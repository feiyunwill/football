# Copyright 2019 Google LLC
# Frame sync server: headless engine + TCP listener, client slot assignment,
# and current-frame pending input collection (frame loop in task 2.2).

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import socket
import struct
import threading
import time

try:
  import gfootball_engine as libgame
  from gfootball_engine import GameState
except ImportError:
  libgame = None
  GameState = None

from gfootball.frame_sync.protocol import (
    MessageType,
    SlotInput,
    default_slot_input,
    pack_authoritative_frame,
    pack_slot_input,
    pack_session_start,
    pack_slot_assignment,
    pack_ready,
    pack_state_hash,
    compute_state_hash,
    unpack_client_frame_input,
    unpack_version_negotiate,
    pack_heartbeat,
    SLOT_INPUT_BYTES,
    FRAME_INPUT_TIMEOUT_MS,
    PROTOCOL_VERSION,
    VERSION_NEGOTIATE_BYTES,
)
from gfootball.frame_sync.config import HEARTBEAT_INTERVAL_MS


def get_scenario_config(scenario_name, left_agents, right_agents, seed):
  """Build ScenarioConfig for the given scenario and agent counts."""
  from gfootball.env import config as cfg
  # 2026-08-26 确定性修复（原因）：不预先提供 game_engine_random_seed 时，
  # NewScenario 内部（env/scenario_builder.py）会用全局 random.randint 兜底，
  # 并令 reverse_team_processing = bool(该随机 seed 的奇偶)；本函数随后仅覆写
  # game_engine_random_seed，reverse 标志残留每进程随机值，导致相同 seed 跨进程
  # 队伍处理顺序不同、模拟真实分叉。改为在 Config 中预置 seed（消除 randint），
  # 并显式按入参 seed 同步派生 reverse_team_processing。
  cfg_obj = cfg.Config({
      'level': scenario_name,
      'game_engine_random_seed': seed,
      'players': [
          'agent:left_players=%d,right_players=%d' % (left_agents, right_agents)
      ],
  })
  cfg_obj.NewScenario(inc=0)
  scenario_config = cfg_obj.ScenarioConfig()
  scenario_config.game_engine_random_seed = seed
  scenario_config.reverse_team_processing = bool(seed % 2)
  return scenario_config


