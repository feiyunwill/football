# 2026-09-09: streaming, bounded replay I/O without importing Gym/native engine.
"""Read trusted local pickle traces and convert them with bounded retention.

Pickle can execute code; these limits do not make untrusted pickle safe or bound
arbitrary reducer/native allocations. File and record bytes are checked before
reads; decoded observations are validated before being retained by this module.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import os
from pathlib import Path
import pickle
import stat
import shutil
import sys
import tempfile
from types import MappingProxyType

import numpy as np

from gfootball.recording_buffers import (
    ObservationState, RecordedAction, RecordingCapacityError, RecordingLimits,
)


class ReplayFormatError(ValueError):
  pass


class ReplayExhausted(EOFError):
  """All recorded input was consumed; library code never exits the process."""


@dataclass(frozen=True)
class ReplayLimits:
  file_bytes: int = 128 * 1024 * 1024
  record_bytes: int = 32 * 1024 * 1024
  records: int = 10000
  load_bytes: int = 256 * 1024 * 1024
  output_bytes: int = 128 * 1024 * 1024
  output_records: int = 100000
  text_bytes: int = 128 * 1024 * 1024
  padding_steps: int = 10
  source_bytes: int = 8 * 1024 * 1024
  sources: int = 22
  consumers: int = 22

  def __post_init__(self):
    for name, minimum, maximum in (
        ('file_bytes', 128, 1024**3), ('record_bytes', 64, 64 * 1024**2),
        # 2026-09-09: converted streams may reach the same 1M cap as output_records.
        # ('records', 1, 100000), ('load_bytes', 2048, 512 * 1024**2),
        ('records', 1, 1000000), ('load_bytes', 2048, 512 * 1024**2),
        ('output_bytes', 128, 1024**3), ('output_records', 1, 1000000),
        ('text_bytes', 128, 512 * 1024**2), ('padding_steps', 0, 1000),
        ('source_bytes', 2048, 128 * 1024**2), ('sources', 1, 22), ('consumers', 1, 22)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid replay limit: ' + name)


class _RecordInput:
  def __init__(self, stream, maximum):
    self.stream, self.maximum, self.used = stream, maximum, 0

  def _size(self, size):
    if size < 0:
      return self.maximum - self.used
    if size > self.maximum - self.used:
      raise RecordingCapacityError('Serialized replay record byte budget exceeded')
    return size

  def read(self, size=-1):
    data = self.stream.read(self._size(size))
    self.used += len(data)
    return data

  def readline(self, size=-1):
    limit = self._size(size)
    if limit == 0:
      raise RecordingCapacityError('Serialized replay line byte budget exceeded')
    data = self.stream.readline(limit)
    self.used += len(data)
    if data and not data.endswith(b'\n') and len(data) == limit:
      raise RecordingCapacityError('Serialized replay line byte budget exceeded')
    return data

  def readinto(self, buffer):
    size = memoryview(buffer).nbytes
    self._size(size)
    count = self.stream.readinto(buffer)
    self.used += count
    return count


class ReplayReader:
  """One validated observation at a time; EOF closes the file, reset reopens it."""
  def __init__(self, path, *, limits=None, observation_limits=None, action_adapter=None):
    self.path = Path(path)
    # 2026-09-09: false/empty invalid values must not silently select defaults.
    # self.limits = limits or ReplayLimits()
    # self.observation_limits = observation_limits or RecordingLimits()
    self.limits = ReplayLimits() if limits is None else limits
    self.observation_limits = RecordingLimits() if observation_limits is None else observation_limits
    if not isinstance(self.limits, ReplayLimits) or not isinstance(self.observation_limits, RecordingLimits):
      raise ValueError('Expected replay and observation limits')
    self.action_adapter = action_adapter
    self._stream = None
    self._identity = None
    self._closed = False
    # 2026-09-09: commit state belongs to the writer, never the replay reader.
    # self._committed = False
    self._ended = False
    self._count = self._bytes = self._peak_step = self._opens = 0
    self._open()

  def _fingerprint(self):
    info = os.fstat(self._stream.fileno())
    if not stat.S_ISREG(info.st_mode):
      raise ReplayFormatError('Replay input must be a regular file')
    if info.st_size > self.limits.file_bytes:
      raise RecordingCapacityError('Replay file byte budget exceeded')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

  def _open(self):
    try:
      self._stream = self.path.open('rb', buffering=64 * 1024)
      current = self._fingerprint()
      if self._identity is not None and current != self._identity:
        raise ReplayFormatError('Replay input changed since it was opened')
      self._identity = current
      self._opens += 1
    except BaseException:
      self.close()
      raise

  def _unchanged(self):
    if self._fingerprint() != self._identity:
      raise ReplayFormatError('Replay input changed while being read')

  def __iter__(self):
    return self

  def __next__(self):
    if self._closed:
      raise RuntimeError('Replay reader is closed')
    if self._ended:
      raise StopIteration
    try:
      self._unchanged()
      start = self._stream.tell()
      if start == self._identity[2]:
        self._ended = True
        self._stream.close()
        self._stream = None
        raise StopIteration
      if self._count >= self.limits.records:
        raise RecordingCapacityError('Replay record count exceeded')
      source = _RecordInput(self._stream, self.limits.record_bytes)
      try:
        decoded = pickle.load(source)
      except (EOFError, pickle.UnpicklingError) as error:
        raise ReplayFormatError('Replay record is truncated or invalid') from error
      self._unchanged()
      state = ObservationState(decoded, limits=self.observation_limits,
                               action_adapter=self.action_adapter)
      self._count += 1
      self._bytes += self._stream.tell() - start
      self._peak_step = max(self._peak_step, state.retained_bytes)
      return state
    except StopIteration:
      raise
    except BaseException:
      self.close()
      raise

  def reset(self):
    if self._closed:
      raise RuntimeError('Replay reader is closed')
    try:
      if self._stream is None:
        self._open()
      else:
        self._unchanged()
        self._stream.seek(0)
      self._ended = False
      self._count = self._bytes = self._peak_step = 0
    except BaseException:
      self.close()
      raise

  def close(self):
    stream, self._stream = self._stream, None
    self._closed = True
    if stream is not None:
      stream.close()

  def stats(self):
    return dict(records=self._count, serialized_bytes=self._bytes,
                peak_step_bytes=self._peak_step, file_opens=self._opens,
                open=self._stream is not None, closed=self._closed, ended=self._ended)

  def __enter__(self):
    if self._closed:
      raise RuntimeError('Replay reader is closed')
    return self

  def __exit__(self, kind, value, traceback):
    self.close()

  def __del__(self):
    if hasattr(self, '_stream'):
      try:
        self.close()
      except BaseException:
        pass


def retained_bytes(value, action_adapter=None):
  """Charge repeated references conservatively in an already validated value."""
  if isinstance(value, MappingProxyType):
    return sys.getsizeof(value) + sys.getsizeof(dict(value)) + sum(
        retained_bytes(key, action_adapter) + retained_bytes(item, action_adapter) for key, item in value.items())
  if type(value) is dict:
    return sys.getsizeof(value) + sum(retained_bytes(key, action_adapter) + retained_bytes(item, action_adapter)
                                    for key, item in value.items())
  if isinstance(value, (list, tuple)):
    return sys.getsizeof(value) + sum(retained_bytes(item, action_adapter) for item in value)
  if isinstance(value, np.ndarray):
    if value.flags.owndata:
      return sys.getsizeof(value)
    if type(value.base) is not bytes:
      raise ValueError('Replay accounting requires an owned dense array')
    return sys.getsizeof(value) + sys.getsizeof(value.base)
  if action_adapter is not None and type(value) is action_adapter.action_type:
    action_adapter.freeze(value)
    return sys.getsizeof(value) + sys.getsizeof(vars(value)) + sum(
        sys.getsizeof(key) + sys.getsizeof(item) for key, item in vars(value).items())
  return sys.getsizeof(value)


def _mutable_arrays(value):
  if type(value) is dict:
    return {key: _mutable_arrays(item) for key, item in value.items()}
  if type(value) is list:
    return [_mutable_arrays(item) for item in value]
  if type(value) is tuple:
    return tuple(_mutable_arrays(item) for item in value)
  if type(value) is np.ndarray:
    return value.copy(order='C')
  return value


def load_replay(path, *, limits=None, observation_limits=None, action_adapter=None):
  """Compatibility list API, bounded by record count and actual retained bytes."""
  # 2026-09-09: only an omitted limit selects defaults.
  # limits = limits or ReplayLimits()
  limits = ReplayLimits() if limits is None else limits
  result, used = [], 0
  with ReplayReader(path, limits=limits, observation_limits=observation_limits,
                    action_adapter=action_adapter) as reader:
    for state in reader:
      record = _mutable_arrays(state.to_record())
      size = retained_bytes(record, action_adapter)
      if used + size + sys.getsizeof(result) > limits.load_bytes:
        raise RecordingCapacityError('Loaded replay byte budget exceeded; use streaming iteration')
      result.append(record)
      used += size
      if used + sys.getsizeof(result) > limits.load_bytes:
        raise RecordingCapacityError('Loaded replay container byte budget exceeded')
  return result


def first_config(state):
  debug = state._trace['debug']
  if 'config' not in debug or not isinstance(debug['config'], MappingProxyType):
    raise ReplayFormatError('First replay record must include a configuration dictionary')
  # Extract only bounded debug metadata; do not copy the complete observation.
  from gfootball.recording_buffers import _thaw
  return _thaw(debug['config'], state._adapter)


def replay_timing(physics_steps_per_frame, fps, physics_hz=100):
  if (type(physics_hz) is not int or not 1 <= physics_hz <= 1000
      or type(fps) is not int or not 1 <= fps <= physics_hz
      or type(physics_steps_per_frame) is not int or not 1 <= physics_steps_per_frame <= physics_hz):
    raise ValueError('Replay timing must use positive integer physics steps and FPS')
  if physics_hz % fps:
    raise ValueError('Replay FPS must divide the physics tick rate exactly')
  steps = physics_hz // fps
  if physics_steps_per_frame % steps:
    raise ValueError('Replay FPS must preserve every recorded action boundary')
  return steps, physics_steps_per_frame // steps


def expanded_actions(states, fps, idle_action, *, action_adapter, limits=None, physics_hz=100):
  """Stream private action-only replay input, preserving original action timing."""
  # 2026-09-09: reject invalid explicit policies before conversion.
  # limits = limits or ReplayLimits()
  limits = ReplayLimits() if limits is None else limits
  if not isinstance(limits, ReplayLimits):
    raise ValueError('Expected replay limits')
  idle = action_adapter.freeze(idle_action)
  count = 0
  source_frame = 0
  expected_actions = None
  configuration = None

  def actions_for(state):
    actions = state._trace['debug'].get('action')
    # 2026-09-09: AI-only environments legitimately record zero controlled slots.
    # if not isinstance(actions, tuple) or not 1 <= len(actions) <= 22:
    #   raise ReplayFormatError('Replay action vector must contain 1..22 actions')
    if not isinstance(actions, tuple) or not 0 <= len(actions) <= 22:
      raise ReplayFormatError('Replay action vector must contain 0..22 actions')
    if any(type(action) is not RecordedAction and (type(action) is not int or not 0 <= action <= 65535)
           for action in actions):
      raise ReplayFormatError('Replay actions must be registered actions or integer indices')
    return actions

  def record(actions, config=None):
    nonlocal count
    if count >= limits.output_records:
      raise RecordingCapacityError('Expanded replay record count exceeded')
    debug = dict(frame_cnt=count, action=[action_adapter.thaw(action) if type(action) is RecordedAction else action
                                          for action in actions])
    if config is not None:
      debug['config'] = config
    count += 1
    return dict(observation={}, debug=debug)

  for state in states:
    actions = actions_for(state)
    # 2026-09-09: missing/duplicated records cannot silently shift action timing.
    frame = state._trace['debug'].get('frame_cnt')
    if type(frame) is not int or frame != source_frame:
      raise ReplayFormatError('Playback requires consecutive frames starting at zero')
    source_frame += 1
    if expected_actions is None:
      # 2026-09-09: bool/float zero are not valid logical frame identifiers.
      # if state._trace['debug'].get('frame_cnt') != 0:
      origin = state._trace['debug'].get('frame_cnt')
      if type(origin) is not int or origin != 0:
        raise ReplayFormatError('Playback requires a trace starting at frame zero')
      configuration = first_config(state)
      steps, factor = replay_timing(configuration.get('physics_steps_per_frame'), fps, physics_hz)
      configuration['physics_steps_per_frame'] = steps
      expected_actions = len(actions)
    elif len(actions) != expected_actions:
      raise ReplayFormatError('Replay action count changed within a trace')
    yield record(actions, configuration if count == 0 else None)
    for _ in range(factor - 1):
      yield record((idle,) * expected_actions)
  if expected_actions is None:
    raise ReplayFormatError('Replay input is empty')
  for _ in range(limits.padding_steps):
    yield record((idle,) * expected_actions)


class AtomicReplayFile:
  """Stream a named export; replace the requested target only after success."""
  def __init__(self, path, maximum, *, directory_limits=None):
    # Import output dependencies only for actual writes; readers need no OpenCV.
    from gfootball.recording_output import OutputBudget, OutputLimits, _BoundedFile
    target = Path(path)
    self.path = target.parent.resolve() / target.name
    options = dict(directory_limits or {})
    options['dump_bytes'] = maximum
    self.budget = OutputBudget(self.path.parent, OutputLimits(**options))
    self._token = None
    self._temporary = None
    self._identity = None
    self._stream = None
    self._writer = None
    self._closed = False
    self._committed = False
    try:
      self._token = self.budget.reserve()
      fd, self._temporary = self.budget.temporary(self._token, '.dump.part')
      try:
        info = os.fstat(fd)
        self._identity = info.st_dev, info.st_ino
        self._stream = os.fdopen(fd, 'wb')
      except BaseException:
        os.close(fd)
        raise
      self._writer = _BoundedFile(self._stream, maximum)
    except BaseException as error:
      # 2026-09-09: cleanup failures must not hide the original output error.
      # self.abort()
      self._abort_after_error(error)
      raise

  def _abort_after_error(self, original):
    try:
      self.abort()
    except BaseException:
      if hasattr(original, 'add_note'):
        original.add_note('Replay temporary-file cleanup also failed.')

  def write(self, data):
    if self._closed:
      raise RuntimeError('Replay output is closed')
    # 2026-09-09: direct API callers receive the same failure cleanup as with.
    # return self._writer.write(data)
    try:
      return self._writer.write(data)
    except BaseException as error:
      self._abort_after_error(error)
      raise

  def dump(self, record):
    # 2026-09-09: reducers can fail before calling write at all.
    # pickle.dump(record, self, protocol=4)
    try:
      pickle.dump(record, self, protocol=4)
    except BaseException as error:
      self._abort_after_error(error)
      raise

  def _close_stream(self):
    stream, self._stream = self._stream, None
    self._writer = None
    if stream is not None:
      stream.close()

  def abort(self):
    from gfootball.recording_output import _unlink_owned
    try:
      self._close_stream()
    finally:
      try:
        if self._temporary is not None and self._identity is not None:
          with self.budget.transaction(self._token, cleanup=True):
            _unlink_owned(self._temporary, self._identity)
            self._temporary = None
      finally:
        self.budget.release(self._token)
        self._token = None
        self._closed = True

  def commit(self):
    if self._committed:
      return str(self.path)
    if self._closed:
      raise RuntimeError('Replay output is closed')
    try:
      with self.budget.transaction(self._token):
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._close_stream()
        os.replace(self._temporary, self.path)
        self._temporary = None
        self.budget.release(self._token)
        self._token = None
        self._closed = True
        self._committed = True
      return str(self.path)
    except BaseException as error:
      # 2026-09-09: report the actual flush/publication failure first.
      # self.abort()
      self._abort_after_error(error)
      raise

  def __enter__(self):
    return self

  def __exit__(self, kind, value, traceback):
    if kind is None:
      self.commit()
    else:
      try:
        self.abort()
      except BaseException:
        if hasattr(value, 'add_note'):
          value.add_note('Replay temporary-file cleanup also failed.')

  def __del__(self):
    if hasattr(self, '_token'):
      try:
        self.abort()
      except BaseException:
        pass


def _text_parts(value):
  if isinstance(value, MappingProxyType) or type(value) is dict:
    yield '{'
    for index, (key, item) in enumerate(value.items()):
      if index:
        yield ', '
      yield repr(key)
      yield ': '
      yield from _text_parts(item)
    yield '}'
  elif type(value) is RecordedAction:
    yield value.name
  elif isinstance(value, (list, tuple)):
    # Frozen observation lists retain a tuple subtype distinct from true tuples.
    is_tuple = type(value) is tuple
    yield '(' if is_tuple else '['
    for index, item in enumerate(value):
      if index:
        yield ', '
      yield from _text_parts(item)
    if is_tuple and len(value) == 1:
      yield ','
    yield ')' if is_tuple else ']'
  elif isinstance(value, np.ndarray):
    yield 'array(shape=%r, dtype=%r, values=' % (value.shape, value.dtype.str)
    # All options bound display work independently of global NumPy print settings.
    yield np.array2string(value, max_line_width=80, precision=8, suppress_small=False,
                          separator=', ', threshold=1000, edgeitems=3, formatter={})
    yield ')'
  else:
    yield repr(value)


def export_text(source, target, include_debug=True, *, limits=None, observation_limits=None,
                action_adapter=None, directory_limits=None):
  if type(include_debug) is not bool:
    raise ValueError('include_debug must be a bool')
  # 2026-09-09: only an omitted limit selects defaults; the reader validates it.
  # limits = limits or ReplayLimits()
  limits = ReplayLimits() if limits is None else limits
  if Path(target).exists() and os.path.samefile(source, target):
    raise ValueError('Text export cannot replace its replay input')
  with ReplayReader(source, limits=limits, observation_limits=observation_limits,
                    action_adapter=action_adapter) as reader:
    with AtomicReplayFile(target, limits.text_bytes, directory_limits=directory_limits) as output:
      output.write(b'[')
      for index, state in enumerate(reader):
        if index:
          output.write(b',\n')
        record = {key: item for key, item in state._trace.items() if include_debug or key != 'debug'}
        for part in _text_parts(record):
          output.write(part.encode('utf-8'))
      output.write(b']\n')
  return str(Path(target))


@contextmanager
def temporary_replay_directory():
  """Remove only this freshly-created directory after all reader owners close."""
  parent = Path(tempfile.gettempdir()).resolve()
  path = Path(tempfile.mkdtemp(prefix='football-replay-', dir=parent)).resolve()
  identity = path.stat()
  error = None
  try:
    yield path
  except BaseException as original:
    error = original
    raise
  finally:
    try:
      current = path.lstat()
      if (path.parent != parent or not path.name.startswith('football-replay-')
          or path.resolve() != path or not stat.S_ISDIR(current.st_mode)
          or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)):
        raise OSError('Replay temporary directory changed ownership')
      shutil.rmtree(path)
    except BaseException:
      if error is None:
        raise
      if hasattr(error, 'add_note'):
        error.add_note('Replay temporary directory cleanup also failed.')


def drive_replay(factory, config, expected_frames, *, render=True):
  """Drive the real supplied environment and close on every result/error path."""
  if type(expected_frames) is not int or not 1 <= expected_frames <= 1000000 or type(render) is not bool:
    raise ValueError('Invalid replay frame budget or render flag')
  environment = factory(config)
  success = False
  error = None
  started = False
  try:
    if render:
      environment.render()
    environment.reset()
    started = True
    for frame in range(expected_frames):
      try:
        _, _, done, _ = environment.step([])
      except ReplayExhausted as original:
        raise ReplayFormatError('Replay input ended before the converted frame count') from original
      if done:
        success = True
        return dict(frames=frame + 1, episode_done=True, source_exhausted=False)
    success = True
    return dict(frames=expected_frames, episode_done=False, source_exhausted=True)
  except BaseException as original:
    error = original
    if isinstance(original, KeyboardInterrupt) and started:
      try:
        environment.write_dump('shutdown')
      except BaseException:
        if hasattr(original, 'add_note'):
          original.add_note('Interrupted replay shutdown recording failed.')
    raise
  finally:
    try:
      environment.close(finalize=success)
    except BaseException:
      if error is None:
        raise
      if hasattr(error, 'add_note'):
        error.add_note('Replay environment cleanup also failed.')
