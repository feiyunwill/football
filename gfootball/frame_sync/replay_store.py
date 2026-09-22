# 2026-09-10: bounded recordings and collection ownership, including returned handles.
from collections.abc import Sequence
from contextlib import contextmanager
import math
import os
import sys
import threading
import time
import weakref

from gfootball.frame_sync.replay_data import (
    # 2026-09-10: cursor EOF may be one past the maximum valid recorded frame.
    # MAX_TIME_MS, ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFormatError,
    MAX_FRAME, MAX_TIME_MS, ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFormatError,
    ReplayFrame, integer, limits_or_default, text,
)


class _Records:
  """Fixed outer index and lazily allocated 64-item chunks; no list growth guesses."""
  __slots__ = ('chunks', 'limit', 'length')

  def __init__(self, limit):
    self.chunks = [None] * ((limit + 63) // 64)
    self.limit, self.length = limit, 0

  def prepare(self):
    if self.length == self.limit:
      raise ReplayCapacityError('Replay record count capacity exceeded')
    block = self.length // 64
    if self.chunks[block] is not None:
      return None, 0
    chunk = [None] * min(64, self.limit - block * 64)
    return chunk, sys.getsizeof(chunk)

  def append(self, record, prepared):
    block, offset = divmod(self.length, 64)
    if prepared is not None:
      self.chunks[block] = prepared
    self.chunks[block][offset] = record
    self.length += 1

  def get(self, index):
    return self.chunks[index // 64][index % 64]


class _RecordView(Sequence):
  __slots__ = ('_replay', '_kind')

  def __init__(self, replay, kind):
    self._replay, self._kind = replay, kind

  def __len__(self):
    with self._replay._access():
      return getattr(self._replay, self._kind).length

  def __getitem__(self, index):
    with self._replay._access():
      records = getattr(self._replay, self._kind)
      if type(index) is slice:
        return tuple(records.get(i) for i in range(*index.indices(records.length)))
      if type(index) is not int:
        raise TypeError('Replay record index must be an integer or slice')
      if index < 0:
        index += records.length
      if not 0 <= index < records.length:
        raise IndexError('Replay record index is outside the recording')
      return records.get(index)

  def __iter__(self):
    # Capture only the count; immutable existing rows never need a full snapshot.
    for index in range(len(self)):
      yield self[index]


class Replay:
  """A bounded match recording. Seal before sharing it as a saved replay.

  Frames/events are immutable and exposed through read-only sequence views.
  Mutating a live handle returned by ReplayManager uses the same aggregate budget.
  Caller-retained deleted replays remain individually bounded and sealed; they
  are outside the manager's retained-byte accounting.
  """
  __slots__ = ('_identity', '_scores', '_duration', '_frames', '_events', '_limits',
               '_bytes', '_peak', '_sealed', '_gate', '_pid', '_manager_ref', '__weakref__')

  def __init__(self, replay_id, match_id, team_home, team_away, score_home=0,
               score_away=0, duration_ms=0, frames=None, events=None, created_at=None,
               *, tick_hz=10, limits=None):
    self._limits = limits_or_default(limits)
    for value, label, maximum in ((replay_id, 'replay ID', 128), (match_id, 'match ID', 128),
                                   (team_home, 'home team', 1024), (team_away, 'away team', 1024)):
      text(value, label, maximum)
    created_at = time.time() if created_at is None else created_at
    if type(created_at) not in (int, float) or not 0 <= created_at <= 2**53 or not math.isfinite(created_at):
      raise ReplayFormatError('Invalid replay creation time')
    integer(tick_hz, 'replay tick frequency', 240, 1)
    integer(score_home, 'home score', 999)
    integer(score_away, 'away score', 999)
    integer(duration_ms, 'replay duration', MAX_TIME_MS)
    for values, maximum in ((frames, self._limits.frames), (events, self._limits.events)):
      if values is not None and (type(values) not in (tuple, list) or len(values) > maximum):
        raise ReplayCapacityError('Initial replay records must be a bounded sequence')
    self._pid, self._gate = os.getpid(), threading.RLock()
    self._manager_ref = None
    self._identity = (replay_id, match_id, team_home, team_away, float(created_at), tick_hz)
    self._scores, self._duration = (score_home, score_away), duration_ms
    self._frames, self._events = _Records(self._limits.frames), _Records(self._limits.events)
    # Scalar metadata has a fixed allowance even when scores/duration are updated.
    self._bytes = (sys.getsizeof(self) + sys.getsizeof(self._identity)
                   + sum(sys.getsizeof(item) for item in self._identity) + 512
                   + sum(sys.getsizeof(rows) + sys.getsizeof(rows.chunks) for rows in (self._frames, self._events)))
    if self._bytes > self._limits.replay_bytes:
      raise ReplayCapacityError('Replay metadata and index capacity exceeded')
    self._peak, self._sealed = self._bytes, False
    for value in frames or ():
      self.add_frame(value)
    for value in events or ():
      self.add_event(value)

  @contextmanager
  def _access(self):
    if os.getpid() != self._pid:
      raise RuntimeError('Replay objects cannot be reused after fork')
    with self._gate:
      yield

  def _writable(self):
    if self._sealed:
      raise RuntimeError('Replay is sealed')

  @property
  def replay_id(self): return self._identity[0]
  @property
  def match_id(self): return self._identity[1]
  @property
  def team_home(self): return self._identity[2]
  @property
  def team_away(self): return self._identity[3]
  @property
  def created_at(self): return self._identity[4]
  @property
  def tick_hz(self): return self._identity[5]
  @property
  def limits(self): return self._limits
  @property
  def frames(self): return _RecordView(self, '_frames')
  @property
  def events(self): return _RecordView(self, '_events')
  @property
  def score_home(self):
    with self._access(): return self._scores[0]
  @score_home.setter
  def score_home(self, value):
    with self._access(): self.set_score(value, self._scores[1])
  @property
  def score_away(self):
    with self._access(): return self._scores[1]
  @score_away.setter
  def score_away(self, value):
    with self._access(): self.set_score(self._scores[0], value)
  @property
  def duration_ms(self):
    with self._access(): return self._duration
  @duration_ms.setter
  def duration_ms(self, value):
    with self._access():
      self._writable()
      integer(value, 'replay duration', MAX_TIME_MS)
      if value < self._minimum_duration():
        raise ReplayFormatError('Duration cannot precede recorded data')
      self._duration = value
  @property
  def is_sealed(self):
    with self._access(): return self._sealed
  @property
  def retained_bytes(self):
    with self._access(): return self._bytes

  def _minimum_duration(self):
    duration = self._events.get(self._events.length - 1).timestamp_ms if self._events.length else 0
    if self._frames.length:
      span = self._frames.length * 1000
      duration = max(duration, (span + self.tick_hz - 1) // self.tick_hz)
    return duration

  def set_score(self, home, away):
    with self._access():
      self._writable()
      integer(home, 'home score', 999)
      integer(away, 'away score', 999)
      self._scores = home, away

  def _append(self, rows, record, maximum):
    if record.retained_bytes > maximum:
      raise ReplayCapacityError('Individual replay record capacity exceeded')
    chunk, extra = rows.prepare()
    extra += record.retained_bytes
    if self._bytes + extra > self._limits.replay_bytes:
      raise ReplayCapacityError('Individual replay byte capacity exceeded')
    manager = self._manager_ref() if self._manager_ref is not None else None
    if manager is not None:
      manager._make_room(extra)
    rows.append(record, chunk)
    self._bytes += extra
    self._peak = max(self._peak, self._bytes)
    if manager is not None:
      manager._used += extra
      manager._peak = max(manager._peak, manager._used)
    self._duration = max(self._duration, self._minimum_duration())

  def add_frame(self, frame):
    with self._access():
      self._writable()
      if type(frame) is not ReplayFrame:
        raise ReplayFormatError('Expected immutable ReplayFrame')
      if self._frames.length and frame.frame_id != self._frames.get(self._frames.length - 1).frame_id + 1:
        raise ReplayFormatError('Replay frames must be consecutive and ordered')
      # Validate the next duration before admitting any data or evicting history.
      integer(((self._frames.length + 1) * 1000 + self.tick_hz - 1) // self.tick_hz,
              'replay duration', MAX_TIME_MS)
      self._append(self._frames, frame, self._limits.frame_bytes)

  def add_event(self, event):
    with self._access():
      self._writable()
      if type(event) is not ReplayEvent:
        raise ReplayFormatError('Expected immutable ReplayEvent')
      if self._events.length:
        previous = self._events.get(self._events.length - 1)
        if event.frame_id < previous.frame_id or event.timestamp_ms < previous.timestamp_ms:
          raise ReplayFormatError('Replay events must be ordered by frame and time')
      self._append(self._events, event, self._limits.event_bytes)

  def seal(self):
    with self._access():
      self._sealed = True
    return self

  def get_highlights(self):
    return [event for event in self.events if event.event_type in (ReplayEventType.GOAL, ReplayEventType.SAVE)]

  def get_duration_seconds(self):
    return self.duration_ms / 1000.0

  def to_dict(self):
    """Retain the legacy listing summary; record serialization is complete below."""
    with self._access():
      return dict(replay_id=self.replay_id, match_id=self.match_id, team_home=self.team_home,
                  team_away=self.team_away, score='%d-%d' % self._scores,
                  duration_seconds=self._duration / 1000.0, frames=self._frames.length, events=self._events.length)

  def metadata(self):
    with self._access():
      return dict(replay_id=self.replay_id, match_id=self.match_id, team_home=self.team_home,
                  team_away=self.team_away, score_home=self._scores[0], score_away=self._scores[1],
                  duration_ms=self._duration, created_at=self.created_at, tick_hz=self.tick_hz)

  def stats(self):
    with self._access():
      return dict(frames=self._frames.length, events=self._events.length, retained_bytes=self._bytes,
                  peak_bytes=self._peak, sealed=self._sealed)

  def get_frame(self, frame_id):
    integer(frame_id, 'requested frame')
    with self._access():
      if not self._frames.length:
        return None
      index = frame_id - self._frames.get(0).frame_id
      return self._frames.get(index) if 0 <= index < self._frames.length else None

  def cursor(self):
    return ReplayCursor(self)

  def save(self, path, *, directory_limits=None):
    from gfootball.frame_sync.replay_file import save_replay
    return save_replay(self, path, directory_limits=directory_limits)

  @classmethod
  # 2026-09-10: a manager can cancel its one in-flight staged import on close.
  # def load(cls, path, *, limits=None):
  def load(cls, path, *, limits=None, cancelled=None):
    from gfootball.frame_sync.replay_file import load_replay
    # return load_replay(path, limits=limits)
    return load_replay(path, limits=limits, cancelled=cancelled)


class ReplayCursor:
  """Independent, seekable iteration over the exact saved frame sequence."""
  # 2026-09-10: callers cannot change the source without resetting cursor invariants.
  # __slots__ = ('replay', '_index')
  __slots__ = ('_replay', '_index')

  def __init__(self, replay):
    if type(replay) is not Replay or not replay.is_sealed:
      raise ReplayFormatError('Playback requires a sealed Replay')
    # self.replay, self._index = replay, 0
    self._replay, self._index = replay, 0

  @property
  def replay(self): return self._replay

  def __iter__(self): return self

  def __next__(self):
    # 2026-09-10: one lock covers selection and progress for shared cursor callers.
    # if self._index == len(self.replay.frames):
    #   raise StopIteration
    # frame = self.replay.frames[self._index]
    # self._index += 1
    # return frame
    with self.replay._access():
      if self._index == self.replay._frames.length:
        raise StopIteration
      frame = self.replay._frames.get(self._index)
      self._index += 1
      return frame

  def seek(self, frame_id):
    # 2026-09-10: preserve progress on invalid seeks and serialize valid seeks.
    # integer(frame_id, 'playback frame')
    # frames = self.replay.frames
    # origin = frames[0].frame_id if frames else 0
    # if not origin <= frame_id <= origin + len(frames):
    #   raise ReplayFormatError('Playback position is outside the recording')
    # self._index = frame_id - origin
    integer(frame_id, 'playback frame', MAX_FRAME + 1)
    with self.replay._access():
      frames = self.replay._frames
      origin = frames.get(0).frame_id if frames.length else 0
      if not origin <= frame_id <= origin + frames.length:
        raise ReplayFormatError('Playback position is outside the recording')
      self._index = frame_id - origin

  def rewind(self):
    # 2026-09-10: use the same process/lock contract as next and seek.
    # self._index = 0
    with self.replay._access():
      self._index = 0


class ReplayManager:
  """One aggregate budget for active and stored matches; oldest saved rows evict.

  Admission is atomic: invalid/duplicate/oversized work cannot stop the current
  recording or evict saved data. Eviction affects this in-memory collection only.
  Files written through save_replay are never removed by collection eviction.
  """
  def __init__(self, *, limits=None):
    self._limits = limits_or_default(limits)
    self._gate, self._pid = threading.RLock(), os.getpid()
    self._replays, self._current_recording = {}, None
    self._used = self._peak = self._evicted = 0
    self._closed = False
    self._loading = False
    self._load_cancelled = threading.Event()

  @contextmanager
  def _access(self, write=False):
    if os.getpid() != self._pid:
      raise RuntimeError('Replay managers cannot be reused after fork')
    with self._gate:
      if write and self._closed:
        raise RuntimeError('Replay manager is closed')
      yield

  def _detach(self, replay):
    replay.seal()
    replay._manager_ref = None
    self._used -= replay._bytes

  def _make_room(self, extra, new_entry=False):
    # Caller holds the shared lock. Select all victims before mutating anything.
    used = self._used + extra
    count = len(self._replays) + (self._current_recording is not None) + int(new_entry)
    victims = []
    if used > self._limits.total_bytes or count > self._limits.replays:
      for replay in sorted(self._replays.values(), key=lambda item: item.created_at):
        victims.append(replay)
        used -= replay._bytes
        count -= 1
        if used <= self._limits.total_bytes and count <= self._limits.replays:
          break
    if used > self._limits.total_bytes or count > self._limits.replays:
      raise ReplayCapacityError('Replay collection capacity exceeded')
    for replay in victims:
      del self._replays[replay.replay_id]
      self._detach(replay)
      self._evicted = min(2**64 - 1, self._evicted + 1)

  def _attach(self, replay):
    replay._gate = self._gate
    replay._manager_ref = weakref.ref(self)
    self._used += replay._bytes
    self._peak = max(self._peak, self._used)

  def start_recording(self, replay_id, match_id, team_home, team_away, *, tick_hz=10):
    with self._access(write=True):
      text(replay_id, 'replay ID')
      if replay_id in self._replays or (self._current_recording is not None
                                      and self._current_recording.replay_id == replay_id):
        raise ReplayFormatError('Replay ID already exists')
      replay = Replay(replay_id, match_id, team_home, team_away, tick_hz=tick_hz, limits=self._limits)
      self._make_room(replay._bytes, new_entry=True)
      if self._current_recording is not None:
        self.stop_recording()
      self._attach(replay)
      self._current_recording = replay
      return replay

  def stop_recording(self):
    with self._access():
      replay = self._current_recording
      if replay is not None:
        replay.seal()
        self._replays[replay.replay_id] = replay
        self._current_recording = None
      return replay

  def abort_recording(self):
    with self._access():
      replay = self._current_recording
      if replay is not None:
        self._current_recording = None
        self._detach(replay)
      return replay

  def record_frame(self, frame):
    with self._access(write=True):
      if self._current_recording is None:
        return False
      self._current_recording.add_frame(frame)
      return True

  def record_event(self, event):
    with self._access(write=True):
      if self._current_recording is None:
        return False
      self._current_recording.add_event(event)
      return True

  def set_score(self, home, away):
    with self._access(write=True):
      if self._current_recording is None:
        return False
      self._current_recording.set_score(home, away)
      return True

  def get_replay(self, replay_id):
    text(replay_id, 'replay ID')
    with self._access():
      return self._replays.get(replay_id)

  def delete_replay(self, replay_id):
    text(replay_id, 'replay ID')
    with self._access(write=True):
      replay = self._replays.pop(replay_id, None)
      if replay is not None:
        self._detach(replay)
      return replay is not None

  def list_replays(self):
    with self._access():
      return list(self._replays.values())

  def get_latest_replays(self, count=10):
    # 2026-09-10: default listing remains valid with a smaller collection policy.
    # integer(count, 'replay list count', self._limits.replays)
    integer(count, 'replay list count', 1000)
    with self._access():
      return sorted(self._replays.values(), key=lambda item: item.created_at, reverse=True)[:count]

  def is_recording(self):
    with self._access():
      return self._current_recording is not None

  def get_storage_info(self):
    with self._access():
      return dict(replay_count=len(self._replays), total_frames=sum(item._frames.length for item in self._replays.values()),
                  is_recording=self._current_recording is not None, retained_bytes=self._used,
                  active_bytes=self._current_recording._bytes if self._current_recording is not None else 0,
                  # 2026-09-10: disclose the separately bounded staged import.
                  # peak_bytes=self._peak, evicted_replays=self._evicted, closed=self._closed)
                  peak_bytes=self._peak, evicted_replays=self._evicted, closed=self._closed,
                  loading=self._loading, staging_limit_bytes=self._limits.replay_bytes if self._loading else 0)

  def save_replay(self, replay_id, path, *, directory_limits=None):
    replay = self.get_replay(replay_id)
    if replay is None:
      raise ReplayFormatError('Replay ID does not exist')
    return replay.save(path, directory_limits=directory_limits)

  def load_replay(self, path):
    with self._access(write=True):
      # 2026-09-10: capture the immutable policy under the lifecycle check.
      # pass
      load_limits = self._limits
      if self._loading:
        raise ReplayCapacityError('One replay import is already in progress')
      self._loading = True
    # replay = Replay.load(path, limits=self._limits)
    # 2026-09-10: one staging budget, cancellation between reads, release on failure.
    # replay = Replay.load(path, limits=load_limits)
    # with self._access(write=True):
    #   if replay.replay_id in self._replays or (self._current_recording is not None
    #                                          and self._current_recording.replay_id == replay.replay_id):
    #     raise ReplayFormatError('Replay ID already exists')
    #   self._make_room(replay._bytes, new_entry=True)
    #   self._attach(replay)
    #   self._replays[replay.replay_id] = replay
    #   return replay
    try:
      replay = Replay.load(path, limits=load_limits, cancelled=self._load_cancelled.is_set)
      with self._access(write=True):
        if replay.replay_id in self._replays or (self._current_recording is not None
                                               and self._current_recording.replay_id == replay.replay_id):
          raise ReplayFormatError('Replay ID already exists')
        self._make_room(replay._bytes, new_entry=True)
        self._attach(replay)
        self._replays[replay.replay_id] = replay
        return replay
    finally:
      with self._access():
        self._loading = False

  def close(self):
    with self._access():
      self._load_cancelled.set()
      self.abort_recording()
      for replay in self._replays.values():
        self._detach(replay)
      self._replays.clear()
      self._closed = True

  def __enter__(self):
    with self._access(write=True):
      return self

  def __exit__(self, kind, value, traceback):
    self.close()

  def __del__(self):
    if hasattr(self, '_closed') and self._pid == os.getpid():
      try:
        self.close()
      except BaseException:
        pass
