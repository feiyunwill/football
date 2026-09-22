# Copyright 2026 Google LLC
# 2026-09-09: independently usable, bounded observation ownership for recording.
"""Own immutable observation data without importing Gym or the native engine.

Budgets conservatively charge repeated references again. Arrays own dense bytes
instead of retaining arbitrary NumPy bases, object dtypes or dtype metadata.
Reader-held evicted states and mutable dump dictionaries belong to the caller.
"""
import collections
from dataclasses import dataclass
import math
import re
import struct
import sys
import threading
from types import MappingProxyType
import weakref

import numpy as np


# 2026-09-10: directory reservations must be usable without importing NumPy.
# class RecordingCapacityError(ValueError):
#   pass
from gfootball.recording_errors import RecordingCapacityError


@dataclass(frozen=True)
class RecordingLimits:
  trace_steps: int = 100
  trace_bytes: int = 256 * 1024 * 1024
  step_bytes: int = 32 * 1024 * 1024
  debug_bytes: int = 1024 * 1024
  frame_bytes: int = 16 * 1024 * 1024
  additional_frames: int = 16
  additional_bytes: int = 16 * 1024 * 1024
  debug_lines: int = 64
  debug_line_bytes: int = 4096
  debug_text_bytes: int = 64 * 1024
  nodes: int = 8192
  depth: int = 16
  string_bytes: int = 64 * 1024
  dump_names: int = 32

  def __post_init__(self):
    for name, minimum, maximum in (
        ('trace_steps', 1, 1000), ('trace_bytes', 4096, 512 * 1024 * 1024),
        ('step_bytes', 2048, 64 * 1024 * 1024), ('debug_bytes', 128, 4 * 1024 * 1024),
        ('frame_bytes', 128, 32 * 1024 * 1024), ('additional_frames', 0, 64),
        ('additional_bytes', 0, 64 * 1024 * 1024), ('debug_lines', 0, 256),
        ('debug_line_bytes', 64, 16384), ('debug_text_bytes', 0, 1024 * 1024),
        ('nodes', 16, 32768), ('depth', 1, 32), ('string_bytes', 64, 1024 * 1024),
        ('dump_names', 4, 64)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid recording limit: ' + name)
    if self.step_bytes > self.trace_bytes:
      raise ValueError('One observation budget must fit in the trace budget')


class RecordedAction(collections.namedtuple('RecordedActionFields', 'backend name sticky directional')):
  __slots__ = ()

  @property
  def _backend_action(self):
    return self.backend

  @property
  def _name(self):
    return self.name

  @property
  def _sticky(self):
    return self.sticky

  @property
  def _directional(self):
    return self.directional


class ActionAdapter:
  """Explicitly register the small native CoreAction value, not arbitrary objects."""
  def __init__(self, action_type, restore):
    if not isinstance(action_type, type) or not callable(restore):
      raise ValueError('Action adapter requires a type and restore callable')
    self.action_type, self.restore = action_type, restore

  def freeze(self, action):
    if type(action) is not self.action_type or set(vars(action)) != {
        '_backend_action', '_name', '_sticky', '_directional'}:
      raise ValueError('Unsupported recording action')
    result = RecordedAction(int(action._backend_action), action._name,
                            action._sticky, action._directional)
    validate_action(result)
    return result

  def thaw(self, action):
    result = self.restore(action)
    if self.freeze(result) != action:
      raise ValueError('Action adapter changed recorded input')
    return result


def validate_action(action):
  if (type(action.backend) is not int or not 0 <= action.backend <= 65535 or
      # 2026-09-09: reject giant text before allocating its UTF-8 conversion.
      # type(action.name) is not str or len(action.name.encode('utf-8')) > 128 or
      type(action.name) is not str or len(action.name) > 128 or len(action.name.encode('utf-8')) > 128 or
      type(action.sticky) is not bool or type(action.directional) is not bool):
    raise ValueError('Invalid recording action')


def validate_dump_name(name):
  # 2026-09-09: character count is a cheap necessary bound before encoding.
  # if (type(name) is not str or not name or len(name.encode('utf-8')) > 64 or
  if (type(name) is not str or not name or len(name) > 64 or len(name.encode('utf-8')) > 64 or
      name in ('.', '..') or name[-1] in ('.', ' ') or
      any(ord(c) < 32 or c in '/\\:*?"<>|' for c in name)):
    raise ValueError('Invalid dump name')
  if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', name.split('.')[0], flags=re.IGNORECASE):
    raise ValueError('Reserved dump name')
  return name


class _FrozenList(tuple):
  __slots__ = ()


class _ImmutableArray(np.ndarray):
  """Bytes-backed array whose public shape/dtype metadata cannot be reassigned."""
  __slots__ = ()

  def __setattr__(self, name, value):
    raise AttributeError('Recording arrays are immutable; make an explicit copy')


def _array_storage_bytes(value):
  header = sys.getsizeof(np.ndarray.__new__(_ImmutableArray, (0,) * value.ndim,
                                           dtype=np.uint8, buffer=b'\0'))
  return header + sys.getsizeof(b'') + value.nbytes


class _Freezer:
  def __init__(self, limits, adapter=None, keep_frame=True, maximum=None):
    self.limits, self.adapter, self.keep_frame = limits, adapter, keep_frame
    self.maximum = limits.step_bytes if maximum is None else maximum
    self.used = 0
    self.nodes = 0
    self.active = set()

  def charge(self, amount):
    if amount > self.maximum - self.used:
      raise RecordingCapacityError('Observation byte budget exceeded')
    self.used += amount

  def freeze(self, value, path=()):
    previous_maximum = self.maximum
    if path == ('debug',):
      self.maximum = min(self.maximum, self.used + self.limits.debug_bytes)
    try:
      return self._freeze(value, path)
    finally:
      self.maximum = previous_maximum

  def _freeze(self, value, path):
    self.nodes += 1
    if self.nodes > self.limits.nodes or len(path) > self.limits.depth:
      raise RecordingCapacityError('Observation structure budget exceeded')
    kind = type(value)
    if value is None or kind in (bool, float, complex):
      self.charge(sys.getsizeof(value))
      return value
    if kind is int:
      if value.bit_length() > 64:
        raise RecordingCapacityError('Recording integer exceeds 64 bits')
      self.charge(sys.getsizeof(value))
      return value
    if kind in (str, bytes):
      size = sys.getsizeof(value)
      if size > self.limits.string_bytes:
        raise RecordingCapacityError('Recording string exceeds its byte budget')
      self.charge(size)
      return value
    if isinstance(value, np.generic):
      if value.dtype.kind not in 'biufc' or value.dtype.itemsize > 16:
        raise ValueError('Unsupported NumPy recording scalar')
      scalar = value.item()
      if type(scalar) not in (bool, int, float, complex):
        raise ValueError('Unsupported NumPy recording scalar conversion')
      return self.freeze(scalar, path)
    # 2026-09-09: accept our own immutable view but not arbitrary subclasses.
    # if kind is np.ndarray:
    if kind in (np.ndarray, _ImmutableArray):
      if value.dtype.kind not in 'biufc' or value.dtype.itemsize > 16 or value.ndim > 4:
        raise ValueError('Recording arrays must have a plain numeric dtype and at most four dimensions')
      if path == ('observation', 'frame'):
        validate_frame(value, self.limits)
      # Validate before materializing a dense copy of a view/broadcast array.
      # Canonical dtype strings discard arbitrary caller-owned dtype metadata.
      dtype = np.dtype(value.dtype.str)
      # 2026-09-09: include the exact immutable subclass header on this runtime,
      # also for zero-dimensional arrays; no fixed CPython/NumPy ABI assumption.
      # header = sys.getsizeof(np.ndarray((0,) * value.ndim, dtype=dtype, buffer=b'')) if value.ndim else 96
      # 2026-09-09: share exact header accounting with the video-frame validator.
      # header = sys.getsizeof(np.ndarray.__new__(_ImmutableArray, (0,) * value.ndim,
      #                                          dtype=np.uint8, buffer=b'\0'))
      # estimate = header + sys.getsizeof(b'') + value.nbytes
      estimate = _array_storage_bytes(value)
      self.charge(estimate)
      raw = value.tobytes(order='C')
      # 2026-09-09: readonly payload alone still allowed shape/dtype mutation.
      # owned = np.ndarray(value.shape, dtype=dtype, buffer=raw)
      owned = np.ndarray.__new__(_ImmutableArray, value.shape, dtype=dtype, buffer=raw)
      actual = sys.getsizeof(owned) + sys.getsizeof(raw)
      self.charge(actual - estimate)
      return owned
    if kind is RecordedAction:
      validate_action(value)
      self.charge(sys.getsizeof(value))
      for field in value:
        self.freeze(field, path + ('action',))
      return value
    if self.adapter is not None and kind is self.adapter.action_type:
      return self.freeze(self.adapter.freeze(value), path)
    if kind not in (dict, list, tuple):
      raise ValueError('Unsupported observation value: ' + kind.__name__)
    if id(value) in self.active:
      raise ValueError('Cyclic observation data is not supported')
    if len(value) > self.limits.nodes - self.nodes:
      raise RecordingCapacityError('Observation container exceeds the node budget')
    self.active.add(id(value))
    try:
      if kind is dict:
        owned = {}
        self.charge(sys.getsizeof(owned) + sys.getsizeof(MappingProxyType(owned)))
        for key, item in value.items():
          if path == ('observation',) and key == 'frame' and not self.keep_frame:
            continue
          if type(key) not in (str, int, bool):
            raise ValueError('Recording dictionary keys must be scalar names or indices')
          frozen_key = self.freeze(key, path + ('key',))
          frozen_item = self.freeze(item, path + (key,))
          previous_size = sys.getsizeof(owned)
          owned[frozen_key] = frozen_item
          self.charge(sys.getsizeof(owned) - previous_size)
        return MappingProxyType(owned)
      estimate = sys.getsizeof(()) + len(value) * struct.calcsize('P')
      self.charge(estimate)
      values = [self.freeze(item, path + (index,)) for index, item in enumerate(value)]
      result = _FrozenList(values) if kind is list else tuple(values)
      self.charge(sys.getsizeof(result) - estimate)
      return result
    finally:
      self.active.remove(id(value))


def validate_frame(frame, limits):
  # 2026-09-09: keep immutable cache frames usable as inputs to recording APIs.
  # if (type(frame) is not np.ndarray or frame.dtype != np.dtype('uint8') or
  if (type(frame) not in (np.ndarray, _ImmutableArray) or frame.dtype != np.dtype('uint8') or
      frame.ndim != 3 or frame.shape[2] != 3 or
      not 1 <= frame.shape[0] <= 4096 or not 1 <= frame.shape[1] <= 4096):
    raise ValueError('Video frame must be an H x W x 3 uint8 array within 4096 pixels per dimension')
  # 2026-09-09: avoid an ABI-specific 160-byte ndarray-header assumption.
  # if frame.nbytes + sys.getsizeof(b'') + 160 > limits.frame_bytes:
  if _array_storage_bytes(frame) > limits.frame_bytes:
    raise RecordingCapacityError('Video frame exceeds its byte budget')


def _thaw(value, adapter, path=(), include_frame=True):
  if isinstance(value, MappingProxyType):
    return {key: _thaw(item, adapter, path + (key,), include_frame)
            for key, item in value.items()
            if not (path == ('observation',) and key == 'frame' and not include_frame)}
  if type(value) is RecordedAction:
    if adapter is None:
      raise ValueError('Native action restoration requires its explicit adapter')
    return adapter.thaw(value)
  if isinstance(value, tuple):
    entries = [_thaw(item, adapter, path, include_frame) for item in value]
    return entries if type(value) is _FrozenList else tuple(entries)
  if type(value) is _ImmutableArray:
    # Preserve the legacy ndarray pickle type and isolate the outgoing header.
    return value.view(np.ndarray)
  # Immutable scalars and bytes-backed arrays can safely be shared with a dump.
  return value


class ObservationState:
  def __init__(self, trace, *, limits=None, action_adapter=None, keep_frame=True):
    self.limits = limits or RecordingLimits()
    if not isinstance(self.limits, RecordingLimits):
      raise ValueError('Expected RecordingLimits')
    if type(trace) is not dict or type(trace.get('observation')) is not dict or type(trace.get('debug')) is not dict:
      raise ValueError('Observation trace requires observation and debug dictionaries')
    # 2026-09-09: reserve the two fixed cache headers even for standalone states.
    # freezer = _Freezer(self.limits, action_adapter, keep_frame)
    overhead = 2 * sys.getsizeof(collections.deque())
    freezer = _Freezer(self.limits, action_adapter, keep_frame,
                       maximum=self.limits.step_bytes - overhead)
    self._trace = freezer.freeze(trace)
    self._base_bytes = freezer.used
    self._adapter = action_adapter
    self._frames = collections.deque()
    self._texts = collections.deque()
    self._frame_bytes = 0
    self._text_bytes = 0
    self._dropped_frames = 0
    self._dropped_texts = 0
    self._owner = None

  @property
  def retained_bytes(self):
    return (self._base_bytes + self._frame_bytes + self._text_bytes +
            sys.getsizeof(self._frames) + sys.getsizeof(self._texts))

  @property
  def _additional_frames(self):
    return tuple(item[0] for item in self._frames)

  @property
  def _debugs(self):
    return tuple(item[0] for item in self._texts)

  def __getitem__(self, key):
    if key in self._trace:
      return self._trace[key]
    if key in self._trace['observation']:
      return self._trace['observation'][key]
    return self._trace['debug'][key]

  def __contains__(self, key):
    return key in self._trace or key in self._trace['observation'] or key in self._trace['debug']

  def _distance(self, first, second):
    first = np.asarray(first)
    second = np.asarray(second)
    if len(first) == 2:
      first = np.append(first, 0)
    if len(second) == 2:
      second = np.append(second, 0)
    return np.linalg.norm(first - second)

  def to_record(self, include_frame=True, first_config=None):
    result = _thaw(self._trace, self._adapter, include_frame=include_frame)
    if first_config is not None:
      frozen = _Freezer(self.limits, self._adapter, maximum=self.limits.debug_bytes).freeze(first_config)
      result['debug']['config'] = _thaw(frozen, self._adapter)
    return result

  def _mutate(self, kind, value):
    owner = self._owner() if self._owner is not None else None
    if owner is not None:
      return owner._mutate(self, kind, value)
    return self._append(kind, value)

  def add_frame(self, frame):
    return self._mutate('frame', frame)

  def add_debug(self, text):
    return self._mutate('text', text)

  def _append(self, kind, value):
    if kind == 'frame':
      validate_frame(value, self.limits)
      if self.limits.additional_frames == 0 or self.limits.additional_bytes == 0:
        self._dropped_frames += 1
        return False
      freezer = _Freezer(self.limits, maximum=self.limits.frame_bytes)
      owned = freezer.freeze(value)
      queue, limit, count = self._frames, self.limits.additional_bytes, self.limits.additional_frames
      size = freezer.used + sys.getsizeof((None, 0))
      retained = self._frame_bytes
    else:
      if type(value) is not str:
        raise ValueError('Debug line must be text')
      size = sys.getsizeof(value) + sys.getsizeof((None, 0))
      if sys.getsizeof(value) > self.limits.debug_line_bytes:
        raise RecordingCapacityError('Debug line exceeds its byte budget')
      owned = value
      queue, limit, count = self._texts, self.limits.debug_text_bytes, self.limits.debug_lines
      retained = self._text_bytes
    if count == 0 or size > limit:
      if kind == 'frame':
        self._dropped_frames += 1
      else:
        self._dropped_texts += 1
      return False
    # 2026-09-09: account actual staged deque capacity instead of guessing a
    # 528-byte block expansion before the new record is inserted.
    # candidate = collections.deque(queue)
    # dropped = 0
    # while candidate and (len(candidate) >= count or retained + size > limit or
    #                      self.retained_bytes - (self._frame_bytes if kind == 'frame' else self._text_bytes)
    #                      + retained + size + 528 > self.limits.step_bytes):
    #   retained -= candidate.popleft()[1]
    #   dropped += 1
    # candidate.append((owned, size))
    # total = self.retained_bytes - (self._frame_bytes if kind == 'frame' else self._text_bytes)
    # total += retained + size + sys.getsizeof(candidate) - sys.getsizeof(queue)
    # if total > self.limits.step_bytes:
    #   return False
    candidate = collections.deque(queue)
    candidate.append((owned, size))
    retained += size
    dropped = 0
    base = self.retained_bytes - (self._frame_bytes if kind == 'frame' else self._text_bytes)
    while (len(candidate) > count or retained > limit or
           base + retained + sys.getsizeof(candidate) - sys.getsizeof(queue) > self.limits.step_bytes):
      if len(candidate) == 1:
        if kind == 'frame':
          self._dropped_frames += 1
        else:
          self._dropped_texts += 1
        return False
      retained -= candidate.popleft()[1]
      dropped += 1
    if kind == 'frame':
      # self._frames, self._frame_bytes = candidate, retained + size
      self._frames, self._frame_bytes = candidate, retained
      self._dropped_frames += dropped
    else:
      # self._texts, self._text_bytes = candidate, retained + size
      self._texts, self._text_bytes = candidate, retained
      self._dropped_texts += dropped
    return True

  def stats(self):
    return dict(retained_bytes=self.retained_bytes, additional_frames=len(self._frames),
                additional_bytes=self._frame_bytes, debug_lines=len(self._texts),
                debug_text_bytes=self._text_bytes, dropped_frames=self._dropped_frames,
                dropped_debug_lines=self._dropped_texts)


class ObservationHistory:
  def __init__(self, limits=None, action_adapter=None):
    self.limits = limits or RecordingLimits()
    if not isinstance(self.limits, RecordingLimits):
      raise ValueError('Expected RecordingLimits')
    self._adapter = action_adapter
    self._states = collections.deque()
    self._bytes = 0
    self._lock = threading.RLock()
    self._evicted = 0

  def __len__(self):
    with self._lock:
      return len(self._states)

  def __getitem__(self, key):
    with self._lock:
      return self._states[key]

  def __iter__(self):
    with self._lock:
      return iter(tuple(self._states))

  def _evict(self):
    removed = self._states.popleft()
    self._bytes -= removed.retained_bytes
    removed._owner = None
    self._evicted += 1

  def append(self, trace, *, keep_frame=True):
    state = ObservationState(trace, limits=self.limits, action_adapter=self._adapter, keep_frame=keep_frame)
    if state.retained_bytes > self.limits.step_bytes:
      raise RecordingCapacityError('Observation including cache metadata exceeds its byte budget')
    with self._lock:
      while self._states and (len(self._states) >= self.limits.trace_steps or
                              self._bytes + state.retained_bytes > self.limits.trace_bytes):
        self._evict()
      self._states.append(state)
      self._bytes += state.retained_bytes
      state._owner = weakref.ref(self)
    return state

  def _mutate(self, state, kind, value):
    with self._lock:
      tracked = any(entry is state for entry in self._states)
      before = state.retained_bytes
      accepted = state._append(kind, value)
      if tracked:
        self._bytes += state.retained_bytes - before
        while self._bytes > self.limits.trace_bytes:
          self._evict()
      return accepted

  def clear(self):
    with self._lock:
      for state in self._states:
        state._owner = None
      self._states.clear()
      self._bytes = 0

  def stats(self):
    with self._lock:
      return dict(steps=len(self._states), retained_bytes=self._bytes, evicted_steps=self._evicted)
