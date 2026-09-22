# 2026-09-10: versioned JSONL match replay files with bounded reads and atomic writes.
import hashlib
import json
import os
from pathlib import Path
import stat

from gfootball.frame_sync.replay_data import (
    ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFormatError, ReplayFrame, integer, limits_or_default,
)
from gfootball.frame_sync.replay_store import Replay

_META_FIELDS = {'replay_id', 'match_id', 'team_home', 'team_away', 'score_home',
                'score_away', 'duration_ms', 'created_at', 'tick_hz'}


def _unique_object(pairs):
  if len(pairs) > 128:
    raise ReplayCapacityError('Replay JSON object field capacity exceeded')
  result = {}
  for key, value in pairs:
    if key in result:
      raise ReplayFormatError('Duplicate replay JSON field')
    result[key] = value
  return result


def _constant(value):
  raise ReplayFormatError('Non-finite replay JSON value')


def _json_int(value):
  if len(value.lstrip('-')) > 19:
    raise ReplayFormatError('Replay integer is outside int64')
  result = int(value)
  if not -(2**63) <= result < 2**63:
    raise ReplayFormatError('Replay integer is outside int64')
  return result


def _decode(line):
  try:
    # 2026-09-10: reject long integers before expensive conversion on older Python.
    # data = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_constant)
    data = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object,
                      parse_constant=_constant, parse_int=_json_int)
  except (UnicodeError, ValueError, RecursionError) as error:
    if isinstance(error, ReplayFormatError):
      raise
    raise ReplayFormatError('Invalid replay JSON record') from error
  if type(data) is not dict:
    raise ReplayFormatError('Replay JSON record must be an object')
  return data


def _encoded(value, maximum):
  try:
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':'), sort_keys=True) + '\n').encode('utf-8')
  except (TypeError, ValueError, UnicodeError) as error:
    raise ReplayFormatError('Replay record cannot be encoded') from error
  if len(data) > maximum:
    raise ReplayCapacityError('Replay file line capacity exceeded')
  return data


class ReplayFileReader:
  """Stream one immutable record; verify the footer only when fully consumed.

  Early close releases the file but does not verify unseen records. Metadata is
  returned as a fresh small dict. No pickle or native-engine loading is involved.
  """
  # 2026-09-10: cancellation remains owned by the caller of a synchronous import.
  # def __init__(self, path, *, limits=None):
  def __init__(self, path, *, limits=None, cancelled=None):
    # 2026-09-10: limits cannot change between header admission and body reads.
    # self.limits = limits_or_default(limits)
    self._limits = limits_or_default(limits)
    if cancelled is not None and not callable(cancelled):
      raise ValueError('Expected a replay cancellation predicate')
    self._cancelled = cancelled
    self._pid = os.getpid()
    self._stream, self._identity = None, None
    self._closed = self._finished = False
    self._frames = self._events = self._bytes = self._peak = 0
    self._last_frame = self._last_event = None
    self._digest = hashlib.sha256()
    try:
      self._check_cancelled()
      self._stream = Path(path).open('rb', buffering=64 * 1024)
      self._identity = self._fingerprint()
      raw, header = self._read()
      if set(header) != {'format', 'version', 'metadata', 'frames', 'events'}:
        raise ReplayFormatError('Invalid replay file header')
      # 2026-09-10: v2 explicitly announces native-origin snapshot events.
      # if header['format'] != 'football.frame_replay' or type(header['version']) is not int or header['version'] != 1:
      if header['format'] != 'football.frame_replay' or type(header['version']) is not int or header['version'] not in (1, 2):
        raise ReplayFormatError('Unsupported replay file format')
      self._version = header['version']
      integer(header['frames'], 'replay file frame count', self.limits.frames)
      integer(header['events'], 'replay file event count', self.limits.events)
      if type(header['metadata']) is not dict or set(header['metadata']) != _META_FIELDS:
        raise ReplayFormatError('Invalid replay metadata fields')
      metadata = Replay(**header['metadata'], limits=self.limits).metadata()
      self._metadata = tuple(metadata.items())
      self._counts = header['frames'], header['events']
      self._digest.update(raw)
    except BaseException:
      self.close()
      raise

  def _process(self):
    if os.getpid() != self._pid:
      raise RuntimeError('Replay readers cannot be reused after fork')

  def _check_cancelled(self):
    if self._cancelled is not None and self._cancelled():
      raise RuntimeError('Replay load cancelled')

  def _fingerprint(self):
    info = os.fstat(self._stream.fileno())
    if not stat.S_ISREG(info.st_mode):
      raise ReplayFormatError('Replay file must be a regular file')
    if info.st_size > self.limits.file_bytes:
      raise ReplayCapacityError('Replay input file capacity exceeded')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

  def _unchanged(self):
    if self._fingerprint() != self._identity:
      raise ReplayFormatError('Replay file changed while reading')

  def _read(self):
    self._check_cancelled()
    self._unchanged()
    raw = self._stream.readline(self.limits.line_bytes + 1)
    if len(raw) > self.limits.line_bytes:
      raise ReplayCapacityError('Replay input line capacity exceeded')
    if not raw or not raw.endswith(b'\n'):
      raise ReplayFormatError('Replay file is truncated')
    self._bytes += len(raw)
    self._unchanged()
    return raw, _decode(raw)

  @property
  def limits(self):
    return self._limits

  @property
  def metadata(self):
    self._process()
    return dict(self._metadata)

  def __iter__(self): return self

  def __next__(self):
    self._process()
    if self._finished:
      raise StopIteration
    if self._closed:
      raise RuntimeError('Replay reader is closed')
    try:
      raw, row = self._read()
      if self._frames < self._counts[0]:
        expected = 'frame'
      elif self._events < self._counts[1]:
        expected = 'event'
      else:
        expected = 'end'
      if row.get('kind') != expected:
        raise ReplayFormatError('Replay record order/count does not match its header')
      if expected == 'end':
        if set(row) != {'kind', 'frames', 'events', 'sha256'}:
          raise ReplayFormatError('Invalid replay footer')
        if (type(row['frames']) is not int or type(row['events']) is not int
            or (row['frames'], row['events']) != self._counts
            or row['sha256'] != self._digest.hexdigest()):
          raise ReplayFormatError('Replay integrity check failed')
        if self._stream.read(1):
          raise ReplayFormatError('Replay file has trailing data')
        self._unchanged()
        minimum = (self._frames * 1000 + self.metadata['tick_hz'] - 1) // self.metadata['tick_hz']
        if self._last_event is not None:
          minimum = max(minimum, self._last_event[1])
        if self.metadata['duration_ms'] < minimum:
          raise ReplayFormatError('Replay duration is shorter than its recorded data')
        self._finished = True
        self.close()
        raise StopIteration
      if set(row) != {'kind', 'data'}:
        raise ReplayFormatError('Invalid replay record fields')
      if expected == 'frame':
        record = ReplayFrame.from_dict(row['data'])
        if record.retained_bytes > self.limits.frame_bytes:
          raise ReplayCapacityError('Replay frame byte capacity exceeded')
        if self._last_frame is not None and record.frame_id != self._last_frame + 1:
          raise ReplayFormatError('Replay file frames are not consecutive')
        self._last_frame = record.frame_id
        self._frames += 1
      else:
        record = ReplayEvent.from_dict(row['data'])
        if self._version == 1 and record.event_type is ReplayEventType.STATE_SNAPSHOT:
          raise ReplayFormatError('Native match origins require replay file version 2')
        if record.retained_bytes > self.limits.event_bytes:
          raise ReplayCapacityError('Replay event byte capacity exceeded')
        current = record.frame_id, record.timestamp_ms
        if self._last_event is not None and any(value < previous for value, previous in zip(current, self._last_event)):
          raise ReplayFormatError('Replay file events are out of order')
        self._last_event = current
        self._events += 1
      self._digest.update(raw)
      self._peak = max(self._peak, record.retained_bytes)
      return record
    except StopIteration:
      raise
    except BaseException:
      self.close()
      raise

  def stats(self):
    self._process()
    return dict(frames=self._frames, events=self._events, bytes_read=self._bytes,
                peak_record_bytes=self._peak, verified=self._finished, closed=self._closed)

  def close(self):
    self._process()
    stream, self._stream = self._stream, None
    self._closed = True
    if stream is not None:
      stream.close()

  def __enter__(self): return self
  def __exit__(self, kind, value, traceback): self.close()
  def __del__(self):
    if hasattr(self, '_stream') and self._pid == os.getpid():
      try:
        self.close()
      except BaseException:
        pass