class FrameSyncServer(object):
  """Server process skeleton: headless env, TCP listen, client slot assignment,
  and per-frame pending input (slot -> SlotInput; which clients have sent).
  """

  def __init__(
      self,
      listen_host='0.0.0.0',
      listen_port=12345,
      scenario_name='academy_empty_goal',
      left_agents=1,
      right_agents=0,
      game_engine_random_seed=42,
      state_hash_interval=0,
  ):
    self.listen_host = listen_host
    self.listen_port = listen_port
    self.scenario_name = scenario_name
    self.left_agents = left_agents
    self.right_agents = right_agents
    self.game_engine_random_seed = game_engine_random_seed
    self.num_slots = left_agents + right_agents
    self._state_hash_interval = state_hash_interval  # 0 = disabled; e.g. 10 = every 10 frames

    self._env = None
    self._sock = None
    self._clients = []  # list of (conn, addr, assigned_slots, ready_flag)
    self._lock = threading.Lock()
    self._heartbeat_thread = None  # 2026-08-28 心跳广播线程
    # Current frame pending: slot index -> SlotInput (default until overwritten by client)
    self._current_frame_inputs = None
    # Set of client indices that have sent input for current frame
    self._received_from = None
    self._frame_id = 0
    self._running = False

  def _init_env(self):
    if libgame is None:
      raise RuntimeError('gfootball_engine not available')
    self._env = libgame.GameEnv()
    self._env.game_config.render = False
    self._env.game_config.physics_steps_per_frame = 10
    self._env.game_config.render_resolution_x = 1280
    self._env.game_config.render_resolution_y = 720
    self._env.start_game()
    scenario_config = get_scenario_config(
        self.scenario_name,
        self.left_agents,
        self.right_agents,
        self.game_engine_random_seed,
    )
    self._env.state = GameState.game_running
    self._env.reset(scenario_config, False)

  def _read_message(self, conn):
    """Read one message: 1-byte type then type-dependent length."""
    try:
      buf = bytearray()
      chunk = conn.recv(1)
      if not chunk:
        return None, None
      buf.extend(chunk)
      msg_type = buf[0]
      if msg_type == MessageType.FrameInput:
        while len(buf) < 7:
          chunk = conn.recv(7 - len(buf))
          if not chunk:
            return None, None
          buf.extend(chunk)
        frame_id = struct.unpack_from('<I', buf, 1)[0]
        num_slots = struct.unpack_from('<H', buf, 5)[0]
        rest = num_slots * (2 + SLOT_INPUT_BYTES)
        while len(buf) < 7 + rest:
          chunk = conn.recv(7 + rest - len(buf))
          if not chunk:
            return None, None
          buf.extend(chunk)
        return msg_type, bytes(buf)
      if msg_type == MessageType.VersionNegotiate:
        # 2026-08-28 读取版本协商剩余 4 字节：version(2) + min_version(2)
        while len(buf) < VERSION_NEGOTIATE_BYTES:
          chunk = conn.recv(VERSION_NEGOTIATE_BYTES - len(buf))
          if not chunk:
            return None, None
          buf.extend(chunk)
        return msg_type, bytes(buf)
      if msg_type in (MessageType.Connect, MessageType.Ready, MessageType.Disconnect):
        return msg_type, bytes(buf)
      return msg_type, None
    except (socket.error, struct.error):
      return None, None

  def _assign_slots_for_new_client(self):
    """Assign slots to the new client (simple: one client = one slot in order)."""
    used = set()
    # 2026-08-25 修复（原因）：_clients 元素为 4 元组 (conn, addr, slots, ready_flag)，
    # 旧 3 元组解包在槽位分配路径会抛 ValueError
    # for _conn, _addr, slots in self._clients:
    for _conn, _addr, slots, _ready in self._clients:
      used.update(slots)
    for slot in range(self.num_slots):
      if slot not in used:
        return [slot]
    return []

  def _handle_client(self, conn, addr, client_index):
    """Handle one client: read messages and update current frame inputs."""
    assigned_slots = self._clients[client_index][2]
    # 2026-08-28 版本协商标记：收到 VersionNegotiate 后发送 SessionStart
    version_negotiated = False
    while self._running:
      msg_type, data = self._read_message(conn)
      if data is None:
        break
      if msg_type == MessageType.FrameInput:
        try:
          frame_id, entries = unpack_client_frame_input(data)
          with self._lock:
            if self._current_frame_inputs is not None and frame_id == self._frame_id:
              for slot_index, slot_inp in entries:
                if 0 <= slot_index < self.num_slots and slot_index in assigned_slots:
                  self._current_frame_inputs[slot_index] = slot_inp
              self._received_from.add(client_index)
        except ValueError:
          pass
      elif msg_type == MessageType.VersionNegotiate:
        # 2026-08-28 版本协商：检查客户端版本兼容性
        try:
          client_ver, client_min = unpack_version_negotiate(data)
          if client_ver < PROTOCOL_VERSION or PROTOCOL_VERSION < client_min:
            # 版本不兼容：断开连接
            conn.close()
            return
          # 版本兼容：发送 SessionStart + SlotAssignment
          if not version_negotiated:
            version_negotiated = True
            conn.sendall(
                pack_session_start(
                    self.game_engine_random_seed,
                    self.left_agents,
                    self.right_agents,
                )
            )
            conn.sendall(pack_slot_assignment(assigned_slots))
        except ValueError:
          pass
      elif msg_type == MessageType.Heartbeat:
        # 2026-08-28 客户端心跳回复：仅确认连接存活，不需回复
        pass
      elif msg_type == MessageType.Ready:
        with self._lock:
          if client_index < len(self._clients) and self._clients[client_index][0] is conn:
            self._clients[client_index] = (
                self._clients[client_index][0],
                self._clients[client_index][1],
                self._clients[client_index][2],
                True,
            )
      elif msg_type == MessageType.Disconnect:
        break
    try:
      conn.close()
    except socket.error:
      pass
    with self._lock:
      self._clients[client_index] = (None, None, assigned_slots, False)

  def _accept_loop(self):
    while self._running and self._sock:
      try:
        conn, addr = self._sock.accept()
        with self._lock:
          slots = self._assign_slots_for_new_client()
          if not slots:
            conn.close()
            continue
          self._clients.append((conn, addr, slots, False))
          idx = len(self._clients) - 1
        # 2026-08-28 版本协商由 handle_client 线程在消息循环中处理。
        # 服务器不在 accept 循环中阻塞读取，避免与 handle_client 的竞态。
        # 启动 handle_client 线程
        t = threading.Thread(
            target=self._handle_client,
            args=(conn, addr, idx),
            daemon=True,
        )
        t.start()
      # 2026-08-26 修复（原因）：settimeout(1.0) 使 accept() 无连接时每秒抛 socket.timeout
      #（socket.error 子类），旧 except 在 _running 时 re-raise，accept 线程启动 1 秒后即
      # 死亡，此后任何客户端都无法接入。超时属预期轮询，吞掉并继续循环。
      # except socket.error:
      #   if self._running:
      #     raise
      except socket.timeout:
        continue
      except socket.error:
        if self._running:
          raise

  def _heartbeat_loop(self):
    """2026-08-28 心跳广播线程：周期性向所有已连接客户端发送 Heartbeat。"""
    period = HEARTBEAT_INTERVAL_MS / 1000.0
    while self._running:
      time.sleep(period)
      if not self._running:
        break
      with self._lock:
        frame_id = self._frame_id
      hb = pack_heartbeat(frame_id, int(time.time() * 1000) & 0xFFFFFFFF)
      self.send_to_all(hb)

  def start(self):
    """Initialize headless env and start TCP listener."""
    self._init_env()
    self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self._sock.bind((self.listen_host, self.listen_port))
    self._sock.listen(8)
    self._sock.settimeout(1.0)
    self._running = True
    accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
    accept_thread.start()
    # 2026-08-28 启动心跳广播线程
    self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
    self._heartbeat_thread.start()

  def stop(self):
    self._running = False
    if self._heartbeat_thread and self._heartbeat_thread.is_alive():
      self._heartbeat_thread.join(timeout=2.0)
    if self._sock:
      try:
        self._sock.close()
      except socket.error:
        pass
      self._sock = None
    # 2026-08-25 修复（原因）：_clients 为 4 元组（含 ready_flag），旧 3 元组解包在
    # stop() 关闭连接时抛 ValueError: too many values to unpack
    # for conn, _addr, _ in self._clients:
    for conn, _addr, _slots, _ready in self._clients:
      if conn:
        try:
          conn.close()
        except socket.error:
          pass
    self._clients = []

  def get_env(self):
    return self._env

  def get_num_slots(self):
    return self.num_slots

  def start_frame_collect(self):
    """Start collecting input for the current frame_id. Call before waiting."""
    with self._lock:
      self._current_frame_inputs = [
          default_slot_input() for _ in range(self.num_slots)
      ]
      self._received_from = set()

  def get_current_frame_inputs(self):
    """Return current frame inputs (slot index -> SlotInput). May have defaults."""
    with self._lock:
      if self._current_frame_inputs is None:
        return [default_slot_input() for _ in range(self.num_slots)]
      return list(self._current_frame_inputs)

  def get_received_from(self):
    with self._lock:
      return set(self._received_from) if self._received_from else set()

  def get_connected_client_count(self):
    with self._lock:
      return sum(1 for c in self._clients if c[0] is not None)

  def all_clients_ready(self):
    """True if every connected client has sent Ready."""
    with self._lock:
      for conn, _addr, _slots, ready in self._clients:
        if conn is not None and not ready:
          return False
      return sum(1 for c in self._clients if c[0] is not None) > 0

  def send_to_all(self, data):
    with self._lock:
      # 2026-08-25 修复（原因）：_clients 为 4 元组（含 ready_flag），旧 3 元组解包会抛 ValueError
      # for conn, _, _ in self._clients:
      for conn, _, _slots, _ready in self._clients:
        if conn:
          try:
            conn.sendall(data)
          except socket.error:
            pass

  def advance_frame_id(self):
    with self._lock:
      self._frame_id += 1

  def get_frame_id(self):
    with self._lock:
      return self._frame_id

  def _build_frame_input_buffer(self, slot_inputs):
    """Build raw buffer for engine StepWithInput: num_slots * SlotInput in order."""
    buf = bytearray()
    for s in slot_inputs:
      buf.extend(pack_slot_input(s))
    return bytes(buf)

  def run_one_frame(self, timeout_ms=None):
    """Collect inputs (with optional timeout), run one env step, broadcast authoritative frame."""
    if timeout_ms is None:
      timeout_ms = FRAME_INPUT_TIMEOUT_MS
    self.start_frame_collect()
    deadline = time.time() + timeout_ms / 1000.0
    n_connected = self.get_connected_client_count()
    while time.time() < deadline:
      received = self.get_received_from()
      if n_connected == 0 or len(received) >= n_connected:
        break
      time.sleep(0.005)
    slot_inputs = self.get_current_frame_inputs()
    frame_buf = self._build_frame_input_buffer(slot_inputs)
    self._env.step_with_input(frame_buf)
    frame_id = self.get_frame_id()
    self.send_to_all(pack_authoritative_frame(frame_id, slot_inputs))
    if getattr(self, '_state_hash_interval', 0) > 0 and frame_id % self._state_hash_interval == 0:
      # 2026-08-26 改用 canonical digest（原因）：全量 get_state 序列化含引擎
      # setValidate(false) 标记的不稳定区段（相机/球员颜色缓冲/边裁/HID），
      # 跨进程 hash 必然不同，校验会误报；digest 跳过这些区段，仅含比赛逻辑状态。
      # state_str = self._env.get_state('')
      digest = self._env.get_state_digest()
      h = compute_state_hash(
          digest if isinstance(digest, bytes) else digest.encode()
      )
      self.send_to_all(pack_state_hash(frame_id, h))
    self.advance_frame_id()

  def run_loop(self, rate_hz=10, wait_for_ready=True):
    """Run frame loop at fixed rate until stop. 10 Hz = 1 env step per second.
    If wait_for_ready, blocks until at least one client connected and all have sent Ready."""
    if wait_for_ready:
      while self._running and not self.all_clients_ready():
        time.sleep(0.05)
    period = 1.0 / rate_hz
    while self._running:
      t0 = time.time()
      self.run_one_frame()
      elapsed = time.time() - t0
      if elapsed < period:
        time.sleep(period - elapsed)
