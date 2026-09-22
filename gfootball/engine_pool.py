"""Bounded ownership of reusable engines, independent of native imports.

Factories transfer a new resource to the pool only on success. Resource.close()
must release its native allocations even if it reports an error. GameEnv.close
is noexcept. Counts include factories and resources still being closed; they
are not byte/RSS measurements. A lease does not serialize use of its resource.
"""
import atexit
from dataclasses import dataclass
import os
import threading


class EngineCapacityError(RuntimeError):
  """No engine reservation is available; no factory has been called."""


class RendererBusyError(EngineCapacityError):
  """Another lease or cleanup owns the process renderer."""


@dataclass(frozen=True)
class EngineKey:
  width: int
  height: int
  startup: tuple

  def __post_init__(self):
    for value in (self.width, self.height):
      if type(value) is not int or not 1 <= value <= 8192:
        raise ValueError('Render dimensions must be integers in [1, 8192]')
    if self.width * self.height > 16777216:
      raise ValueError('Render resolution exceeds 16777216 pixels')
    if (type(self.startup) is not tuple or len(self.startup) != 6 or
        any(type(value) is not str or len(value) > 4096 for value in self.startup)):
      raise ValueError('Engine startup identity requires six bounded strings')

  @classmethod
  def current(cls, width, height):
    return cls(width, height, (os.getcwd(),) + tuple(os.environ.get(name, '') for name in (
        'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT', 'DISPLAY', 'SDL_VIDEODRIVER', 'EGL_PLATFORM')))


class EngineLease:
  __slots__ = ('_pool', '_resource', '_key', '_rendering', '_thread', '__weakref__')

  def __init__(self, pool, resource, key, rendering, thread):
    self._pool, self._resource = pool, resource
    self._key, self._rendering, self._thread = key, rendering, thread

  @property
  def resource(self):
    self._pool._check_process()
    if self._resource is None:
      raise RuntimeError('Engine lease is closed')
    return self._resource

  @property
  def key(self):
    return self._key

  @property
  def rendering(self):
    return self._rendering

  def release(self, reusable=True):
    self._pool._release(self, reusable)

  def __del__(self):
    # GC is an abort, never evidence of a reusable engine. Partial construction
    # and interpreter teardown must not generate secondary unraisable errors.
    try:
      self.release(reusable=False)
    except BaseException:
      pass


