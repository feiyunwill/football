"""Real concurrent admission and lifecycle with explicit closeable resources."""
import gc
import threading
import unittest
from unittest import mock
import weakref

from gfootball.engine_pool import EnginePool, EngineCapacityError, RendererBusyError
from gfootball import owned_engine
from gfootball.owned_engine import OwnedEngine, create_owned_engine
from gfootball.test_engine_pool import Resource, key


class CallableResource(Resource):
  def __init__(self, close_action=None):
    super().__init__(close_action)
    self.value = 0
    self.callback = None

  def add(self, value, *, extra=0):
    if self.callback:
      self.callback()
    self.value += value + extra
    return self.value


class OwnedEngineTest(unittest.TestCase):
  def pool(self, maximum=2, **options):
    pool = EnginePool(max_live=maximum, idle_headless=options.get('idle', 0),
                      idle_rendering=options.get('renderer', 0))
    self.addCleanup(pool.close)
    return pool

  def worker(self, action):
    errors = []
    def run():
      try:
        action()
      except BaseException as error:
        errors.append(error)
    worker = threading.Thread(target=run, name='football-engine-owned-test')
    worker.start()
    def finish():
      worker.join(3)
      self.assertFalse(worker.is_alive(), 'Owned engine worker leaked')
      if errors:
        raise errors[0]
    self.addCleanup(finish)
    return worker, finish

  def test_fresh_match_retires_matching_cached_resource_before_factory(self):
    pool = self.pool(1, idle=1)
    cached = pool.acquire(key(), CallableResource)
    resource = cached.resource
    resource.value = 42
    cached.release()
    made = []
    def factory():
      self.assertEqual(resource.closed, 1)
      result = CallableResource()
      made.append(result)
      return result
    with create_owned_engine(key(), factory, pool=pool) as fresh:
      self.assertEqual(fresh.value, 0)
      self.assertEqual(pool.stats()['live'], 1)
    self.assertEqual(made[0].closed, 1)
    self.assertEqual(pool.stats()['idle_headless'], 0)
    self.assertEqual(pool.stats()['live'], 0)

  def test_pool_and_direct_owners_share_one_capacity_and_can_reclaim_idle(self):
    pool = self.pool(2, idle=1)
    cached_owner = pool.acquire(key(), Resource)
    direct = create_owned_engine(key(), Resource, pool=pool)
    self.addCleanup(direct.close)
    factory = mock.Mock(side_effect=AssertionError('Must reject before factory'))
    with self.assertRaises(EngineCapacityError):
      create_owned_engine(key(), factory, pool=pool)
    with self.assertRaises(EngineCapacityError):
      pool.acquire(key(), factory)
    factory.assert_not_called()
    cached_owner.release()
    with create_owned_engine(key(), Resource, pool=pool):
      self.assertEqual(pool.stats()['live'], 2)
    direct.close()
    self.assertEqual(pool.stats()['live'], 0)

  def test_simultaneous_factories_consume_capacity_before_returning(self):
    pool = self.pool(3)
    proceed = threading.Event()
    self.addCleanup(proceed.set)
    entered = [threading.Event() for _ in range(3)]
    def run(index):
      def factory():
        entered[index].set()
        if not proceed.wait(3):
          raise AssertionError('Factory release deadline')
        return Resource()
      with create_owned_engine(key(), factory, pool=pool):
        pass
    workers = [self.worker(lambda index=index: run(index)) for index in range(3)]
    try:
      self.assertTrue(all(event.wait(2) for event in entered))
      self.assertEqual((pool.stats()['live'], pool.stats()['leased']), (3, 3))
      with self.assertRaises(EngineCapacityError):
        create_owned_engine(key(), lambda: self.fail('Fourth factory called'), pool=pool)
    finally:
      proceed.set()
      for _, finish in workers:
        finish()
    self.assertEqual(pool.stats()['live'], 0)

  def test_closing_resource_stays_charged_until_native_close_returns(self):
    pool = self.pool(1)
    closing, proceed = threading.Event(), threading.Event()
    def cleanup():
      closing.set()
      if not proceed.wait(3):
        raise AssertionError('Close release deadline')
    _, finish = self.worker(lambda: create_owned_engine(key(), lambda: Resource(cleanup), pool=pool).close())
    try:
      self.assertTrue(closing.wait(2))
      self.assertEqual(pool.stats()['live'], 1)
      with self.assertRaises(EngineCapacityError):
        pool.acquire(key(), Resource)
    finally:
      proceed.set()
      finish()
    self.assertEqual(pool.stats()['live'], 0)

  def test_failed_factory_refunds_admission_and_preserves_original_error(self):
    pool = self.pool(1)
    expected = ValueError('Explicit factory failure')
    def factory():
      raise expected
    with self.assertRaises(ValueError) as caught:
      create_owned_engine(key(), factory, pool=pool)
    self.assertIs(caught.exception, expected)
    self.assertEqual(pool.stats()['live'], 0)
    with create_owned_engine(key(), Resource, pool=pool):
      self.assertEqual(pool.stats()['leased'], 1)

  def test_failed_proxy_transfer_closes_already_created_resource(self):
    pool = self.pool(1)
    resource = Resource()
    failure = MemoryError('Explicit owner allocation failure')
    with mock.patch.object(owned_engine, 'OwnedEngine', side_effect=failure):
      with self.assertRaises(MemoryError) as caught:
        create_owned_engine(key(), lambda: resource, pool=pool)
    self.assertIs(caught.exception, failure)
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_pool_shutdown_during_factory_closes_candidate_before_refund(self):
    pool = self.pool(1)
    resource = Resource()
    def factory():
      pool.close()
      self.assertEqual(pool.stats()['live'], 1)
      return resource
    with self.assertRaisesRegex(RuntimeError, 'closed during creation'):
      create_owned_engine(key(), factory, pool=pool)
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_attribute_and_keyword_method_forwarding_use_the_owned_resource(self):
    pool = self.pool(1)
    resource = CallableResource()
    owner = create_owned_engine(key(), lambda: resource, pool=pool)
    owner.value = 8
    self.assertEqual(owner.add(2, extra=3), 13)
    self.assertEqual(resource.value, 13)
    owner.close()
    for operation in (lambda: owner.value, lambda: setattr(owner, 'value', 2)):
      with self.assertRaisesRegex(RuntimeError, 'closed'):
        operation()
    owner.close()
    self.assertEqual(resource.closed, 1)

  def test_retained_method_cannot_reopen_or_access_a_closed_native_resource(self):
    pool = self.pool(1)
    owner = create_owned_engine(key(), CallableResource, pool=pool)
    method = owner.add
    owner.close()
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      method(1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_foreign_thread_cannot_read_write_invoke_or_close(self):
    pool = self.pool(1)
    owner = create_owned_engine(key(), CallableResource, pool=pool)
    self.addCleanup(owner.close)
    method = owner.add
    def foreign():
      for operation in (lambda: owner.value, lambda: setattr(owner, 'value', 2), lambda: method(1), owner.close):
        with self.assertRaisesRegex(RuntimeError, 'creating thread'):
          operation()
    _, finish = self.worker(foreign)
    finish()
    self.assertEqual(owner.value, 0)
    self.assertEqual(pool.stats()['live'], 1)

  def test_reentrant_close_and_call_do_not_release_active_resource(self):
    pool = self.pool(1)
    resource = CallableResource()
    owner = create_owned_engine(key(), lambda: resource, pool=pool)
    self.addCleanup(owner.close)
    for operation in (owner.close, lambda: owner.add(1)):
      resource.callback = operation
      with self.assertRaisesRegex(RuntimeError, 'operation'):
        owner.add(1)
      self.assertEqual(resource.closed, 0)
      self.assertEqual(pool.stats()['live'], 1)
    resource.callback = None
    self.assertEqual(owner.add(2), 2)

  def test_close_failure_is_terminal_and_does_not_leak_capacity(self):
    pool = self.pool(1)
    def fail_close():
      raise OSError('Close reported error after releasing resource')
    resource = Resource(fail_close)
    owner = create_owned_engine(key(), lambda: resource, pool=pool)
    with self.assertRaises(OSError):
      owner.close()
    owner.close()
    self.assertEqual(resource.closed, 1)
    self.assertEqual(pool.stats()['live'], 0)

  def test_context_cleanup_error_does_not_replace_the_original_failure(self):
    pool = self.pool(1)
    expected = ValueError('Original match failure')
    def fail_close():
      raise OSError('Secondary cleanup failure')
    with self.assertRaises(ValueError) as caught:
      with create_owned_engine(key(), lambda: Resource(fail_close), pool=pool):
        raise expected
    self.assertIs(caught.exception, expected)
    self.assertEqual(pool.stats()['live'], 0)

  def test_abandoned_owners_and_retained_methods_release_without_cache(self):
    pool = self.pool(1)
    refs = []
    for _ in range(1000):
      resource = CallableResource()
      owner = create_owned_engine(key(), lambda: resource, pool=pool)
      refs.append(weakref.ref(resource))
      method = owner.add
      del owner
      self.assertEqual(pool.stats()['live'], 1)
      del method, resource
    gc.collect()
    self.assertEqual(pool.stats()['live'], 0)
    self.assertTrue(all(ref() is None for ref in refs))

  def test_inherited_owner_rejects_before_pool_lock(self):
    pool = self.pool(1)
    owner = create_owned_engine(key(), Resource, pool=pool)
    self.addCleanup(owner.close)
    with mock.patch.object(owned_engine.os, 'getpid', return_value=pool._pid + 1):
      for operation in (owner.close, lambda: owner.closed):
        with self.assertRaisesRegex(RuntimeError, 'fork'):
          operation()
    self.assertEqual(pool.stats()['live'], 1)

  def test_global_default_and_renderer_reservation_use_the_same_pool(self):
    pool = self.pool(2, renderer=1)
    with mock.patch.object(owned_engine, 'ENGINE_POOL', pool):
      with create_owned_engine(key(), Resource, rendering=True):
        with self.assertRaises(RendererBusyError):
          pool.acquire(key(), Resource, rendering=True)
        with create_owned_engine(key(), Resource):
          self.assertEqual(pool.stats()['live'], 2)
    self.assertEqual(pool.stats()['live'], 0)

  def test_invalid_admission_flags_fail_before_factory(self):
    pool = self.pool()
    factory = mock.Mock(side_effect=AssertionError('Invalid argument reached factory'))
    for value in (None, 0, 1, 'fresh'):
      with self.assertRaises(TypeError):
        pool.acquire(key(), factory, reuse=value)
    with self.assertRaises(TypeError):
      create_owned_engine(key(), factory, pool='invalid')
    with self.assertRaises(TypeError):
      OwnedEngine(None)
    factory.assert_not_called()
    self.assertEqual(pool.stats()['live'], 0)


if __name__ == '__main__':
  unittest.main()
