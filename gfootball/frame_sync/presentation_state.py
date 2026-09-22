# Copyright 2026 Google LLC
# 2026-09-09: bounded immutable display snapshots and atomic publication.
"""Presentation history owns immutable serialized states, not live environments.

Byte limits charge sys.getsizeof(bytes/str) per retained record, conservatively
counting shared payloads again across different frames. Container metadata is
count bounded. Returned samples belong to readers and are outside this budget.
"""
import collections
from dataclasses import dataclass
import math
import sys
import threading
import time


class PresentationCapacityError(ValueError):
  """A single published state cannot fit; the previous publication is unchanged."""


@dataclass(frozen=True)
class PresentationState:
  state: object
  frame_id: int
  confirmed_frame_id: int
  timestamp: float
  waiting_for_authority: bool
  revision: int
  state_revision: int
  discontinuity: bool

  def __post_init__(self):
    # A frozen record alone does not make a caller-supplied bytearray immutable.
    # Validate the public sample type, including samples from custom holders.
    if type(self.state) not in (bytes, str):
      raise ValueError('Presentation state must be immutable bytes or str')
    if sys.getsizeof(self.state) > 1024 * 1024:
      raise PresentationCapacityError('Presentation snapshot exceeds the hard byte limit')
    if (type(self.frame_id) is not int or not -1 <= self.frame_id <= 0xfffffff7 or
        type(self.confirmed_frame_id) is not int or not -1 <= self.confirmed_frame_id <= self.frame_id):
      raise ValueError('Invalid presentation frame IDs')
    if (type(self.timestamp) not in (int, float) or not math.isfinite(self.timestamp) or self.timestamp < 0 or
        type(self.waiting_for_authority) is not bool or type(self.discontinuity) is not bool):
      raise ValueError('Invalid presentation time or flags')
    if (type(self.revision) is not int or not 1 <= self.revision <= 0xffffffffffffffff or
        type(self.state_revision) is not int or not 1 <= self.state_revision <= self.revision):
      raise ValueError('Invalid presentation revision')


