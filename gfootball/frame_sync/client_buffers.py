# Copyright 2026 Google LLC
# 2026-09-09: bounded Python TCP state shared independently of the IO mechanism.
"""Strict frame stream decoding and client APIs; callers serialize buffer access.

Payload budgets charge sys.getsizeof(bytes), including the Python bytes header.
Queue/dict metadata has separate count limits. These are retained application
budgets, not process RSS, kernel socket buffers or objects returned to callers.
"""
import collections
from dataclasses import dataclass
import itertools
import math
import struct
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire


class ClientFailure(RuntimeError):
  def __init__(self, reason):
    self.reason = reason
    super().__init__(reason)


@dataclass(frozen=True)
class ClientLimits:
  receive_bytes: int = 8192
  authority_frames: int = 1024
  authority_bytes: int = 512 * 1024
  hashes: int = 1024
  timestamps: int = 1024
  send_messages: int = 256
  send_bytes: int = 2 * 1024 * 1024
  connect_timeout: float = 5.0
  handshake_timeout: float = 5.0
  ready_timeout: float = 30.0
  idle_timeout: float = 3.0
  write_timeout: float = 5.0

  def __post_init__(self):
    for name, minimum, maximum in (
        ('receive_bytes', 512, 8192), ('authority_frames', 1, 1024),
        ('authority_bytes', 64, 4 * 1024 * 1024), ('hashes', 1, 1024),
        ('timestamps', 1, 1024), ('send_messages', 1, 1024),
        ('send_bytes', 64, 4 * 1024 * 1024)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid client limit: ' + name)
    for name in ('connect_timeout', 'handshake_timeout', 'ready_timeout', 'idle_timeout', 'write_timeout'):
      value = getattr(self, name)
      if type(value) not in (int, float) or not math.isfinite(value) or not 0.01 <= value <= 30:
        raise ValueError('Invalid client timeout: ' + name)


class ClientBuffers:
  def __init__(self, limits):
    self.limits = limits
    self.receive = b''
    self.authority = collections.deque()
    self.authority_bytes = 0
    self.hashes = {}
    self.timestamps = collections.OrderedDict()
    self.rtt = collections.deque(maxlen=50)
    self.session = None
    self.slots = None
    self.bots = set()
    self.next_authority = 0
    self.phase = 'session'
    self.failure = None
    self.last_packet = time.monotonic()
    self.ready_since = None

  def fail(self, reason):
    if self.failure is None:
      self.failure = reason
    self.phase = 'closed'
    self.receive = b''
    self.authority.clear()
    self.authority_bytes = 0
    self.hashes.clear()
    self.timestamps.clear()
    self.rtt.clear()
    self.bots.clear()

  def feed(self, chunk, now=None):
    if self.phase == 'closed':
      raise ClientFailure('closed')
    now = time.monotonic() if now is None else now
    try:
      if not isinstance(chunk, bytes) or sys.getsizeof(self.receive) + len(chunk) > self.limits.receive_bytes:
        raise ClientFailure('receive_capacity')
      self.receive += chunk
      while self._parse(now):
        self.last_packet = now  # Partial bytes do not extend the progress deadline.
    except ClientFailure as error:
      self.fail(error.reason)
      raise

  def _parse(self, now):
    data = self.receive
    if not data:
      return False
    kind = data[0]
    if kind == wire.MessageType.Heartbeat:
      if len(data) < wire.HEARTBEAT_BYTES:
        return False
      used = wire.HEARTBEAT_BYTES
    elif kind == wire.MessageType.SessionStart:
      if self.phase != 'session':
        raise ClientFailure('unexpected_session')
      if len(data) < 9:
        return False
      seed, left, right = wire.unpack_session_start(data[:9])
      if left > 11 or right > 11 or not 1 <= left + right <= 22:
        raise ClientFailure('invalid_session')
      self.session = (seed, left, right)
      self.phase = 'slots'
      used = 9
    elif kind == wire.MessageType.SlotAssignment:
      if self.phase != 'slots':
        raise ClientFailure('unexpected_slots')
      if len(data) < 3:
        return False
      count = struct.unpack_from('<H', data, 1)[0]
      total = self.session[1] + self.session[2]
      if not 1 <= count <= total:
        raise ClientFailure('invalid_slots')
      used = 3 + 2 * count
      if len(data) < used:
        return False
      slots = tuple(struct.unpack_from('<H', data, 3 + 2 * i)[0] for i in range(count))
      if len(set(slots)) != count or any(slot >= total for slot in slots):
        raise ClientFailure('invalid_slots')
      self.slots = slots
      self.phase = 'ready'
      self.ready_since = now
    elif kind in (wire.MessageType.TakeoverNotify, wire.MessageType.HandbackNotify):
      if self.session is None:
        raise ClientFailure('unexpected_control')
      if len(data) < 7:
        return False
      slot = struct.unpack_from('<H', data, 1)[0]
      if slot >= self.session[1] + self.session[2]:
        raise ClientFailure('invalid_control')
      if kind == wire.MessageType.TakeoverNotify:
        self.bots.add(slot)
      else:
        self.bots.discard(slot)
      used = 7
    elif kind == wire.MessageType.AuthoritativeFrame:
      if self.phase != 'streaming':
        raise ClientFailure('unexpected_authority')
      if len(data) < 7:
        return False
      frame, count = struct.unpack_from('<IH', data, 1)
      if count != self.session[1] + self.session[2] or frame != self.next_authority or frame > 0xfffffff7:
        raise ClientFailure('invalid_authority')
      used = 7 + count * wire.SLOT_INPUT_BYTES
      if len(data) < used:
        return False
      packet = data[:used]
      _, inputs = wire.unpack_authoritative_frame(packet)
      if not all(wire.is_valid_slot_input(value) for value in inputs):
        raise ClientFailure('invalid_input')
      retained = sys.getsizeof(packet)
      if len(self.authority) >= self.limits.authority_frames or retained > self.limits.authority_bytes - self.authority_bytes:
        raise ClientFailure('authority_capacity')
      self.authority.append(packet)
      self.authority_bytes += retained
      self.next_authority += 1
      if frame in self.timestamps:
        self.rtt.append(max(0.0, (now - self.timestamps[frame]) * 1000.0))
      # Older unmatched timing samples are diagnostics, never authoritative data.
      while self.timestamps and next(iter(self.timestamps)) <= frame:
        self.timestamps.popitem(last=False)
    elif kind == wire.MessageType.StateHash:
      if self.phase != 'streaming':
        raise ClientFailure('unexpected_hash')
      used = wire.STATE_HASH_BYTES
      if len(data) < used:
        return False
      frame, digest = wire.unpack_state_hash(data[:used])
      if frame > 0xfffffff7 or (frame in self.hashes and self.hashes[frame] != digest):
        raise ClientFailure('invalid_hash')
      if frame not in self.hashes and len(self.hashes) >= self.limits.hashes:
        raise ClientFailure('hash_capacity')
      self.hashes[frame] = digest
    else:
      # Snapshot/delta messages require a negotiated bootstrap/decoder. The
      # ordinary initial-session parser must never byte-skip unsupported data.
      raise ClientFailure('unsupported_message')
    self.receive = data[used:]
    return True

  def pop_authority(self):
    if not self.authority:
      return None
    packet = self.authority.popleft()
    self.authority_bytes -= sys.getsizeof(packet)
    return wire.unpack_authoritative_frame(packet)

  def record_send(self, frame, now):
    if frame < self.next_authority or frame in self.timestamps:
      return
    if len(self.timestamps) == self.limits.timestamps:
      self.timestamps.popitem(last=False)
    self.timestamps[frame] = now

  def timeout(self, now):
    if self.phase == 'streaming' and now - self.last_packet >= self.limits.idle_timeout:
      return 'idle_timeout'
    if self.phase == 'ready' and now - self.ready_since >= self.limits.ready_timeout:
      return 'ready_timeout'
    return None


class BufferedClientAPI:
  """Common public API. Concrete transports implement enqueue/failure under lock."""
  def _init_buffers(self, host, port, callback, limits, handshake):
    if not isinstance(host, str) or not host or len(host.encode('utf-8')) > 253 or '\x00' in host:
      raise ValueError('Invalid TCP host')
    if type(port) is not int or not 1 <= port <= 65535:
      raise ValueError('Invalid TCP port')
    if callback is not None and not callable(callback):
      raise ValueError('Input callback must be callable')
    # 2026-09-09: preserve the asyncio server's existing server-first handshake.
    # if handshake not in ('versioned', 'native'):
    if handshake not in ('versioned', 'native', 'server_first'):
      raise ValueError('Unknown TCP handshake')
    if limits is not None and not isinstance(limits, ClientLimits):
      raise ValueError('Expected ClientLimits')
    self.host, self.port = host, port
    self.controlled_slots_callback = callback or (lambda: [])
    self.limits = limits or ClientLimits()
    self.handshake = handshake
    self._lock = threading.RLock()
    self._buffers = ClientBuffers(self.limits)
    self._buffers.fail('closed')
    # 2026-09-10: clients must send liveness even while waiting for a match/input.
    self._heartbeat_generation = None
    self._next_heartbeat = 0.0

  def _heartbeat_locked(self, now):
    if self._buffers.phase not in ('ready', 'streaming'):
      return True
    interval = max(.01, min(1.0, self.limits.idle_timeout / 3))
    if self._heartbeat_generation != self._generation:
      self._heartbeat_generation = self._generation
      self._next_heartbeat = now + interval
    if now < self._next_heartbeat:
      return True
    self._next_heartbeat = now + interval
    # Periodic probes avoid echo loops with servers that echo received heartbeats.
    return self._enqueue_locked(wire.pack_heartbeat(max(0, self._buffers.next_authority - 1),
                                                   int(now * 1000) & 0xffffffff))

  def send_ready(self):
    with self._lock:
      if self._buffers.phase == 'streaming':
        return True
      if self._buffers.phase != 'ready':
        return False
      if not self._enqueue_locked(wire.pack_ready()):
        return False
      self._buffers.phase = 'streaming'
      self._buffers.last_packet = time.monotonic()
      return True

  # 2026-09-09: one sampled input can feed both network and prediction. Keep
  # the callback API, adding an explicit bounded-entry API for the logic owner.
  # def send_frame_input(self, frame_id):
  #   with self._lock:
  #     if self._buffers.phase != 'streaming':
  #       return False
  #     generation = self._generation
  #   try:
  #     # User callbacks run outside the transport lock; bound even a generator.
  #     entries = list(itertools.islice(iter(self.controlled_slots_callback()), 23))
  #     with self._lock:
  #       if generation != self._generation or self._buffers.phase != 'streaming':
  #         return False
  #       if not entries:
  #         return False
  #       if (type(frame_id) is not int or not 0 <= frame_id <= 0xfffffff7 or
  #           len(entries) != len(self._buffers.slots) or
  #           any(type(slot) is not int or slot != expected or not wire.is_valid_slot_input(value)
  #               for (slot, value), expected in zip(entries, self._buffers.slots))):
  #         raise ValueError('Invalid client input')
  #       packet = wire.pack_client_frame_input(frame_id, entries)
  #       if not self._enqueue_locked(packet):
  #         return False
  #       self._buffers.record_send(frame_id, time.monotonic())
  #       return True
  #   except Exception:
  #     with self._lock:
  #       if generation == self._generation:
  #         self._fail_locked('invalid_input')
  #     raise
  def send_frame_input(self, frame_id):
    return self._send_frame_entries(frame_id, self.controlled_slots_callback)

  def send_frame_entries(self, frame_id, entries):
    """Send already sampled input without calling the transport input callback."""
    return self._send_frame_entries(frame_id, lambda: entries)

  def _send_frame_entries(self, frame_id, sample):
    with self._lock:
      if self._buffers.phase != 'streaming':
        return False
      generation = self._generation
    try:
      entries = list(itertools.islice(iter(sample()), 23))
      with self._lock:
        if generation != self._generation or self._buffers.phase != 'streaming':
          return False
        if not entries:
          return False
        if (type(frame_id) is not int or not 0 <= frame_id <= 0xfffffff7 or
            len(entries) != len(self._buffers.slots) or
            any(type(slot) is not int or slot != expected or not wire.is_valid_slot_input(value)
                for (slot, value), expected in zip(entries, self._buffers.slots))):
          raise ValueError('Invalid client input')
        packet = wire.pack_client_frame_input(frame_id, entries)
        if not self._enqueue_locked(packet):
          return False
        self._buffers.record_send(frame_id, time.monotonic())
        return True
    except Exception:
      with self._lock:
        if generation == self._generation:
          self._fail_locked('invalid_input')
      raise

  def pop_authoritative_frame(self):
    with self._lock:
      return self._buffers.pop_authority()

  def has_authoritative_frame(self):
    with self._lock:
      return bool(self._buffers.authority)

  def pop_state_hash(self):
    with self._lock:
      if not self._buffers.hashes:
        return None
      frame = next(iter(self._buffers.hashes))
      return frame, self._buffers.hashes.pop(frame)

  def check_state_hash(self, frame_id, local_state_str):
    """Compare a matching canonical digest without discarding other frames."""
    with self._lock:
      if self._buffers.phase == 'closed':
        return False
      expected = self._buffers.hashes.get(frame_id)
      if expected is None:
        return True
      generation = self._generation
    data = local_state_str if isinstance(local_state_str, bytes) else local_state_str.encode()
    matched = wire.compute_state_hash(data) == expected
    with self._lock:
      if generation != self._generation or self._buffers.phase == 'closed':
        return False
      if not matched:
        self._fail_locked('hash_mismatch')
        return False
      self._buffers.hashes.pop(frame_id, None)
      return True

  def tick_disconnect_detection(self):
    with self._lock:
      reason = self._buffers.timeout(time.monotonic())
      if reason:
        self._fail_locked(reason)

  def is_disconnected(self):
    with self._lock:
      return self._buffers.phase == 'closed'

  @property
  def failure_reason(self):
    with self._lock:
      return self._buffers.failure

  def get_rtt_samples(self):
    with self._lock:
      return list(self._buffers.rtt)

  def get_rtt_ms(self):
    with self._lock:
      return self._buffers.rtt[-1] if self._buffers.rtt else 0.0

  def get_avg_rtt_ms(self):
    with self._lock:
      return sum(self._buffers.rtt) / len(self._buffers.rtt) if self._buffers.rtt else 0.0

  def get_input_latency_ms(self):
    return self.get_avg_rtt_ms() / 2.0

  def stats(self):
    with self._lock:
      state = self._buffers
      return dict(authority_frames=len(state.authority), authority_bytes=state.authority_bytes,
                  receive_bytes=sys.getsizeof(state.receive), hashes=len(state.hashes),
                  timestamps=len(state.timestamps), rtt_samples=len(state.rtt),
                  # 2026-09-09: retain the active asynchronous write in its budget.
                  # send_messages=len(self._send_queue), send_bytes=self._send_bytes)
                  send_messages=len(self._send_queue) + (getattr(self, "_active_send", None) is not None),
                  send_bytes=self._send_bytes)
