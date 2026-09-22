# Copyright 2026 Google LLC
# 2026-09-10: opt-in v3 token issuance; bounded legacy snapshot bootstrap.
from dataclasses import dataclass
import struct
import sys

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientBuffers, ClientFailure

RESUME_VERSION = 3
SESSION_TOKEN = 14


def validate_token(token):
  if type(token) is not int or not 1 <= token <= 0xffffffffffffffff:
    raise ValueError('Expected a nonzero uint64 session token')
  return token


def pack_session_token(token):
  return struct.pack('<BQ', SESSION_TOKEN, validate_token(token))


@dataclass(frozen=True)
class ResumeLimits:
  snapshot_bytes: int = 1024 * 1024

  def __post_init__(self):
    if type(self.snapshot_bytes) is not int or not 1 <= self.snapshot_bytes <= 1024 * 1024:
      raise ValueError('Invalid resume snapshot limit')


class ResumeBuffers(ClientBuffers):
  """One bounded snapshot, consumed incrementally through the ordinary 8 KiB IO.

  snapshot_bytes limits serialized payload. Fixed bytearray/bytes headers are
  reported separately by retained_snapshot_bytes. Final immutable conversion
  transiently holds both bounded copies; no unbounded concatenation is used.
  Native servers may send consecutive authority before Ready; queue it against
  the ordinary authority/hash budgets while the logic owner restores the state.
  """
  # 2026-09-10: reject snapshots older than locally confirmed authority.
  # def __init__(self, limits, resume_limits, *, restoring=False, expected_session=None, expected_slots=None):
  def __init__(self, limits, resume_limits, *, restoring=False, expected_session=None, expected_slots=None, minimum_frame=0):
    super().__init__(limits)
    self.resume_limits = resume_limits
    self.restoring = restoring
    self.expected_session = expected_session
    self.expected_slots = expected_slots
    self.session_token = None
    self.snapshot = None
    self._snapshot_buffer = None
    self._snapshot_offset = 0
    self._snapshot_frame = None
    self._snapshot_received = False
    self.minimum_frame = minimum_frame
    self.handed_back = set()

  @property
  def retained_snapshot_bytes(self):
    if self._snapshot_buffer is not None:
      return sys.getsizeof(self._snapshot_buffer)
    return sys.getsizeof(self.snapshot[1]) if self.snapshot is not None else 0

  def fail(self, reason):
    super().fail(reason)
    self._snapshot_buffer = self.snapshot = None
    self._snapshot_offset = 0
    self.session_token = None
    self.handed_back.clear()

  def _parse(self, now):
    if not self.receive:
      return False
    if self.phase == 'token':
      if self.receive[0] != SESSION_TOKEN:
        raise ClientFailure('missing_session_token')
      if len(self.receive) < 9:
        return False
      token = struct.unpack_from('<Q', self.receive, 1)[0]
      if not token:
        raise ClientFailure('invalid_session_token')
      self.session_token = token
      self.receive = self.receive[9:]
      self.phase, self.ready_since = 'ready', now
      return True
    if self.phase == 'snapshot_header':
      if self.receive[0] != wire.MessageType.StateSnapshot:
        raise ClientFailure('missing_resume_snapshot')
      if len(self.receive) < 9:
        return False
      frame, size = struct.unpack_from('<II', self.receive, 1)
      # 2026-09-10: a valid identity must not rewind already confirmed gameplay.
      # if frame > 0xfffffff7 or not 1 <= size <= self.resume_limits.snapshot_bytes:
      if not self.minimum_frame <= frame <= 0xfffffff7 or not 1 <= size <= self.resume_limits.snapshot_bytes:
        raise ClientFailure('invalid_resume_snapshot')
      self._snapshot_buffer = bytearray(size)
      self._snapshot_frame = frame
      self.receive = self.receive[9:]
      self.phase = 'snapshot_body'
      return True
    if self.phase == 'snapshot_body':
      used = min(len(self.receive), len(self._snapshot_buffer) - self._snapshot_offset)
      end = self._snapshot_offset + used
      self._snapshot_buffer[self._snapshot_offset:end] = self.receive[:used]
      self._snapshot_offset = end
      self.receive = self.receive[used:]
      if end == len(self._snapshot_buffer):
        self.snapshot = self._snapshot_frame, bytes(self._snapshot_buffer)
        self._snapshot_buffer = None
        self._snapshot_offset = 0
        self._snapshot_received = True
        self.next_authority = self._snapshot_frame
        self.phase, self.ready_since = 'ready', now
      return True
    kind = self.receive[0]
    if self.restoring and kind == wire.MessageType.HandbackNotify and len(self.receive) >= 7:
      slot = struct.unpack_from('<H', self.receive, 1)[0]
      if slot in (self.slots or ()) and self.phase != 'streaming':
        raise ClientFailure('unexpected_handback')
    if self._snapshot_received and self.phase == 'ready' and kind in (
        wire.MessageType.AuthoritativeFrame, wire.MessageType.StateHash):
      self.phase = 'streaming'
      try:
        return super()._parse(now)
      finally:
        self.phase = 'ready'
    # 2026-09-10: retain explicit owned-slot handback acknowledgement.
    # parsed = super()._parse(now)
    handback = wire.unpack_handback_notify(self.receive[:7])[0] if kind == wire.MessageType.HandbackNotify and len(self.receive) >= 7 else None
    parsed = super()._parse(now)
    if parsed and handback is not None:
      self.handed_back.add(handback)
    if parsed and kind == wire.MessageType.SessionStart:
      if self.expected_session is not None and self.session != self.expected_session:
        raise ClientFailure('resume_session_mismatch')
    if parsed and kind == wire.MessageType.SlotAssignment:
      if self.expected_slots is not None and self.slots != self.expected_slots:
        raise ClientFailure('resume_slots_mismatch')
      self.phase = 'snapshot_header' if self.restoring else 'token'
      self.ready_since = None
    return parsed
