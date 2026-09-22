"""Fresh engine ownership through the same admission budget as cached Core engines.

The public native binding is unchanged. This adapter owns one fresh pool lease,
forwards operations on its creating thread, and never caches a finished match.
"""
import functools
import os
import threading

from gfootball.engine_pool import ENGINE_POOL, EngineLease, EnginePool


class OwnedEngine:
  __slots__ = ('_lease', '_owner', '_pid', '_active', '__weakref__')

  def __init__(self, lease):
    if type(lease) is not EngineLease:
      raise TypeError('Expected a fresh engine lease')
    object.__setattr__(self, '_lease', lease)
    object.__setattr__(self, '_owner', threading.current_thread())
    object.__setattr__(self, '_pid', os.getpid())
    object.__setattr__(self, '_active', False)

  def _check_owner(self):
    # Check before touching inherited resource/pool locks.
    if os.getpid() != self._pid:
      raise RuntimeError('Engine ownership cannot cross fork; use spawn')
    if threading.current_thread() is not self._owner:
      raise RuntimeError('Engine operations belong to the creating thread')

  def _resource(self):
    self._check_owner()
    if self._lease is None:
      raise RuntimeError('Owned engine is closed')
    if self._active:
      raise RuntimeError('Reentrant engine operation')
    return self._lease.resource

  def __getattr__(self, name):
    value = getattr(self._resource(), name)
    if callable(value):
      # Do not return a native bound method: a caller retaining it must still
      # encounter the owner/closed checks at invocation time.
      return functools.partial(self._invoke, name)
    return value

  def __setattr__(self, name, value):
    if name in self.__slots__:
      object.__setattr__(self, name, value)
    else:
      setattr(self._resource(), name, value)

  def _invoke(self, name, *args, **kwargs):
    resource = self._resource()
    self._active = True
    try:
      return getattr(resource, name)(*args, **kwargs)
    finally:
      self._active = False

  def close(self):
    self._check_owner()
    if self._active:
      raise RuntimeError('Cannot close an engine during its operation')
    lease = self._lease
    if lease is None:
      return
    self._lease = None
    lease.release(reusable=False)

  def __enter__(self):
    self._resource()
    return self

  def __exit__(self, kind, value, traceback):
    try:
      self.close()
    except BaseException:
      if value is None:
        raise
      if hasattr(value, 'add_note'):
        value.add_note('Engine cleanup also failed; the original error is preserved.')


def create_owned_engine(key, factory, *, rendering=False, pool=None):
  """Reserve before construction; never reuse or cache a match simulation.

  Factories clean up partial construction if they raise before transferring a
  resource. As for EnginePool, resource.close must release native allocations
  even if it reports an error; the actual GameEnv close is noexcept.
  """
  selected = ENGINE_POOL if pool is None else pool
  if not isinstance(selected, EnginePool):
    raise TypeError('Expected EnginePool')
  lease = selected.acquire(key, factory, rendering=rendering, reuse=False)
  try:
    return OwnedEngine(lease)
  except BaseException as error:
    try:
      lease.release(reusable=False)
    except BaseException:
      if hasattr(error, 'add_note'):
        error.add_note('Engine cleanup also failed during ownership transfer.')
    raise
