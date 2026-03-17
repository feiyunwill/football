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
    SLOT_INPUT_BYTES,
    FRAME_INPUT_TIMEOUT_MS,
)


def get_scenario_config(scenario_name, left_agents, right_agents, seed):
  """Build ScenarioConfig for the given scenario and agent counts."""
  from gfootball.env import config as cfg
  cfg_obj = cfg.Config({
      'level': scenario_name,
      'players': [
          'agent:left_players=%d,right_players=%d' % (left_agents, right_agents)
      ],
  })
  cfg_obj.NewScenario(inc=0)
  scenario_config = cfg_obj.ScenarioConfig()
  scenario_config.game_engine_random_seed = seed
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
      if msg_type in (MessageType.Connect, MessageType.Ready, MessageType.Disconnect):
        return msg_type, bytes(buf)
      return msg_type, None
    except (socket.error, struct.error):
      return None, None

  def _assign_slots_for_new_client(self):
    """Assign slots to the new client (simple: one client = one slot in order)."""
    used = set()
    for _conn, _addr, slots in self._clients:
      used.update(slots)
    for slot in range(self.num_slots):
      if slot not in used:
        return [slot]
    return []

  def _handle_client(self, conn, addr, client_index):
    """Handle one client: read messages and update current frame inputs."""
    assigned_slots = self._clients[client_index][2]
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
        t = threading.Thread(
            target=self._handle_client,
            args=(conn, addr, idx),
            daemon=True,
        )
        t.start()
        # Session start: send ScenarioConfig params and this client's slot assignment
        conn.sendall(
            pack_session_start(
                self.game_engine_random_seed,
                self.left_agents,
                self.right_agents,
            )
        )
        conn.sendall(pack_slot_assignment(slots))
      except socket.error:
        if self._running:
          raise

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

  def stop(self):
    self._running = False
    if self._sock:
      try:
        self._sock.close()
      except socket.error:
        pass
      self._sock = None
    for conn, _addr, _ in self._clients:
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
      for conn, _, _ in self._clients:
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
      state_str = self._env.get_state('')
      h = compute_state_hash(
          state_str if isinstance(state_str, bytes) else state_str.encode()
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
