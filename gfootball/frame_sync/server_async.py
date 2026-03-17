# Copyright 2019 Google LLC
# Frame sync server (asyncio): same protocol as server.py, using asyncio.start_server
# and StreamReader/StreamWriter. Optional alternative for async integration.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import asyncio
import struct

try:
  import gfootball_engine as libgame
  from gfootball_engine import GameState
except ImportError:
  libgame = None
  GameState = None

from gfootball.frame_sync.server import get_scenario_config
from gfootball.frame_sync.protocol import (
    MessageType,
    default_slot_input,
    pack_authoritative_frame,
    pack_slot_input,
    pack_session_start,
    pack_slot_assignment,
    pack_state_hash,
    compute_state_hash,
    unpack_client_frame_input,
    SLOT_INPUT_BYTES,
    FRAME_INPUT_TIMEOUT_MS,
)


class FrameSyncServerAsync(object):
  """Asyncio frame sync server: headless env, asyncio.start_server, per-frame
  input collection, same protocol as FrameSyncServer. Use run_loop_async() in
  an event loop."""

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
    self._state_hash_interval = state_hash_interval

    self._env = None
    self._server = None
    self._lock = asyncio.Lock()
    # (reader, writer, addr, assigned_slots, ready)
    self._clients = []
    self._current_frame_inputs = None
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

  async def _read_message(self, reader):
    """Read one message from StreamReader; returns (msg_type, data) or (None, None)."""
    try:
      h = await reader.read(1)
      if not h:
        return None, None
      msg_type = h[0]
      if msg_type == MessageType.FrameInput:
        rest = await reader.readexactly(6)
        frame_id = struct.unpack_from('<I', rest, 0)[0]
        num_slots = struct.unpack_from('<H', rest, 4)[0]
        need = num_slots * (2 + SLOT_INPUT_BYTES)
        body = await reader.readexactly(need)
        return msg_type, h + rest + body
      if msg_type in (MessageType.Connect, MessageType.Ready, MessageType.Disconnect):
        return msg_type, h
      return msg_type, None
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
      return None, None

  def _assign_slots_for_new_client(self):
    used = set()
    for _r, _w, _addr, slots, _ in self._clients:
      used.update(slots)
    for slot in range(self.num_slots):
      if slot not in used:
        return [slot]
    return []

  async def _handle_client(self, reader, writer, addr, client_index):
    assigned_slots = self._clients[client_index][3]
    try:
      while self._running:
        msg_type, data = await self._read_message(reader)
        if data is None:
          break
        if msg_type == MessageType.FrameInput:
          try:
            frame_id, entries = unpack_client_frame_input(data)
            async with self._lock:
              if self._current_frame_inputs is not None and frame_id == self._frame_id:
                for slot_index, slot_inp in entries:
                  if 0 <= slot_index < self.num_slots and slot_index in assigned_slots:
                    self._current_frame_inputs[slot_index] = slot_inp
                  self._received_from.add(client_index)
          except ValueError:
            pass
        elif msg_type == MessageType.Ready:
          async with self._lock:
            if client_index < len(self._clients):
              r, w, a, sl, _ = self._clients[client_index]
              if r is reader:
                self._clients[client_index] = (r, w, a, sl, True)
        elif msg_type == MessageType.Disconnect:
          break
    finally:
      try:
        writer.close()
        await writer.wait_closed()
      except (OSError, asyncio.CancelledError):
        pass
      async with self._lock:
        if client_index < len(self._clients) and self._clients[client_index][0] is reader:
          self._clients[client_index] = (None, None, addr, assigned_slots, False)

  async def _accept_cb(self, reader, writer):
    addr = writer.get_extra_info('peername')
    async with self._lock:
      slots = self._assign_slots_for_new_client()
      if not slots:
        writer.close()
        await writer.wait_closed()
        return
      self._clients.append((reader, writer, addr, slots, False))
      idx = len(self._clients) - 1
    writer.write(
        pack_session_start(
            self.game_engine_random_seed,
            self.left_agents,
            self.right_agents,
        )
    )
    writer.write(pack_slot_assignment(slots))
    await writer.drain()
    await self._handle_client(reader, writer, addr, idx)

  def start(self):
    """Initialize headless env. Caller must call run_loop_async() in an event loop."""
    self._init_env()
    self._running = True

  async def start_server(self):
    """Create and start the asyncio server. Call after start()."""
    self._server = await asyncio.start_server(
        self._accept_cb,
        self.listen_host,
        self.listen_port,
        reuse_address=True,
    )

  def stop(self):
    self._running = False
    if self._server:
      self._server.close()
      self._server = None
    self._clients = []

  def get_env(self):
    return self._env

  def get_num_slots(self):
    return self.num_slots

  async def start_frame_collect(self):
    async with self._lock:
      self._current_frame_inputs = [
          default_slot_input() for _ in range(self.num_slots)
      ]
      self._received_from = set()

  async def get_current_frame_inputs(self):
    async with self._lock:
      if self._current_frame_inputs is None:
        return [default_slot_input() for _ in range(self.num_slots)]
      return list(self._current_frame_inputs)

  async def get_received_from(self):
    async with self._lock:
      return set(self._received_from) if self._received_from else set()

  async def get_connected_client_count(self):
    async with self._lock:
      return sum(1 for c in self._clients if c[0] is not None)

  async def all_clients_ready(self):
    async with self._lock:
      for c in self._clients:
        if c[0] is not None and not c[4]:
          return False
      return sum(1 for c in self._clients if c[0] is not None) > 0

  async def send_to_all(self, data):
    async with self._lock:
      for _r, w, _a, _s, _ in self._clients:
        if w is not None:
          try:
            w.write(data)
            await w.drain()
          except (OSError, ConnectionResetError):
            pass

  async def advance_frame_id(self):
    async with self._lock:
      self._frame_id += 1

  async def get_frame_id(self):
    async with self._lock:
      return self._frame_id

  def _build_frame_input_buffer(self, slot_inputs):
    buf = bytearray()
    for s in slot_inputs:
      buf.extend(pack_slot_input(s))
    return bytes(buf)

  async def run_one_frame(self, timeout_ms=None):
    if timeout_ms is None:
      timeout_ms = FRAME_INPUT_TIMEOUT_MS
    await self.start_frame_collect()
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000.0
    n_connected = await self.get_connected_client_count()
    while asyncio.get_event_loop().time() < deadline:
      received = await self.get_received_from()
      if n_connected == 0 or len(received) >= n_connected:
        break
      await asyncio.sleep(0.005)
    slot_inputs = await self.get_current_frame_inputs()
    frame_buf = self._build_frame_input_buffer(slot_inputs)
    self._env.step_with_input(frame_buf)
    frame_id = await self.get_frame_id()
    await self.send_to_all(pack_authoritative_frame(frame_id, slot_inputs))
    if self._state_hash_interval > 0 and frame_id % self._state_hash_interval == 0:
      state_str = self._env.get_state('')
      h = compute_state_hash(
          state_str if isinstance(state_str, bytes) else state_str.encode()
      )
      await self.send_to_all(pack_state_hash(frame_id, h))
    await self.advance_frame_id()

  async def run_loop_async(self, rate_hz=10, wait_for_ready=True):
    """Run frame loop at fixed rate until stop()."""
    if self._server is None:
      await self.start_server()
    if wait_for_ready:
      while self._running and not await self.all_clients_ready():
        await asyncio.sleep(0.05)
    period = 1.0 / rate_hz
    while self._running:
      t0 = asyncio.get_event_loop().time()
      await self.run_one_frame()
      elapsed = asyncio.get_event_loop().time() - t0
      if elapsed < period:
        await asyncio.sleep(period - elapsed)
