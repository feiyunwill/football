"""Real concurrent ownership tests with explicit closeable resource oracles.

These resources are deliberately not GameEnv; no native imports are replaced.
"""
import gc
import os
import threading
import unittest
from unittest import mock
import weakref

from gfootball.engine_pool import EnginePool, EngineKey, EngineCapacityError, RendererBusyError


class Resource:
  def __init__(self, close_action=None):
    self.closed = 0
    self.close_action = close_action

  def close(self):
    self.closed += 1
    if self.close_action:
      self.close_action()


def key(width=64, height=48, data=''):
  return EngineKey(width, height, ('cwd', data, '', '', '', ''))


class EnginePoolTest(unittest.TestCase):
  def pool(self, **kwargs):
    pool = EnginePool(**kwargs)
    self.addCleanup(pool.close)
    return pool

  def worker(self, callback):
    errors = []
    def run():
      try:
        callback()
      except BaseException as error:
        errors.append(error)
    thread = threading.Thread(target=run, name='football-engine-pool-test', daemon=False)
    thread.start()
    def finish():
      thread.join(3)
      self.assertFalse(thread.is_alive(), 'Owned worker did not terminate')
      if errors:
        raise errors[0]
    self.addCleanup(finish)
    return thread, finish

  def test_idle_retention_and_live_limit(self):
    pool = self.pool(max_live=4, idle_headless=2)
    leases = [pool.acquire(key(), Resource) for _ in range(4)]
    resources = [lease.resource for lease in leases]
    factory = mock.Mock(side_effect=AssertionError('Capacity must precede factory'))
    with self.assertRaises(EngineCapacityError):
      pool.acquire(key(), factory)
    factory.assert_not_called()
    for lease in leases:
      lease.release()
    self.assertEqual(pool.stats()['live'], 2)
    self.assertEqual(pool.stats()['idle_headless'], 2)
    self.assertEqual([resource.closed for resource in resources], [0, 0, 1, 1])
    pool.clear_idle()
    self.assertEqual([resource.closed for resource in resources], [1, 1, 1, 1])
    self.assertEqual(pool.stats()['live'], 0)

  def test_same_key_and_thread_reuses_resource(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource)
    resource = lease.resource
    lease.release()
    second = pool.acquire(key(), lambda: self.fail('Unexpected allocation'))
    self.assertIs(second.resource, resource)
    second.release(False)
    self.assertEqual(resource.closed, 1)

  def test_resolution_and_startup_mismatch_close_before_allocation(self):
    pool = self.pool()
    for changed in (key(80, 60), key(data='other-resources')):
      old = pool.acquire(key(), Resource)
      resource = old.resource
      old.release()
      def factory():
        self.assertEqual(resource.closed, 1)
        return Resource()
      new = pool.acquire(changed, factory)
      self.assertIsNot(new.resource, resource)
      new.release(False)

  def test_rendering_and_headless_resources_never_mix(self):
    pool = self.pool()
    first = pool.acquire(key(), Resource)
    old = first.resource
    first.release()
    renderer = pool.acquire(key(), Resource, rendering=True)
    self.assertIsNot(renderer.resource, old)
    renderer.release()
    again = pool.acquire(key(), Resource)
    self.assertIs(again.resource, old)
    again.release(False)

  def test_only_one_renderer_and_repeated_release(self):
    pool = self.pool()
    renderer = pool.acquire(key(), Resource, rendering=True)
    resource = renderer.resource
    with self.assertRaises(RendererBusyError):
      pool.acquire(key(), lambda: self.fail('Busy renderer allocated'), rendering=True)
    renderer.release(False)
    renderer.release(False)
    self.assertEqual(resource.closed, 1)
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      renderer.resource
    self.assertFalse(pool.stats()['renderer_reserved'])

  def test_failed_factory_refunds_renderer_and_total_reservation(self):
    pool = self.pool()
    failure = ValueError('factory failed before ownership transfer')
    for rendering in (False, True):
      with self.assertRaises(ValueError) as raised:
        pool.acquire(key(), mock.Mock(side_effect=failure), rendering=rendering)
      self.assertIs(raised.exception, failure)
      self.assertEqual(pool.stats()['live'], 0)
      self.assertFalse(pool.stats()['renderer_reserved'])
    lease = pool.acquire(key(), Resource, rendering=True)
    lease.release(False)

  def test_failed_victim_close_refunds_without_calling_factory(self):
    pool = self.pool()
    def fail():
      raise OSError('terminal close error')
    lease = pool.acquire(key(), lambda: Resource(fail))
    resource = lease.resource
    lease.release()
    with self.assertRaises(OSError):
      pool.acquire(key(80), lambda: self.fail('Factory called after failed close'))
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_shutdown_creation_preserves_failure_if_close_also_reports_error(self):
    pool = self.pool()
    def fail_close():
      raise OSError('terminal resource cleanup error')
    resource = Resource(fail_close)
    def factory():
      pool.close()
      return resource
    with self.assertRaisesRegex(RuntimeError, 'closed during creation'):
      pool.acquire(key(), factory, rendering=True)
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)
    self.assertFalse(pool.stats()['renderer_reserved'])

  def test_clear_attempts_every_close_even_when_one_reports_error(self):
    pool = self.pool()
    def fail():
      raise OSError('terminal close error')
    first = pool.acquire(key(), lambda: Resource(fail))
    second = pool.acquire(key(), Resource, rendering=True)
    resources = first.resource, second.resource
    first.release()
    second.release()
    with self.assertRaises(OSError):
      pool.clear_idle()
    self.assertEqual([resource.closed for resource in resources], [1, 1])
    self.assertEqual(pool.stats()['live'], 0)
    self.assertFalse(pool.stats()['renderer_reserved'])

  def test_cache_never_reuses_another_thread_resource(self):
    pool = self.pool()
    first = pool.acquire(key(), Resource)
    original = first.resource
    first.release()
    def run():
      second = pool.acquire(key(), Resource)
      self.assertIsNot(second.resource, original)
      self.assertEqual(original.closed, 1)
      second.release(False)
    _, finish = self.worker(run)
    finish()

  def test_cross_thread_release_closes_instead_of_caching(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource, rendering=True)
    resource = lease.resource
    _, finish = self.worker(lease.release)
    finish()
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)
    self.assertFalse(pool.stats()['renderer_reserved'])

  def test_concurrent_release_closes_exactly_once(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource)
    resource = lease.resource
    barrier = threading.Barrier(9)
    def run():
      barrier.wait(3)
      lease.release(False)
    workers = [self.worker(run) for _ in range(8)]
    barrier.wait(3)
    for _, finish in workers:
      finish()
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_capacity_includes_inflight_factory_and_close_during_factory(self):
    pool = self.pool(max_live=1, idle_headless=0, idle_rendering=0)
    entered, proceed = threading.Event(), threading.Event()
    self.addCleanup(proceed.set)
    resource = Resource()
    def factory():
      entered.set()
      if not proceed.wait(3):
        raise TimeoutError('Factory release deadline')
      return resource
    def run():
      with self.assertRaisesRegex(RuntimeError, 'closed during creation'):
        pool.acquire(key(), factory, rendering=True)
    _, finish = self.worker(run)
    self.assertTrue(entered.wait(3))
    self.assertEqual(pool.stats()['live'], 1)
    with self.assertRaises(EngineCapacityError):
      pool.acquire(key(), Resource)
    with self.assertRaises(RendererBusyError):
      pool.acquire(key(), Resource, rendering=True)
    pool.close()
    self.assertEqual(resource.closed, 0)
    proceed.set()
    finish()
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_capacity_and_renderer_remain_reserved_during_native_close(self):
    pool = self.pool(max_live=1, idle_headless=0, idle_rendering=0)
    entered, proceed = threading.Event(), threading.Event()
    self.addCleanup(proceed.set)
    def close_action():
      entered.set()
      if not proceed.wait(3):
        raise TimeoutError('Close release deadline')
    lease = pool.acquire(key(), lambda: Resource(close_action), rendering=True)
    _, finish = self.worker(lambda: lease.release(False))
    self.assertTrue(entered.wait(3))
    self.assertEqual(pool.stats()['live'], 1)
    with self.assertRaises(RendererBusyError):
      pool.acquire(key(), Resource, rendering=True)
    with self.assertRaises(EngineCapacityError):
      pool.acquire(key(), Resource)
    proceed.set()
    finish()
    self.assertEqual(pool.stats()['live'], 0)

  def test_clear_keeps_renderer_reserved_until_close_finishes(self):
    pool = self.pool()
    entered, proceed = threading.Event(), threading.Event()
    self.addCleanup(proceed.set)
    def close_action():
      entered.set()
      if not proceed.wait(3):
        raise TimeoutError('Close release deadline')
    lease = pool.acquire(key(), lambda: Resource(close_action), rendering=True)
    lease.release()
    _, finish = self.worker(pool.clear_idle)
    self.assertTrue(entered.wait(3))
    with self.assertRaises(RendererBusyError):
      pool.acquire(key(), Resource, rendering=True)
    proceed.set()
    finish()
    self.assertFalse(pool.stats()['renderer_reserved'])

  def test_closed_pool_leaves_borrowed_resources_until_return(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource)
    resource = lease.resource
    pool.close()
    self.assertEqual(resource.closed, 0)
    self.assertIs(lease.resource, resource)
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      pool.acquire(key(), Resource)
    lease.release()
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)
    pool.close()

  def test_abandoned_lease_discards_and_releases_python_references(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource)
    resource = lease.resource
    reference = weakref.ref(lease)
    del lease
    gc.collect()
    self.assertIsNone(reference())
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_many_unique_keys_have_constant_retained_count(self):
    pool = self.pool()
    references = []
    for index in range(1000):
      lease = pool.acquire(key(data=str(index)), Resource)
      references.append(weakref.ref(lease.resource))
      lease.release()
      self.assertEqual(pool.stats()['live'], 1)
    pool.clear_idle()
    gc.collect()
    self.assertTrue(all(reference() is None for reference in references))
    self.assertEqual(pool.stats()['live'], 0)

  def test_32_concurrent_borrowers_and_overload(self):
    pool = self.pool()
    entered = threading.Barrier(33)
    proceed = threading.Event()
    self.addCleanup(proceed.set)
    def run():
      lease = pool.acquire(key(), Resource)
      try:
        entered.wait(3)
        if not proceed.wait(3):
          raise TimeoutError('Borrower release deadline')
      finally:
        lease.release(False)
    workers = [self.worker(run) for _ in range(32)]
    entered.wait(3)
    self.assertEqual(pool.stats()['live'], 32)
    with self.assertRaises(EngineCapacityError):
      pool.acquire(key(), Resource)
    proceed.set()
    for _, finish in workers:
      finish()
    self.assertEqual(pool.stats()['live'], 0)

  def test_pid_rejection_precedes_any_inherited_lock_access(self):
    pool = self.pool()
    lease = pool.acquire(key(), Resource)
    old_pid = os.getpid()
    # This checks the guard only; it is not a POSIX/native fork test.
    with mock.patch('gfootball.engine_pool.os.getpid', return_value=old_pid + 1):
      for operation in (pool.stats, pool.close, lease.release,
                        lambda: lease.resource, lambda: pool.acquire(key(), Resource)):
        with self.assertRaisesRegex(RuntimeError, 'fork'):
          operation()
    lease.release(False)

  def test_validation_does_not_call_factory(self):
    for values in (dict(max_live=0), dict(max_live=True), dict(idle_headless=33),
                   dict(idle_rendering=2), dict(max_live=1)):
      with self.assertRaises(ValueError):
        EnginePool(**values)
    for values in ((0, 1), (True, 1), (8193, 1), (8192, 8192)):
      with self.assertRaises(ValueError):
        key(*values)
    with self.assertRaises(ValueError):
      key(data='x' * 4097)
    with self.assertRaises(ValueError):
      EngineKey(64, 48, [''] * 6)
    pool = self.pool()
    for bad in (None, ('width', 'height'), object()):
      with self.assertRaises(TypeError):
        pool.acquire(bad, lambda: self.fail('Invalid key allocated'))
    with self.assertRaises(TypeError):
      pool.acquire(key(), Resource, rendering=1)
    with self.assertRaises(TypeError):
      pool.acquire(key(), lambda: None)
    self.assertEqual(pool.stats()['live'], 0)


if __name__ == '__main__':
  unittest.main()
