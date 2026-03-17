# Copyright 2019 Google LLC
# Frame sync client: connect to server, report controlled slots, send frame input,
# receive authoritative frames and buffer them in order for the logic layer.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import socket
import struct
import threading
import collections

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
    pack_client_frame_input,
    pack_slot_input,
    pack_ready,
    compute_state_hash,
    unpack_authoritative_frame,
    unpack_session_start,
    unpack_slot_assignment,
    unpack_state_hash,
    SLOT_INPUT_BYTES,
    STATE_HASH_BYTES,
    MAX_PREDICT_AHEAD_FRAMES,
    MAX_FRAMES_WITHOUT_PACKET,
)


class FrameSyncClient(object):
  """Client: connect to server, receive SessionStart + SlotAssignment, send Ready,
  send FrameInput per frame, receive AuthoritativeFrame and buffer by frame_id for logic.
  """

  def __init__(self, host, port, controlled_slots_callback=None):
    """controlled_slots_callback: callable that returns list of (slot_index, SlotInput) for current frame."""
    self.host = host
    self.port = port
    self.controlled_slots_callback = controlled_slots_callback or (lambda: [])
    self._sock = None
    self._lock = threading.Lock()
    self._recv_buf = bytearray()
    # Authoritative frames in order: list of (frame_id, list of SlotInput)
    self._auth_frame_queue = collections.deque()
    self._session_start = None
    self._slot_assignment = None
    self._last_state_hash = None
    self._running = False
    self._recv_thread = None
    self._last_auth_frame_id = -1
    self._frames_without_packet = 0
    self._disconnect_after_frames = 30  # consider disconnected if no packet for 30 logic frames
    self._disconnected = False

  def connect(self):
    self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._sock.connect((self.host, self.port))
    self._running = True
    self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
    self._recv_thread.start()
    # Wait for SessionStart + SlotAssignment (handled in _recv_loop)
    import time
    for _ in range(100):
      with self._lock:
        if self._session_start is not None and self._slot_assignment is not None:
          break
      time.sleep(0.05)
    with self._lock:
      if self._session_start is None or self._slot_assignment is None:
        raise RuntimeError('Did not receive SessionStart and SlotAssignment')
    return self._session_start, self._slot_assignment

  def _read_bytes(self, n):
    while len(self._recv_buf) < n:
      chunk = self._sock.recv(4096)
      if not chunk:
        return None
      self._recv_buf.extend(chunk)
    out = bytes(self._recv_buf[:n])
    del self._recv_buf[:n]
    return out

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
      from gfootball.frame_sync.protocol import SESSION_START_PAYLOAD_BYTES
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

  def _recv_loop(self):
    while self._running and self._sock:
      try:
        chunk = self._sock.recv(4096)
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
      except (socket.error, ValueError):
        break

  def send_ready(self):
    if self._sock:
      self._sock.sendall(pack_ready())

  def send_frame_input(self, frame_id):
    """Send this frame's input for our controlled slots (from callback)."""
    entries = self.controlled_slots_callback()
    if not entries:
      return
    if self._sock:
      self._sock.sendall(pack_client_frame_input(frame_id, entries))

  def pop_authoritative_frame(self):
    """Return (frame_id, slot_inputs) or None if queue empty. In order."""
    with self._lock:
      if not self._auth_frame_queue:
        return None
      self._frames_without_packet = 0
      return self._auth_frame_queue.popleft()

  def has_authoritative_frame(self):
    with self._lock:
      return len(self._auth_frame_queue) > 0

  def tick_disconnect_detection(self):
    """Call once per logic frame; marks disconnected if no auth packet for N frames."""
    with self._lock:
      if not self._auth_frame_queue:
        self._frames_without_packet += 1
      if self._frames_without_packet >= self._disconnect_after_frames:
        self._disconnected = True

  def is_disconnected(self):
    with self._lock:
      return self._disconnected

  def pop_state_hash(self):
    """Return (frame_id, hash_64) or None for optional verification (5.3)."""
    with self._lock:
      out = self._last_state_hash
      self._last_state_hash = None
      return out

  def check_state_hash(self, frame_id, local_state_str):
    """If server sent a state hash for this frame, compare with local; return True if match or no hash."""
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
    self._running = False
    if self._sock:
      try:
        self._sock.close()
      except socket.error:
        pass
      self._sock = None


def _build_frame_input_buffer(slot_inputs):
  buf = bytearray()
  for s in slot_inputs:
    buf.extend(pack_slot_input(s))
  return bytes(buf)


