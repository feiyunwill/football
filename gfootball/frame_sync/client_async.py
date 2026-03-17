# Copyright 2019 Google LLC
# Frame sync client (asyncio): same protocol as client.py, using asyncio.open_connection
# and StreamReader/StreamWriter. Sync API (pop_authoritative_frame, send_ready, etc.)
# so ClientLogicLoop can be used unchanged. Call connect_async() from an event loop.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import asyncio
import collections
import struct
import threading

try:
  import gfootball_engine as libgame
  from gfootball_engine import GameState
except ImportError:
  libgame = None
  GameState = None

from gfootball.frame_sync.protocol import (
    MessageType,
    pack_client_frame_input,
    pack_ready,
    compute_state_hash,
    unpack_authoritative_frame,
    unpack_session_start,
    unpack_slot_assignment,
    unpack_state_hash,
    SLOT_INPUT_BYTES,
    STATE_HASH_BYTES,
)
from gfootball.frame_sync.protocol import SESSION_START_PAYLOAD_BYTES


class FrameSyncClientAsync(object):
  """Asyncio frame sync client: connect_async(), then same sync API as FrameSyncClient
  (pop_authoritative_frame, send_ready, send_frame_input, etc.) for ClientLogicLoop.
  Writes are scheduled on the event loop via call_soon_threadsafe."""

  def __init__(self, host, port, controlled_slots_callback=None):
    self.host = host
    self.port = port
    self.controlled_slots_callback = controlled_slots_callback or (lambda: [])
    self._reader = None
    self._writer = None
    self._loop = None
    self._lock = threading.Lock()
    self._recv_buf = bytearray()
    self._auth_frame_queue = collections.deque()
    self._session_start = None
    self._slot_assignment = None
    self._last_state_hash = None
    self._running = False
    self._recv_task = None
    self._last_auth_frame_id = -1
    self._frames_without_packet = 0
    self._disconnect_after_frames = 30
    self._disconnected = False
    self._session_ready = None  # asyncio.Event set when SessionStart+SlotAssignment received
    self._writer_lock = None  # asyncio.Lock, created when connected

  async def connect_async(self):
    """Connect to server, wait for SessionStart + SlotAssignment, return (session_start, slot_assignment)."""
    self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
    self._loop = asyncio.get_running_loop()
    self._writer_lock = asyncio.Lock()
    self._session_ready = asyncio.Event()
    self._running = True
    self._recv_task = asyncio.create_task(self._recv_loop_async())
    try:
      await asyncio.wait_for(self._session_ready.wait(), timeout=10.0)
    except asyncio.TimeoutError:
      self._running = False
      if self._recv_task:
        self._recv_task.cancel()
      self._writer.close()
      await self._writer.wait_closed()
      raise RuntimeError('Did not receive SessionStart and SlotAssignment')
    with self._lock:
      if self._session_start is None or self._slot_assignment is None:
        raise RuntimeError('Did not receive SessionStart and SlotAssignment')
      return self._session_start, self._slot_assignment

  def _parse_one_message(self):
    if len(self._recv_buf) < 1:
      return None, None
    msg_type = self._recv_buf[0]
    if msg_type == MessageType.AuthoritativeFrame:
      if len(self._recv_buf) < 7:
        return None, None
      num_slots = struct.unpack_from('<H', self._recv_buf, 5)[0]
      need = 7 + num_slots * SLOT_INPUT_BYTES
      if len(self._recv_buf) < need:
        return None, None
      data = bytes(self._recv_buf[:need])
      del self._recv_buf[:need]
      try:
        frame_id, slot_inputs = unpack_authoritative_frame(data)
        return msg_type, (frame_id, slot_inputs)
      except ValueError:
        return None, None
    if msg_type == MessageType.SessionStart:
      need = 1 + SESSION_START_PAYLOAD_BYTES
      if len(self._recv_buf) < need:
        return None, None
      data = bytes(self._recv_buf[:need])
      del self._recv_buf[:need]
      try:
        seed, left, right = unpack_session_start(data)
        return msg_type, (seed, left, right)
      except ValueError:
        return None, None
    if msg_type == MessageType.SlotAssignment:
      if len(self._recv_buf) < 1 + 2:
        return None, None
      num = struct.unpack_from('<H', self._recv_buf, 1)[0]
      need = 1 + 2 + num * 2
      if len(self._recv_buf) < need:
        return None, None
      data = bytes(self._recv_buf[:need])
      del self._recv_buf[:need]
      try:
        slots = unpack_slot_assignment(data)
        return msg_type, slots
      except ValueError:
        return None, None
    if msg_type == MessageType.StateHash:
      if len(self._recv_buf) < STATE_HASH_BYTES:
        return None, None
      data = bytes(self._recv_buf[:STATE_HASH_BYTES])
      del self._recv_buf[:STATE_HASH_BYTES]
      try:
        return msg_type, unpack_state_hash(data)
      except ValueError:
        return None, None
    return None, None

  async def _recv_loop_async(self):
    while self._running and self._reader:
      try:
        chunk = await self._reader.read(4096)
        if not chunk:
          break
        with self._lock:
          self._recv_buf.extend(chunk)
          while True:
            msg_type, payload = self._parse_one_message()
            if payload is None:
              break
            if msg_type == MessageType.AuthoritativeFrame:
              self._auth_frame_queue.append(payload)
              self._last_auth_frame_id = payload[0]
              self._frames_without_packet = 0
            elif msg_type == MessageType.StateHash:
              self._last_state_hash = payload
            elif msg_type == MessageType.SessionStart:
              self._session_start = payload
            elif msg_type == MessageType.SlotAssignment:
              self._slot_assignment = payload
              self._session_ready.set()
      except (asyncio.CancelledError, ConnectionResetError, OSError):
        break

  def _schedule_send(self, data):
    if self._writer is None or self._loop is None:
      return

    async def _do_send():
      try:
        async with self._writer_lock:
          self._writer.write(data)
          await self._writer.drain()
      except (OSError, ConnectionResetError, asyncio.CancelledError):
        pass

    self._loop.call_soon_threadsafe(
        lambda: asyncio.ensure_future(_do_send())
    )

  def send_ready(self):
    self._schedule_send(pack_ready())

  def send_frame_input(self, frame_id):
    entries = self.controlled_slots_callback()
    if not entries:
      return
    self._schedule_send(pack_client_frame_input(frame_id, entries))

  def pop_authoritative_frame(self):
    with self._lock:
      if not self._auth_frame_queue:
        return None
      self._frames_without_packet = 0
      return self._auth_frame_queue.popleft()

  def has_authoritative_frame(self):
    with self._lock:
      return len(self._auth_frame_queue) > 0

  def tick_disconnect_detection(self):
    with self._lock:
      if not self._auth_frame_queue:
        self._frames_without_packet += 1
      if self._frames_without_packet >= self._disconnect_after_frames:
        self._disconnected = True

  def is_disconnected(self):
    with self._lock:
      return self._disconnected

  def pop_state_hash(self):
    with self._lock:
      out = self._last_state_hash
      self._last_state_hash = None
      return out

  def check_state_hash(self, frame_id, local_state_str):
    h = self.pop_state_hash()
    if h is None:
      return True
    fid, server_hash = h
    if fid != frame_id:
      return True
    local_hash = compute_state_hash(
        local_state_str if isinstance(local_state_str, bytes) else local_state_str.encode()
    )
    return local_hash == server_hash

  def close(self):
    w = self._writer
    loop = self._loop
    self._running = False
    self._writer = None
    self._reader = None
    self._loop = None
    if self._recv_task and not self._recv_task.done():
      self._recv_task.cancel()
    if loop and w:
      try:
        loop.call_soon_threadsafe(lambda: w.close())
      except Exception:
        pass
