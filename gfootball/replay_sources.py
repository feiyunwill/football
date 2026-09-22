# 2026-09-09: one replay decode per common input frame, scoped to one environment.
"""Bounded shared action cursors; consumers advance/reset as one frame group."""
import os
from pathlib import Path
import sys
import threading

from gfootball.recording_buffers import ActionAdapter, RecordedAction, RecordingCapacityError, RecordingLimits
from gfootball.replay_io import (
    ReplayExhausted, ReplayFormatError, ReplayLimits, ReplayReader, first_config, retained_bytes,
)


class ReplayCursor:
  def __init__(self, source, token):
    self._source, self._token = source, token
    self._closed = False

  def take(self):
    if self._closed:
      raise RuntimeError('Replay cursor is closed')
    return self._source.take(self._token)

  def reset(self):
    if self._closed:
      raise RuntimeError('Replay cursor is closed')
    self._source.reset(self._token)

  def close(self):
    if not self._closed:
      self._source.release(self._token)
      self._closed = True

  def __del__(self):
    if hasattr(self, '_closed'):
      try:
        self.close()
      except BaseException:
        pass


class ReplayActionSource:
  def __init__(self, pool, key):
    self.pool, self.key = pool, key
    self._reader = None
    self._closed = False
    self._config = None
    self._actions = ()
    self._index = 0
    self._consumers = {}
    self._reset_pending = None
    self._ended = False
    self.layout = None
    self._config_bytes = 0
    try:
      self._reader = ReplayReader(key, limits=pool.limits, observation_limits=pool.observation_limits,
                                  action_adapter=pool.adapter)
      try:
        state = next(self._reader)
      except StopIteration as error:
        raise ReplayFormatError('Replay input is empty') from error
      self._actions = self._validate_actions(state)
      config = first_config(state)
      self.layout = pool.layout_resolver(config)
      if (type(self.layout) is not tuple or len(self.layout) != 2
          or any(type(value) is not int or not 0 <= value <= 11 for value in self.layout)
          or sum(self.layout) != len(self._actions)):
        raise ReplayFormatError('Recorded player layout does not match the action vector')
      # Keep only immutable config/actions. Large observation arrays are released.
      self._config = state._trace['debug']['config']
      self._config_bytes = retained_bytes(self._config, pool.adapter)
      pool._check_capacity(self, self.retained_bytes)
    except BaseException:
      self.close()
      raise

  def _require_open(self):
    self.pool._check_process()
    if self._closed:
      raise RuntimeError('Replay action source is closed')

  def _validate_actions(self, state):
    actions = state._trace['debug'].get('action')
    if (not isinstance(actions, tuple) or len(actions) > 22
        or any(type(action) is not RecordedAction and (type(action) is not int or not 0 <= action <= 65535)
               for action in actions)):
      raise ReplayFormatError('Invalid replay action vector')
    if self.layout is not None and len(actions) != sum(self.layout):
      raise ReplayFormatError('Replay action count changed within the file')
    return actions

  @property
  def retained_bytes(self):
    # Reserve the maximum current reset set before starting a reset, including
    # its actual set capacity rather than charging a smaller tuple snapshot.
    reset_size = sys.getsizeof(set(self._consumers)) + sum(sys.getsizeof(token) for token in self._consumers)
    return (sys.getsizeof(self) + sys.getsizeof(self.key) + self._config_bytes
            + retained_bytes(self._actions) + retained_bytes(self._consumers)
            # 2026-09-09: reset metadata is precharged while consumers register.
            # + (retained_bytes(tuple(self._reset_pending)) if self._reset_pending is not None else 0))
            + reset_size)

  def subscribe(self, indices):
    with self.pool._lock:
      self._require_open()
      if (type(indices) not in (tuple, list) or len(indices) > 22
          or any(type(index) is not int or not 0 <= index < sum(self.layout) for index in indices)
          or len(set(indices)) != len(indices)):
        raise ValueError('Invalid replay action indices')
      if self._index or self._ended or any(position for _, position in self._consumers.values()):
        raise RuntimeError('Replay players must register before input consumption starts')
      if sum(len(source._consumers) for source in self.pool._sources.values()) >= self.pool.limits.consumers:
        raise RecordingCapacityError('Replay consumer count exceeded')
      token = object()
      self._consumers[token] = (tuple(indices), 0)
      try:
        self.pool._check_capacity(self, self.retained_bytes)
        return ReplayCursor(self, token)
      except BaseException:
        self._consumers.pop(token, None)
        raise

  def _advance(self, position):
    try:
      state = next(self._reader)
    except StopIteration:
      self._ended = True
      self._actions = ()
      raise ReplayExhausted('Replay input is exhausted')
    candidate = self._validate_actions(state)
    size = self.retained_bytes - retained_bytes(self._actions) + retained_bytes(candidate)
    self.pool._check_capacity(self, size)
    self._actions = candidate
    self._index = position

  def take(self, token):
    with self.pool._lock:
      self._require_open()
      if token not in self._consumers:
        raise RuntimeError('Replay cursor is not registered')
      if self._reset_pending is not None:
        if self._reset_pending:
          raise RuntimeError('All replay players must reset before consuming new input')
        self._rewind()
      if self._ended:
        raise ReplayExhausted('Replay input is exhausted')
      indices, position = self._consumers[token]
      if position == self._index + 1:
        if any(other < position for _, other in self._consumers.values()):
          raise RuntimeError('All replay players must consume the current frame before advancing')
      elif position != self._index:
        raise RuntimeError('Replay cursor is outside the current frame')
      try:
        if position != self._index:
          self._advance(position)
        result = [self.pool.adapter.thaw(self._actions[index])
                  if type(self._actions[index]) is RecordedAction else self._actions[index] for index in indices]
        self._consumers[token] = (indices, position + 1)
        return result
      except ReplayExhausted:
        raise
      except BaseException:
        self.close()
        raise

  def _rewind(self):
    try:
      self._reader.reset()
      state = next(self._reader)
      candidate = self._validate_actions(state)
      size = self.retained_bytes - retained_bytes(self._actions) + retained_bytes(candidate)
      self.pool._check_capacity(self, size)
      self._actions = candidate
      self._index = 0
      self._ended = False
      self._reset_pending = None
    except BaseException:
      self.close()
      raise

  def reset(self, token):
    with self.pool._lock:
      self._require_open()
      if token not in self._consumers:
        raise RuntimeError('Replay cursor is not registered')
      if self._reset_pending is None:
        if not self._ended and self._index == 0 and not any(value[1] for value in self._consumers.values()):
          return
        self._reset_pending = set(self._consumers)
      indices, _ = self._consumers[token]
      self._consumers[token] = (indices, 0)
      self._reset_pending.discard(token)
      if not self._reset_pending:
        self._rewind()

  def release(self, token):
    with self.pool._lock:
      self.pool._check_process()
      self._consumers.pop(token, None)
      if self._reset_pending is not None:
        self._reset_pending.discard(token)
      if not self._consumers:
        self.close()

  def close(self):
    with self.pool._lock:
      try:
        if self._reader is not None:
          self._reader.close()
      finally:
        self._closed = True
        self._actions = ()
        self._config = None
        self._config_bytes = 0
        self._consumers.clear()
        self._reset_pending = None
        if self.pool._sources.get(self.key) is self:
          del self.pool._sources[self.key]

  def stats(self):
    with self.pool._lock:
      return dict(layout=self.layout, consumers=len(self._consumers), index=self._index,
                  retained_bytes=self.retained_bytes, ended=self._ended, closed=self._closed,
                  reader=self._reader.stats() if self._reader is not None else None)