def save_replay(replay, path, *, directory_limits=None):
  if type(replay) is not Replay or not replay.is_sealed:
    raise ReplayFormatError('File export requires a sealed Replay')
  if directory_limits is not None and type(directory_limits) is not dict:
    raise ValueError('Expected directory limit options')
  # Reuse actual OS-coordinated reservations, fsync/replace and failure cleanup.
  # These output dependencies are loaded only by a real export, not by readers.
  from gfootball.replay_io import AtomicReplayFile
  from gfootball.recording_buffers import RecordingCapacityError
  digest = hashlib.sha256()
  try:
    with AtomicReplayFile(path, replay.limits.file_bytes, directory_limits=directory_limits) as output:
      def write(value, hashed=True):
        data = _encoded(value, replay.limits.line_bytes)
        output.write(data)
        if hashed:
          digest.update(data)
      # 2026-09-10: ordinary historical recordings keep their v1 format.
      # write(dict(format='football.frame_replay', version=1, metadata=replay.metadata(),
      version = 2 if any(event.event_type is ReplayEventType.STATE_SNAPSHOT for event in replay.events) else 1
      write(dict(format='football.frame_replay', version=version, metadata=replay.metadata(),
                 frames=len(replay.frames), events=len(replay.events)))
      for frame in replay.frames:
        write(dict(kind='frame', data=frame.to_dict()))
      for event in replay.events:
        write(dict(kind='event', data=event.to_dict()))
      write(dict(kind='end', frames=len(replay.frames), events=len(replay.events), sha256=digest.hexdigest()), False)
  except RecordingCapacityError as error:
    raise ReplayCapacityError('Replay output capacity exceeded') from error
  return str(Path(path))


# 2026-09-10: allow the owning manager to stop its single staged read.
# def load_replay(path, *, limits=None):
#   with ReplayFileReader(path, limits=limits) as reader:
def load_replay(path, *, limits=None, cancelled=None):
  with ReplayFileReader(path, limits=limits, cancelled=cancelled) as reader:
    replay = Replay(**reader.metadata, limits=reader.limits)
    for record in reader:
      if type(record) is ReplayFrame:
        replay.add_frame(record)
      else:
        replay.add_event(record)
    return replay.seal()