class EnginePool:
  """At most max_live engines and two independently bounded idle lists.

  The process renderer remains reserved through creation and native close.
  Reuse requires the same Thread object, not an OS thread id that can recur.
  Use fresh processes with spawn; an inherited pool rejects calls before locks.
  """
  def __init__(self, max_live=32, idle_headless=2, idle_rendering=1):
    for name, value, upper in (('max_live', max_live, 256),
                               ('idle_headless', idle_headless, 32),
                               ('idle_rendering', idle_rendering, 1)):
      lower = 1 if name == 'max_live' else 0
      if type(value) is not int or not lower <= value <= upper:
        raise ValueError('%s must be in [%d, %d]' % (name, lower, upper))
    if idle_headless + idle_rendering > max_live:
      raise ValueError('Idle capacities exceed the total engine limit')
    self._pid = os.getpid()
    self._lock = threading.RLock()
    self._maximum, self._limits = max_live, (idle_headless, idle_rendering)
    self._idle = ([], [])
    self._live = self._leased = 0
    self._renderer = False
    self._closed = False

  def _check_process(self):
    if os.getpid() != self._pid:
      raise RuntimeError('Engine ownership cannot cross fork; create environments with spawn')

  def stats(self):
    self._check_process()
    with self._lock:
      return dict(live=self._live, leased=self._leased, idle_headless=len(self._idle[0]),
                  idle_rendering=len(self._idle[1]), renderer_reserved=self._renderer,
                  max_live=self._maximum, closed=self._closed)

  # 2026-09-10: direct match owners share admission but must get a fresh engine.
  # def acquire(self, key, factory, rendering=False):
  def acquire(self, key, factory, rendering=False, *, reuse=True):
    self._check_process()
    # 2026-09-10: refuse ambiguous fresh/reuse admission flags.
    # if type(key) is not EngineKey or type(rendering) is not bool or not callable(factory):
    if type(key) is not EngineKey or type(rendering) is not bool or type(reuse) is not bool or not callable(factory):
      raise TypeError('Expected EngineKey, callable factory and boolean rendering')
    thread = threading.current_thread()
    victim = None
    with self._lock:
      if self._closed:
        raise RuntimeError('Engine pool is closed')
      if rendering and self._renderer:
        raise RendererBusyError('Only one rendering environment may be active in this process')
      idle = self._idle[int(rendering)]
      for index in range(len(idle) - 1, -1, -1):
        resource, old_key, owner = idle[index]
        # 2026-09-10: a match cannot inherit a cached Core simulation.
        # if old_key == key and owner is thread:
        if reuse and old_key == key and owner is thread:
          # Construct before detaching so even a Python allocation failure keeps ownership.
          lease = EngineLease(self, resource, key, rendering, thread)
          idle.pop(index)
          self._leased += 1
          if rendering:
            self._renderer = True
          return lease
      # Retire an incompatible cached engine before allocating its replacement.
      if idle:
        victim = idle.pop(0)[0]
      elif self._live >= self._maximum:
        raise EngineCapacityError('Maximum live engine count reached')
      else:
        self._live += 1
      self._leased += 1
      if rendering:
        self._renderer = True
    resource = None
    try:
      if victim is not None:
        victim.close()
        victim = None
      resource = factory()
      if resource is None or not callable(getattr(resource, 'close', None)):
        raise TypeError('Engine factory must return an owned closeable resource')
      with self._lock:
        if self._closed:
          raise RuntimeError('Engine pool closed during creation')
        lease = EngineLease(self, resource, key, rendering, thread)
        resource = None
        return lease
    except BaseException as failure:
      try:
        if resource is not None and callable(getattr(resource, 'close', None)):
          resource.close()
      except BaseException as cleanup:
        if hasattr(failure, 'add_note'):
          failure.add_note('Engine cleanup also failed: %s' % cleanup)
      finally:
        with self._lock:
          self._live -= 1
          self._leased -= 1
          if rendering:
            self._renderer = False
      raise

  def _release(self, lease, reusable):
    self._check_process()
    if type(reusable) is not bool:
      raise TypeError('reusable must be boolean')
    with self._lock:
      resource = lease._resource
      if resource is None:
        return
      idle = self._idle[int(lease.rendering)]
      cache = (reusable and not self._closed and lease._thread is threading.current_thread()
               and len(idle) < self._limits[int(lease.rendering)])
      if cache:
        idle.append((resource, lease.key, lease._thread))
      lease._resource = None
      if cache:
        self._leased -= 1
        if lease.rendering:
          self._renderer = False
        return
    try:
      resource.close()
    finally:
      with self._lock:
        self._leased -= 1
        self._live -= 1
        if lease.rendering:
          self._renderer = False

  def clear_idle(self, close=False):
    """Drain idle resources; active leases retain ownership until release."""
    self._check_process()
    with self._lock:
      if close:
        self._closed = True
      pending = [(entry[0], False) for entry in self._idle[0]]
      pending += [(entry[0], True) for entry in self._idle[1]]
      self._idle[0].clear()
      self._idle[1].clear()
      if any(rendering for _, rendering in pending):
        self._renderer = True
    first = None
    for resource, rendering in pending:
      try:
        resource.close()
      except BaseException as error:
        if first is None:
          first = error
      finally:
        with self._lock:
          self._live -= 1
          if rendering:
            self._renderer = False
    if first is not None:
      raise first

  def close(self):
    self.clear_idle(close=True)


ENGINE_POOL = EnginePool()
atexit.register(ENGINE_POOL.close)