class ReplaySourcePool:
  """One explicit environment owner; never a global shared gameplay timeline."""
  def __init__(self, action_adapter, layout_resolver, *, limits=None, observation_limits=None):
    if not isinstance(action_adapter, ActionAdapter) or not callable(layout_resolver):
      raise ValueError('Replay sources require an action adapter and layout resolver')
    self.adapter, self.layout_resolver = action_adapter, layout_resolver
    # 2026-09-09: explicit false/empty policies must not silently use defaults.
    # self.limits = limits or ReplayLimits()
    # self.observation_limits = observation_limits or RecordingLimits()
    self.limits = ReplayLimits() if limits is None else limits
    self.observation_limits = RecordingLimits() if observation_limits is None else observation_limits
    if not isinstance(self.limits, ReplayLimits) or not isinstance(self.observation_limits, RecordingLimits):
      raise ValueError('Expected replay and observation limits')
    self._sources = {}
    self._lock = threading.RLock()
    self._closed = False
    self._pid = os.getpid()

  def _check_process(self):
    if self._pid != os.getpid():
      raise RuntimeError('Replay source pool cannot be used after fork')

  def _check_capacity(self, source, candidate):
    total = sys.getsizeof(self._sources) + candidate + sum(
        item.retained_bytes for item in self._sources.values() if item is not source)
    if total > self.limits.source_bytes:
      raise RecordingCapacityError('Replay source cache byte budget exceeded')

  def source(self, path):
    self._check_process()
    path = os.fspath(path)
    if type(path) is not str or len(path) > 4096:
      raise ValueError('Replay source path exceeds its length budget')
    key = str(Path(path).resolve())
    with self._lock:
      if self._closed:
        raise RuntimeError('Replay source pool is closed')
      if key in self._sources:
        return self._sources[key]
      if len(self._sources) >= self.limits.sources:
        raise RecordingCapacityError('Replay source count exceeded')
      source = ReplayActionSource(self, key)
      try:
        self._sources[key] = source
        self._check_capacity(source, source.retained_bytes)
        return source
      except BaseException:
        source.close()
        raise

  def close(self):
    with self._lock:
      first = None
      for source in tuple(self._sources.values()):
        try:
          source.close()
        except BaseException as error:
          first = first or error
      self._sources.clear()
      self._closed = True
      if first is not None:
        raise first

  def stats(self):
    with self._lock:
      return dict(sources=len(self._sources), consumers=sum(len(source._consumers) for source in self._sources.values()),
                  retained_bytes=sys.getsizeof(self._sources) + sum(source.retained_bytes for source in self._sources.values()),
                  closed=self._closed)

  def __del__(self):
    if hasattr(self, '_lock'):
      try:
        self.close()
      except BaseException:
        pass