class LogicStateHolder:
  """Thread-safe publication of a bounded, immutable latest-state history.

  One logic owner supplies ordered writes; any number of readers can take an
  atomic sample. Rewinds, same-frame corrections and explicit discontinuities
  discard obsolete history. clear() starts a new logical session while revision
  IDs keep advancing; close() releases storage and rejects further writes.
  """
  def __init__(self, buffer_size=4, *, snapshot_bytes=1024 * 1024,
               history_bytes=4 * 1024 * 1024, clock=None):
    for name, value, minimum, maximum in (
        ('buffer_size', buffer_size, 1, 64),
        ('snapshot_bytes', snapshot_bytes, 64, 1024 * 1024),
        ('history_bytes', history_bytes, 64, 8 * 1024 * 1024)):
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid presentation limit: ' + name)
    if clock is not None and not callable(clock):
      raise ValueError('Clock must be callable')
    self._lock = threading.Lock()
    self._buffer_size = buffer_size
    self._snapshot_bytes = snapshot_bytes
    self._history_limit = history_bytes
    self._clock = clock or time.monotonic
    self._buffer = collections.deque()
    self._retained_bytes = 0
    self._revision = 0
    self._last_write_time = None
    self._closed = False
    self._logic_fps = 10.0

  @staticmethod
  def _frame(value):
    return type(value) is int and -1 <= value <= 0xfffffff7

  def _now(self):
    now = self._clock()
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
      raise ValueError('Invalid monotonic presentation time')
    return float(now)

  def write(self, state_str, frame_id, confirmed_frame_id=None,
            waiting_for_authority=False, *, discontinuity=False):
    if type(state_str) not in (bytes, str):
      raise ValueError('Presentation state must be immutable bytes or str')
    if not self._frame(frame_id) or (confirmed_frame_id is not None and not self._frame(confirmed_frame_id)):
      raise ValueError('Invalid presentation frame ID')
    if type(waiting_for_authority) is not bool or type(discontinuity) is not bool:
      raise ValueError('Presentation flags must be bool')
    size = sys.getsizeof(state_str)
    if size > self._snapshot_bytes or size > self._history_limit:
      raise PresentationCapacityError('Presentation snapshot exceeds its byte budget')
    now = self._now()
    with self._lock:
      if self._closed:
        raise RuntimeError('Presentation holder is closed')
      previous = self._buffer[-1] if self._buffer else None
      confirmed = (previous.confirmed_frame_id if previous else -1) if confirmed_frame_id is None else confirmed_frame_id
      if confirmed > frame_id or (previous and confirmed < previous.confirmed_frame_id):
        raise ValueError('Confirmed presentation frame cannot exceed current or regress')
      # 2026-09-09: metadata-only updates preserve the payload timestamp but
      # must still participate in monotonic publication ordering.
      # if previous and now < previous.timestamp:
      if self._last_write_time is not None and now < self._last_write_time:
        raise ValueError('Presentation clock moved backwards')
      if self._revision == 0xffffffffffffffff:
        raise OverflowError('Presentation revision exhausted; use a new holder')
      revision = self._revision + 1
      same_state = previous is not None and type(state_str) is type(previous.state) and state_str == previous.state
      if same_state:
        state_str = previous.state  # share the already immutable payload
        # Charge the object actually retained after choosing the shared payload.
        size = sys.getsizeof(state_str)
      cut = bool(discontinuity or (previous and (
          frame_id < previous.frame_id or (frame_id == previous.frame_id and not same_state))))
      same_frame = previous is not None and frame_id == previous.frame_id
      timestamp = previous.timestamp if same_frame and same_state and not cut else now
      state_revision = previous.state_revision if same_state else revision
      sample = PresentationState(state_str, frame_id, confirmed, timestamp,
                                 waiting_for_authority, revision, state_revision, cut)
      # Stage a bounded set of references before committing any observable state.
      # A rejected write or allocation failure leaves the previous sample intact.
      candidate = collections.deque() if cut else collections.deque(self._buffer)
      retained = 0 if cut else self._retained_bytes
      if same_frame and candidate:
        retained -= sys.getsizeof(candidate.pop().state)
      while candidate and (len(candidate) >= self._buffer_size or retained + size > self._history_limit):
        retained -= sys.getsizeof(candidate.popleft().state)
      candidate.append(sample)
      self._buffer = candidate
      self._retained_bytes = retained + size
      self._revision = revision
      self._last_write_time = now
    return revision

  def read_sample(self):
    """One atomic immutable sample; no copies of the serialized payload."""
    with self._lock:
      return self._buffer[-1] if self._buffer else None

  def read_pair(self):
    """Atomically borrow the last two immutable endpoints, without payload copies."""
    with self._lock:
      current = self._buffer[-1] if self._buffer else None
      previous = self._buffer[-2] if len(self._buffer) > 1 else None
      return previous, current

  def read(self):
    """Compatibility tuple: (state, frame, confirmed, monotonic time, waiting)."""
    sample = self.read_sample()
    if sample is None:
      return None, -1, -1, None, False
    return (sample.state, sample.frame_id, sample.confirmed_frame_id,
            sample.timestamp, sample.waiting_for_authority)

  def read_interpolated(self):
    """Latest opaque state and a diagnostic phase; does not interpolate state.

    Phase advances from the latest publication over one logic period. A stall,
    discontinuity or insufficient history returns zero. Native position/pose
    interpolation requires a separate engine display API and is not claimed here.
    """
    with self._lock:
      sample = self._buffer[-1] if self._buffer else None
      depth, fps = len(self._buffer), self._logic_fps
    if sample is None:
      return None, 0.0
    if depth < 2 or sample.waiting_for_authority or sample.discontinuity:
      return sample.state, 0.0
    elapsed = max(0.0, self._now() - sample.timestamp)
    return sample.state, min(elapsed * fps, 0.999)

  def set_logic_fps(self, fps):
    if type(fps) not in (int, float) or not math.isfinite(fps) or not 1 <= fps <= 240:
      raise ValueError('Invalid logic frame rate')
    with self._lock:
      self._logic_fps = float(fps)

  @property
  def buffer_depth(self):
    with self._lock:
      return len(self._buffer)

  def stats(self):
    with self._lock:
      return dict(frames=len(self._buffer), retained_bytes=self._retained_bytes,
                  frame_limit=self._buffer_size, snapshot_limit=self._snapshot_bytes,
                  history_limit=self._history_limit, revision=self._revision, closed=self._closed)

  def clear(self):
    """Release this session's snapshots without reusing revision IDs."""
    with self._lock:
      self._buffer.clear()
      self._retained_bytes = 0
      self._last_write_time = None

  def close(self):
    with self._lock:
      self._closed = True
      self._buffer.clear()
      self._retained_bytes = 0
      self._last_write_time = None
