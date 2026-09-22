# 2026-09-10: bounded wire/input/output state shared by both real TCP servers.
"""Single-owner server state; retained bytes and container counts are bounded.

These are application payload budgets, not kernel buffers or process RSS.
No state here creates a socket, engine, worker thread or asynchronous task.
"""
import collections
from dataclasses import dataclass
import math
import struct
import sys
import time

from gfootball.frame_sync import protocol as wire

MAX_FRAME = 0xfffffff7


class ServerFailure(RuntimeError):
  def __init__(self, reason):
    self.reason = reason
    super().__init__(reason)


@dataclass(frozen=True)
class ServerLimits:
  connections: int = 32
  pending_frames: int = 128
  input_bytes: int = 256 * 1024
  receive_bytes: int = 8192
  send_messages: int = 256
  send_bytes: int = 2 * 1024 * 1024
  snapshot_bytes: int = 1024 * 1024
  messages_per_second: int = 1000
  message_burst: int = 128
  handshake_timeout: float = 5.0
  ready_timeout: float = 30.0
  idle_timeout: float = 3.0
  message_timeout: float = 2.0
  write_timeout: float = 5.0
  heartbeat_interval: float = 1.0

  def __post_init__(self):
    for name, minimum, maximum in (
        ('connections', 1, 44), ('pending_frames', 1, 1024),
        ('input_bytes', 64, 4 * 1024 * 1024), ('receive_bytes', 512, 8192),
        ('send_messages', 1, 1024), ('send_bytes', 64, 4 * 1024 * 1024),
        ('snapshot_bytes', 64, 1024 * 1024), ('messages_per_second', 1, 10000),
        ('message_burst', 1, 1024)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid server limit: ' + name)
    for name in ('handshake_timeout', 'ready_timeout', 'idle_timeout',
                 'message_timeout', 'write_timeout', 'heartbeat_interval'):
      value = getattr(self, name)
      if type(value) not in (int, float) or not math.isfinite(value) or not 0.01 <= value <= 30:
        raise ValueError('Invalid server timeout: ' + name)


class ServerDecoder:
  """Consume complete messages; never guess a body length or skip unknown bytes."""
  def __init__(self, limits, num_slots):
    self.limits, self.num_slots = limits, num_slots
    self.data = b''

  @property
  def available(self):
    return self.limits.receive_bytes - sys.getsizeof(self.data)

  def feed(self, data):
    if type(data) is not bytes or len(data) > self.available:
      raise ServerFailure('receive_capacity')
    self.data += data

  def pop(self):
    if not self.data:
      return None
    kind = self.data[0]
    # 2026-09-10: v6 input has a bounded epoch prefix; generic dispatch rejects it.
    # if kind == wire.MessageType.FrameInput:
    #   if len(self.data) < 7:
    if kind in (wire.MessageType.FrameInput, wire.MessageType.MatchEpochInput):
      header = 11 if kind == wire.MessageType.MatchEpochInput else 7
      if len(self.data) < header:
        return None
      # count = struct.unpack_from('<H', self.data, 5)[0]
      count = struct.unpack_from('<H', self.data, header - 2)[0]
      if not 1 <= count <= self.num_slots:
        raise ServerFailure('invalid_input_count')
      # need = 7 + count * (2 + wire.SLOT_INPUT_BYTES)
      need = header + count * (2 + wire.SLOT_INPUT_BYTES)
    else:
      sizes = {wire.MessageType.Connect: 1, wire.MessageType.Disconnect: 1,
               wire.MessageType.Ready: 1, wire.MessageType.Heartbeat: wire.HEARTBEAT_BYTES,
               wire.MessageType.VersionNegotiate: wire.VERSION_NEGOTIATE_BYTES,
               wire.MessageType.ReconnectRequest: wire.RECONNECT_REQUEST_BYTES}
      # 2026-09-10: decode v4's explicit envelope; legacy dispatch still rejects it.
      sizes[wire.MessageType.MatchReconnectRequest] = wire.MATCH_RECONNECT_REQUEST_BYTES
      sizes[wire.MessageType.MatchEndAck] = wire.MATCH_END_ACK_BYTES
      # 2026-09-10: fixed-size v5 confirmation; generic dispatch rejects it.
      sizes[wire.MessageType.MatchReady] = wire.MATCH_READY_BYTES
      sizes[wire.MessageType.MatchControlAck] = 17
      if kind not in sizes:
        raise ServerFailure('unsupported_message')
      need = sizes[kind]
    if len(self.data) < need:
      return None
    result, self.data = self.data[:need], self.data[need:]
    return result

  def clear(self):
    self.data = b''


class FrameInputWindow:
  """Accept current/future inputs once; duplicates are idempotent, changes reject."""
  def __init__(self, limits, num_slots):
    self.limits, self.num_slots = limits, num_slots
    self.frame_id = 0
    self.sealed = False
    self._frames = {}
    self.payload_bytes = 0

  # 2026-09-10: validate old-epoch packets without admitting them to the window.
  # def accept(self, packet, slots):
  def validate(self, packet, slots):
    if type(packet) is not bytes or len(packet) < 7 or packet[0] != wire.MessageType.FrameInput:
      raise ServerFailure('invalid_input')
    frame, count = struct.unpack_from('<IH', packet, 1)
    if (frame > MAX_FRAME or count != len(slots) or not 1 <= count <= self.num_slots
        or len(packet) != 7 + count * (2 + wire.SLOT_INPUT_BYTES)):
      raise ServerFailure('invalid_input')
    entries = []
    seen = set()
    for index in range(count):
      offset = 7 + index * (2 + wire.SLOT_INPUT_BYTES)
      slot = struct.unpack_from('<H', packet, offset)[0]
      value, _ = wire.unpack_slot_input(packet, offset + 2)
      if slot not in slots or slot in seen or not wire.is_valid_slot_input(value):
        raise ServerFailure('invalid_input')
      seen.add(slot)
      entries.append((slot, packet[offset + 2:offset + 2 + wire.SLOT_INPUT_BYTES]))
    return frame, entries

  def accept(self, packet, slots):
    frame, entries = self.validate(packet, slots)
    if frame < self.frame_id or (frame == self.frame_id and self.sealed):
      return 'late'
    if frame - self.frame_id >= self.limits.pending_frames:
      raise ServerFailure('future_input_capacity')
    row = self._frames.get(frame, {})
    extra = 0
    for slot, value in entries:
      if slot in row:
        if row[slot] != value:
          raise ServerFailure('conflicting_input')
      else:
        extra += sys.getsizeof(value)
    if extra > self.limits.input_bytes - self.payload_bytes:
      raise ServerFailure('input_capacity')
    if not extra:
      return 'duplicate'
    # Stage the small row before changing either the live record or accounting.
    candidate = dict(row)
    candidate.update(entries)
    self._frames[frame] = candidate
    self.payload_bytes += extra
    return 'accepted'

  def received(self):
    return frozenset(self._frames.get(self.frame_id, {}))

  def current(self):
    row = self._frames.get(self.frame_id, {})
    return [wire.unpack_slot_input(row[index])[0] if index in row else wire.default_slot_input()
            for index in range(self.num_slots)]

  def seal(self):
    if self.sealed:
      raise ServerFailure('frame_already_sealed')
    self.sealed = True
    return self.current()

  def advance(self):
    if not self.sealed:
      raise ServerFailure('frame_not_sealed')
    if self.frame_id == MAX_FRAME:
      raise ServerFailure('frame_limit')
    row = self._frames.pop(self.frame_id, {})
    self.payload_bytes -= sum(sys.getsizeof(value) for value in row.values())
    self.frame_id += 1
    self.sealed = False

  def disconnect(self, slots):
    # Keep already accepted current input; ownership handover invalidates future
    # cached input, so it cannot override the bot or a resumed owner later.
    for frame in tuple(self._frames):
      if frame <= self.frame_id:
        continue
      row = self._frames[frame]
      for slot in slots:
        value = row.pop(slot, None)
        if value is not None:
          self.payload_bytes -= sys.getsizeof(value)
      if not row:
        del self._frames[frame]

  def clear(self):
    self._frames.clear()
    self.payload_bytes = 0

  def stats(self):
    return dict(frame=self.frame_id, frames=len(self._frames),
                entries=sum(len(row) for row in self._frames.values()),
                payload_bytes=self.payload_bytes, sealed=self.sealed)


class ServerSendQueue:
  """Charge queued, deferred-resume and currently transmitting immutable bytes."""
  def __init__(self, limits):
    self.limits = limits
    self.pending = collections.deque()
    self.deferred = collections.deque()
    self.active = None
    self.active_since = None
    self.payload_bytes = 0
    self.closed = False

  @property
  def messages(self):
    return len(self.pending) + len(self.deferred) + int(self.active is not None)

  # 2026-09-10: queue age is part of the send deadline, including resume history.
  # def enqueue(self, data, *, deferred=False):
  def enqueue(self, data, *, deferred=False, now=None):
    if self.closed:
      raise ServerFailure('closed')
    if type(data) is not bytes or not data:
      raise ServerFailure('invalid_output')
    size = sys.getsizeof(data)
    if self.messages >= self.limits.send_messages or size > self.limits.send_bytes - self.payload_bytes:
      raise ServerFailure('send_capacity')
    now = time.monotonic() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
      raise ValueError('Invalid send timestamp')
    # (self.deferred if deferred else self.pending).append(data)
    (self.deferred if deferred else self.pending).append((data, now))
    self.payload_bytes += size

  def ready(self):
    self.pending.extend(self.deferred)
    self.deferred.clear()

  def take(self):
    if self.active is not None:
      raise RuntimeError('Only one server socket writer is allowed')
    if self.pending:
      # 2026-09-10: preserve original enqueue time when a packet starts sending.
      # self.active = self.pending.popleft()
      self.active, self.active_since = self.pending.popleft()
    return self.active

  def release_active(self):
    if self.active is not None:
      self.payload_bytes -= sys.getsizeof(self.active)
      self.active = None
      self.active_since = None

  def close(self):
    self.closed = True
    self.pending.clear()
    self.deferred.clear()
    # The writer's finally releases its live packet after write/cancellation.
    self.payload_bytes = sys.getsizeof(self.active) if self.active is not None else 0

  def stats(self):
    return dict(messages=self.messages, payload_bytes=self.payload_bytes,
                deferred=len(self.deferred), active=self.active is not None, closed=self.closed)