class ClientLogicLoop(object):
  """Fixed-rate logic loop (task 3.2/3.3): 10 Hz, get_state snapshot, apply
  authoritative or prediction input, step_with_input.
  Prediction: others' input = last received authoritative (per-slot); our slots from callback.
  Rollback: 1-frame depth; when auth arrives for previously predicted frame,
  set_state(rollback_snapshot) and re-step with auth.
  Exposes get_last_confirmed_frame_id() and get_current_frame_id() for display layer interpolation.
  """

  def __init__(
      self,
      client,
      env,
      num_slots,
      controlled_slots_callback,
      rate_hz=10,
      state_holder=None,
  ):
    self._client = client
    self._env = env
    self._num_slots = num_slots
    self._controlled_slots_callback = controlled_slots_callback
    self._rate_hz = rate_hz
    self._state_holder = state_holder
    self._current_frame_id = 0
    self._last_confirmed_frame_id = -1
    self._last_auth_inputs = [default_slot_input() for _ in range(num_slots)]
    self._rollback_snapshot = None
    self._running = False
    self._rollback_count = 0
    self._frames_without_packet = 0
    self._only_authority_mode = False

  def get_last_confirmed_frame_id(self):
    return self._last_confirmed_frame_id

  def get_current_frame_id(self):
    return self._current_frame_id

  def get_rollback_count(self):
    return self._rollback_count

  def is_waiting_for_authority(self):
    """True when prediction is stopped (cap or M frames without packet). For presentation layer."""
    return self._only_authority_mode or (
        self._current_frame_id - self._last_confirmed_frame_id >= MAX_PREDICT_AHEAD_FRAMES
    )

  def run_one_tick(self):
    self._client.send_frame_input(self._current_frame_id)
    self._client.tick_disconnect_detection()
    auth = self._client.pop_authoritative_frame()
    if auth is not None:
      self._frames_without_packet = 0
      self._only_authority_mode = False
    else:
      self._frames_without_packet += 1
      if self._frames_without_packet >= MAX_FRAMES_WITHOUT_PACKET:
        self._only_authority_mode = True

    can_predict = (
        not self._only_authority_mode
        and (self._current_frame_id - self._last_confirmed_frame_id) < MAX_PREDICT_AHEAD_FRAMES
    )

    snapshot = self._env.get_state('')
    if auth is not None:
      frame_id, slot_inputs = auth
      if frame_id == self._current_frame_id:
        frame_buf = _build_frame_input_buffer(slot_inputs)
        self._env.step_with_input(frame_buf)
        self._last_auth_inputs = list(slot_inputs)
        self._last_confirmed_frame_id = self._current_frame_id
        self._current_frame_id += 1
        self._write_state_after_tick()
        return
      if frame_id == self._current_frame_id - 1 and self._rollback_snapshot is not None:
        self._rollback_count += 1
        self._env.set_state(self._rollback_snapshot)
        frame_buf = _build_frame_input_buffer(slot_inputs)
        self._env.step_with_input(frame_buf)
        self._last_auth_inputs = list(slot_inputs)
        self._last_confirmed_frame_id = frame_id
        self._rollback_snapshot = None
        self._write_state_after_tick()
        return
      if frame_id > self._last_confirmed_frame_id and frame_id < self._current_frame_id - 1:
        self._last_confirmed_frame_id = frame_id
        self._last_auth_inputs = list(slot_inputs)
    if not can_predict:
      return
    our_entries = self._controlled_slots_callback()
    pred_inputs = list(self._last_auth_inputs)
    for slot_idx, slot_inp in our_entries:
      if 0 <= slot_idx < self._num_slots:
        pred_inputs[slot_idx] = slot_inp
    self._rollback_snapshot = snapshot
    frame_buf = _build_frame_input_buffer(pred_inputs)
    self._env.step_with_input(frame_buf)
    self._current_frame_id += 1
    if self._state_holder is not None:
      self._state_holder.write(
          self._env.get_state(''),
          self._current_frame_id - 1,
          self._last_confirmed_frame_id,
          waiting_for_authority=self.is_waiting_for_authority(),
      )

  def _write_state_after_tick(self):
    if self._state_holder is not None:
      self._state_holder.write(
          self._env.get_state(''),
          self._current_frame_id - 1,
          self._last_confirmed_frame_id,
          waiting_for_authority=self.is_waiting_for_authority(),
      )

  def run_loop(self):
    import time
    period = 1.0 / self._rate_hz
    self._running = True
    while self._running:
      t0 = time.time()
      self.run_one_tick()
      elapsed = time.time() - t0
      if elapsed < period:
        time.sleep(period - elapsed)

  def stop(self):
    self._running = False
