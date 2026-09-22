# 2026-09-10: public recording/collection/cursor contracts and actual thread races.
from dataclasses import replace
import gc
import threading
import unittest
from unittest import mock
import weakref

from gfootball.frame_sync.replay import (
    Replay, ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFormatError,
    ReplayFrame, ReplayLimits, ReplayManager,
)


def policy(**updates):
  return replace(ReplayLimits(frames=8, events=8, replay_bytes=65536, total_bytes=262144), **updates)


def replay(**options):
  return Replay('r0', 'm0', 'Home', 'Away', **options)


class ReplayStoreTest(unittest.TestCase):
  def test_direct_active_handle_uses_the_collection_byte_budget_and_oldest_eviction(self):
    frame = ReplayFrame(0, inputs={'p0': {'direction': [1, 0]}})
    sample = replay(limits=policy())
    base = sample.retained_bytes
    sample.add_frame(frame)
    full = sample.retained_bytes
    limits = policy(replay_bytes=full, total_bytes=2 * full + base, replays=3)
    manager = ReplayManager(limits=limits)
    self.addCleanup(manager.close)
    saved = []
    for index in range(2):
      active = manager.start_recording('r%d' % index, 'm0', 'Home', 'Away')
      active.add_frame(frame)
      saved.append(manager.stop_recording())
    active = manager.start_recording('r2', 'm0', 'Home', 'Away')
    active.add_frame(frame)
    info = manager.get_storage_info()
    self.assertEqual(info['evicted_replays'], 1)
    self.assertIsNone(manager.get_replay('r0'))
    self.assertIs(manager.get_replay('r1'), saved[1])
    self.assertEqual(info['retained_bytes'], saved[1].retained_bytes + active.retained_bytes)
    self.assertLessEqual(info['peak_bytes'], limits.total_bytes)
    with self.assertRaises(RuntimeError): saved[0].add_frame(ReplayFrame(1))
    before = manager.get_storage_info()
    with self.assertRaises(ReplayCapacityError): active.add_frame(ReplayFrame(1))
    self.assertEqual(manager.get_storage_info(), before)
    self.assertEqual(len(active.frames), 1)

  def test_count_eviction_and_duplicate_rejection_preserve_existing_replays(self):
    manager = ReplayManager(limits=policy(replays=2))
    self.addCleanup(manager.close)
    for name in ('r1', 'r2'):
      manager.start_recording(name, 'm0', 'Home', 'Away')
      manager.stop_recording()
    before = manager.get_storage_info()
    with self.assertRaises(ReplayFormatError): manager.start_recording('r2', 'm0', 'Home', 'Away')
    self.assertEqual(manager.get_storage_info(), before)
    self.assertEqual([item.replay_id for item in manager.get_latest_replays()], ['r2', 'r1'])
    manager.start_recording('r3', 'm0', 'Home', 'Away')
    self.assertIsNone(manager.get_replay('r1'))
    self.assertEqual(manager.get_storage_info()['evicted_replays'], 1)

  def test_invalid_replacement_does_not_stop_the_active_recording(self):
    manager = ReplayManager(limits=policy())
    self.addCleanup(manager.close)
    current = manager.start_recording('r0', 'm0', 'Home', 'Away')
    with self.assertRaises(ReplayFormatError): manager.start_recording('r1', 'm0', '', 'Away')
    self.assertTrue(manager.is_recording())
    self.assertFalse(current.is_sealed)
    self.assertTrue(manager.record_frame(ReplayFrame(0)))
    other = manager.start_recording('r1', 'm0', 'Home', 'Away')
    self.assertTrue(current.is_sealed)
    self.assertIs(manager.get_replay('r0'), current)
    self.assertFalse(other.is_sealed)

  def test_failed_active_capacity_admission_is_atomic(self):
    manager = ReplayManager(limits=policy(replays=1))
    self.addCleanup(manager.close)
    current = manager.start_recording('r0', 'm0', 'Home', 'Away')
    before = manager.get_storage_info()
    with self.assertRaises(ReplayCapacityError): manager.start_recording('r1', 'm0', 'Home', 'Away')
    self.assertEqual(manager.get_storage_info(), before)
    self.assertFalse(current.is_sealed)
    self.assertEqual(manager.list_replays(), [])

  def test_frames_and_events_have_separate_count_caps_and_read_only_views(self):
    value = replay(limits=policy(frames=2, events=1))
    first, second = ReplayFrame(10), ReplayFrame(11)
    value.add_frame(first); value.add_frame(second)
    with self.assertRaises(ReplayCapacityError): value.add_frame(ReplayFrame(12))
    value.add_event(ReplayEvent(ReplayEventType.GOAL, 1000, 11))
    with self.assertRaises(ReplayCapacityError): value.add_event(ReplayEvent(ReplayEventType.FOUL, 1000, 11))
    self.assertEqual(value.frames[:], (first, second))
    with self.assertRaises(AttributeError): value.frames.append(first)
    with self.assertRaises(TypeError): value.frames[0] = second
    with self.assertRaises(AttributeError): value.frames = []
    with self.assertRaises(AttributeError): value.replay_id = 'changed'

  def test_frame_continuity_event_order_and_duration_are_consistent(self):
    value = replay(limits=policy(), tick_hz=20)
    value.add_frame(ReplayFrame(50)); value.add_frame(ReplayFrame(51))
    self.assertEqual(value.duration_ms, 100)
    with self.assertRaises(ReplayFormatError): value.add_frame(ReplayFrame(53))
    with self.assertRaises(ReplayFormatError): value.add_frame(ReplayFrame(51))
    value.add_event(ReplayEvent(ReplayEventType.GOAL, 500, 51))
    self.assertEqual(value.get_duration_seconds(), .5)
    with self.assertRaises(ReplayFormatError): value.add_event(ReplayEvent(ReplayEventType.FOUL, 400, 51))
    with self.assertRaises(ReplayFormatError): value.add_event(ReplayEvent(ReplayEventType.FOUL, 600, 50))
    with self.assertRaises(ReplayFormatError): value.duration_ms = 499
    self.assertEqual(value.duration_ms, 500)

  def test_score_updates_validate_both_values_before_mutation(self):
    value = replay(limits=policy())
    value.set_score(2, 1)
    for bad in (-1, True, 1000):
      with self.assertRaises(ReplayFormatError): value.set_score(9, bad)
      self.assertEqual((value.score_home, value.score_away), (2, 1))
    value.seal()
    with self.assertRaises(RuntimeError): value.score_home = 3
    with self.assertRaises(RuntimeError): value.duration_ms = 1000
    self.assertEqual(value.to_dict()['score'], '2-1')

  def test_cursor_seeks_exact_frames_and_eof_is_repeatable(self):
    value = replay(limits=policy(), frames=[ReplayFrame(i) for i in range(5, 8)])
    with self.assertRaises(ReplayFormatError): value.cursor()
    value.seal()
    a, b = value.cursor(), value.cursor()
    self.assertEqual(next(a).frame_id, 5)
    a.seek(7)
    self.assertEqual(next(a).frame_id, 7)
    for _ in range(2):
      with self.assertRaises(StopIteration): next(a)
    self.assertEqual(next(b).frame_id, 5)
    a.rewind()
    with self.assertRaises(ReplayFormatError): a.seek(100)
    self.assertEqual(next(a).frame_id, 5)
    self.assertIs(value.get_frame(7), value.frames[2])
    self.assertIsNone(value.get_frame(4))

  def test_empty_cursor_and_false_like_limits_are_explicit(self):
    value = replay(limits=policy()).seal()
    self.assertEqual(list(value.cursor()), [])
    value.cursor().seek(0)
    for invalid in (False, {}, 0):
      with self.assertRaises(ValueError): replay(limits=invalid)
      with self.assertRaises(ValueError): ReplayManager(limits=invalid)
    with self.assertRaises(ReplayCapacityError): replay(limits=policy(), frames=(ReplayFrame(0) for _ in range(20)))

  def test_cursor_source_and_maximum_frame_eof_stay_valid(self):
    from gfootball.frame_sync.replay_data import MAX_FRAME
    value = replay(limits=policy(), frames=[ReplayFrame(MAX_FRAME)]).seal()
    cursor = value.cursor()
    with self.assertRaises(AttributeError): cursor.replay = replay(limits=policy())
    cursor.seek(MAX_FRAME + 1)
    with self.assertRaises(StopIteration): next(cursor)
    cursor.rewind()
    self.assertEqual(next(cursor).frame_id, MAX_FRAME)

  def test_shared_cursor_consumes_each_frame_once_across_threads(self):
    # 2026-09-10: cursor concurrency must fit its independently bounded fixture.
    # value = replay(limits=policy(frames=1000), frames=[ReplayFrame(i) for i in range(1000)]).seal()
    value = replay(limits=policy(frames=1000, replay_bytes=1024**2, total_bytes=2 * 1024**2),
                   frames=[ReplayFrame(i) for i in range(1000)]).seal()
    cursor = value.cursor()
    observed, errors = [], []
    def consume():
      try:
        for row in cursor: observed.append(row.frame_id)
      except BaseException as error:
        errors.append(error)
    threads = [threading.Thread(target=consume, name='frame-replay-cursor-%d' % i) for i in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(5)
    self.assertFalse(any(thread.is_alive() for thread in threads))
    self.assertEqual(errors, [])
    self.assertEqual(sorted(observed), list(range(1000)))

  def test_abort_delete_and_close_refund_only_manager_ownership(self):
    manager = ReplayManager(limits=policy())
    active = manager.start_recording('r0', 'm0', 'Home', 'Away')
    active.add_frame(ReplayFrame(0))
    manager.abort_recording()
    self.assertTrue(active.is_sealed)
    self.assertEqual(manager.get_storage_info()['retained_bytes'], 0)
    self.assertEqual(len(active.frames), 1)
    manager.start_recording('r1', 'm0', 'Home', 'Away')
    saved = manager.stop_recording()
    self.assertTrue(manager.delete_replay('r1'))
    self.assertFalse(manager.delete_replay('r1'))
    self.assertTrue(saved.is_sealed)
    unfinished = manager.start_recording('r2', 'm0', 'Home', 'Away')
    manager.close(); manager.close()
    self.assertTrue(unfinished.is_sealed)
    self.assertEqual(manager.get_storage_info()['retained_bytes'], 0)
    with self.assertRaises(RuntimeError): manager.record_frame(ReplayFrame(0))

  def test_manager_collection_and_deleted_replay_are_reclaimed(self):
    manager = ReplayManager(limits=policy())
    retained = manager.start_recording('r0', 'm0', 'Home', 'Away')
    owner = weakref.ref(manager)
    del manager
    gc.collect()
    self.assertIsNone(owner())
    self.assertTrue(retained.is_sealed)
    manager = ReplayManager(limits=policy())
    row = manager.start_recording('r1', 'm0', 'Home', 'Away')
    ref = weakref.ref(row)
    manager.stop_recording(); manager.delete_replay('r1')
    del row
    gc.collect()
    self.assertIsNone(ref())
    manager.close()

  def test_initial_lists_and_iteration_do_not_alias_or_snapshot_every_frame(self):
    rows = [ReplayFrame(0)]
    value = replay(limits=policy(), frames=rows)
    rows.append(ReplayFrame(1))
    self.assertEqual(len(value.frames), 1)
    iterator = iter(value.frames)
    self.assertEqual(next(iterator).frame_id, 0)
    value.add_frame(rows[1])
    self.assertEqual(list(iterator), [])
    self.assertEqual([frame.frame_id for frame in value.frames], [0, 1])

  def test_concurrent_event_producers_share_the_same_admission_boundary(self):
    manager = ReplayManager(limits=policy(frames=1, events=128, replay_bytes=256 * 1024, total_bytes=256 * 1024))
    self.addCleanup(manager.close)
    active = manager.start_recording('r0', 'm0', 'Home', 'Away')
    barrier = threading.Barrier(8)
    accepted, rejected, errors = [], [], []
    def produce(index):
      try:
        barrier.wait(3)
        for _ in range(20):
          try:
            active.add_event(ReplayEvent(ReplayEventType.GOAL, 0, 0, details={'producer': index}))
            accepted.append(index)
          except ReplayCapacityError:
            rejected.append(index)
      except BaseException as error:
        errors.append(error)
    threads = [threading.Thread(target=produce, args=(i,), name='frame-replay-producer-%d' % i) for i in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(5)
    self.assertFalse(any(thread.is_alive() for thread in threads))
    self.assertEqual(errors, [])
    self.assertEqual((len(accepted), len(rejected), len(active.events)), (128, 32, 128))
    self.assertEqual(manager.get_storage_info()['retained_bytes'], active.retained_bytes)

  def test_default_maximum_frame_count_is_accepted_then_rejected_without_growth(self):
    value = replay(limits=ReplayLimits())
    for frame_id in range(100000): value.add_frame(ReplayFrame(frame_id))
    before = value.stats()
    self.assertEqual(before['frames'], 100000)
    self.assertLessEqual(before['retained_bytes'], value.limits.replay_bytes)
    with self.assertRaises(ReplayCapacityError): value.add_frame(ReplayFrame(100000))
    self.assertEqual(value.stats(), before)
    self.assertEqual(value.frames[-1].frame_id, 99999)


if __name__ == '__main__': unittest.main()
