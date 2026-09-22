# 2026-09-09: shared action readers with real on-disk traces and observable cursors.
import gc
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest import mock
import weakref

import numpy as np

from gfootball.recording_buffers import RecordingCapacityError
from gfootball.replay_io import ReplayExhausted, ReplayFormatError, ReplayLimits, ReplayReader
from gfootball.replay_sources import ReplaySourcePool
from gfootball.test_recording_buffers import Action, ADAPTER
from gfootball.test_replay_io import trace


def layout(config):
  return tuple(config['layout'])


class ReplaySourceTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-replay-source-test-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.path = self.directory / 'source.dump'

  def write(self, count=3, teams=(1, 1), *, path=None, big_first=False, large_names=False):
    target = path or self.path
    with target.open('wb') as stream:
      for frame in range(count):
        row = trace(frame, config=frame == 0, players=sum(teams))
        if frame == 0:
          row['debug']['config']['layout'] = teams
        if big_first and frame == 0:
          row['observation']['features'] = np.zeros(256 * 1024, np.uint8)
        row['debug']['action'] = [Action(player * 1000 + frame, 'x' * 128 if large_names and frame else 'p%d_f%d' % (player, frame))
                                   for player in range(sum(teams))]
        pickle.dump(row, stream, protocol=4)

  def pool(self, **limits):
    pool = ReplaySourcePool(ADAPTER, layout, limits=ReplayLimits(**limits))
    self.addCleanup(pool.close)
    return pool

  def cursor(self, source, indices):
    cursor = source.subscribe(indices)
    self.addCleanup(cursor.close)
    return cursor

  def test_same_file_alias_is_one_source_and_decode_per_frame(self):
    self.write(5)
    pool = self.pool()
    source = pool.source(self.path)
    self.assertIs(pool.source(self.directory / 'unused' / '..' / self.path.name), source)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    for frame in range(5):
      self.assertEqual(a.take()[0]._name, 'p0_f%d' % frame)
      self.assertEqual(b.take()[0]._name, 'p1_f%d' % frame)
      self.assertEqual(source.stats()['reader']['records'], frame + 1)
    with self.assertRaises(ReplayExhausted):
      a.take()
    self.assertFalse(source.stats()['reader']['open'])
    self.assertEqual(pool.stats()['sources'], 1)

  def test_22_consumers_share_300_decodes_and_no_observation_retention(self):
    self.write(300, (11, 11), big_first=True)
    references = []
    original = ReplayReader.__next__

    def observed(reader):
      state = original(reader)
      references.append(weakref.ref(state))
      return state

    pool = self.pool()
    with mock.patch.object(ReplayReader, '__next__', observed):
      source = pool.source(self.path)
      cursors = [self.cursor(source, [player]) for player in range(22)]
      for frame in range(300):
        for player, cursor in enumerate(cursors):
          self.assertEqual(cursor.take()[0]._backend_action, player * 1000 + frame)
        self.assertEqual(source.stats()['reader']['records'], frame + 1)
        self.assertLess(pool.stats()['retained_bytes'], 64 * 1024)
    gc.collect()
    self.assertEqual(len(references), 300)
    self.assertTrue(all(reference() is None for reference in references))
    self.assertEqual(source.stats()['reader']['file_opens'], 1)

  def test_consumer_cannot_advance_over_a_slower_player_and_can_retry(self):
    self.write()
    source = self.pool().source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    self.assertEqual(a.take()[0]._name, 'p0_f0')
    with self.assertRaisesRegex(RuntimeError, 'current frame'):
      a.take()
    self.assertEqual(source.stats()['reader']['records'], 1)
    self.assertEqual(b.take()[0]._name, 'p1_f0')
    self.assertEqual(a.take()[0]._name, 'p0_f1')

  def test_all_players_reset_together_and_replay_restarts_after_eof(self):
    self.write(2)
    source = self.pool().source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    for _ in range(2):
      a.take()
      b.take()
    with self.assertRaises(ReplayExhausted):
      b.take()
    a.reset()
    with self.assertRaisesRegex(RuntimeError, 'must reset'):
      a.take()
    b.reset()
    self.assertEqual(a.take()[0]._name, 'p0_f0')
    self.assertEqual(b.take()[0]._name, 'p1_f0')
    self.assertEqual(source.stats()['reader']['file_opens'], 2)

  def test_reset_is_valid_before_first_step_without_reopening_or_advancing(self):
    self.write()
    source = self.pool().source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    a.reset()
    b.reset()
    self.assertEqual(source.stats()['reader']['records'], 1)
    self.assertEqual(source.stats()['reader']['file_opens'], 1)
    self.assertEqual(a.take()[0]._name, 'p0_f0')

  def test_closed_slow_consumer_no_longer_blocks_live_consumer(self):
    self.write()
    pool = self.pool()
    source = pool.source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    a.take()
    b.close()
    self.assertEqual(a.take()[0]._name, 'p0_f1')
    a.close()
    self.assertEqual(pool.stats()['sources'], 0)
    self.assertEqual(pool.stats()['consumers'], 0)
    self.assertFalse(source.stats()['reader']['open'])
    with self.assertRaises(RuntimeError):
      a.take()

  def test_closing_last_pending_reset_consumer_allows_remaining_group_to_rewind(self):
    self.write()
    source = self.pool().source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    a.take()
    b.take()
    a.reset()
    b.close()
    self.assertEqual(a.take()[0]._name, 'p0_f0')

  def test_sources_consumers_indices_and_late_registration_are_bounded(self):
    for value in (False, 0, {}, []):
      with self.assertRaises(ValueError):
        ReplaySourcePool(ADAPTER, layout, limits=value)
      with self.assertRaises(ValueError):
        ReplaySourcePool(ADAPTER, layout, observation_limits=value)
    self.write()
    other = self.directory / 'second.dump'
    self.write(path=other)
    pool = self.pool(sources=1, consumers=2)
    source = pool.source(self.path)
    with self.assertRaises(RecordingCapacityError):
      pool.source(other)
    for indices in ([True], [-1], [2], [0, 0], list(range(23))):
      with self.assertRaises(ValueError):
        source.subscribe(indices)
    a, b = self.cursor(source, [0]), self.cursor(source, [1])
    with self.assertRaises(RecordingCapacityError):
      source.subscribe([0])
    a.take()
    with self.assertRaises(RuntimeError):
      source.subscribe([0])

  def test_cache_growth_refuses_new_action_row_and_closes_the_source(self):
    self.write(2, (11, 11), large_names=True)
    baseline_pool = self.pool()
    baseline = baseline_pool.source(self.path)
    self.cursor(baseline, list(range(22)))
    maximum = baseline_pool.stats()['retained_bytes'] + 512
    baseline_pool.close()
    pool = self.pool(source_bytes=maximum)
    source = pool.source(self.path)
    cursor = self.cursor(source, list(range(22)))
    cursor.take()
    with self.assertRaises(RecordingCapacityError):
      cursor.take()
    self.assertTrue(source.stats()['closed'])
    self.assertFalse(source.stats()['reader']['open'])
    self.assertEqual(pool.stats()['sources'], 0)

  def test_empty_and_invalid_layout_sources_close_files_without_retaining_cache(self):
    self.path.write_bytes(b'')
    pool = self.pool()
    with self.assertRaises(ReplayFormatError):
      pool.source(self.path)
    self.assertEqual(pool.stats()['sources'], 0)
    self.write()
    bad = ReplaySourcePool(ADAPTER, lambda config: (11, 11))
    self.addCleanup(bad.close)
    with self.assertRaises(ReplayFormatError):
      bad.source(self.path)
    self.assertEqual(bad.stats()['sources'], 0)
    self.path.rename(self.directory / 'renamed.dump')

  def test_corrupted_later_action_vector_is_terminal_and_cannot_return_old_actions(self):
    self.write(1)
    with self.path.open('ab') as stream:
      pickle.dump(trace(1, players=1), stream, protocol=4)
    source = self.pool().source(self.path)
    cursor = self.cursor(source, [0, 1])
    cursor.take()
    with self.assertRaises(ReplayFormatError):
      cursor.take()
    with self.assertRaises(RuntimeError):
      cursor.take()
    self.assertFalse(source.stats()['reader']['open'])

  def test_native_like_actions_are_independent_values_for_each_consumer(self):
    self.write()
    source = self.pool().source(self.path)
    a, b = self.cursor(source, [0]), self.cursor(source, [0])
    first = a.take()[0]
    first._name = 'caller mutation'
    second = b.take()[0]
    self.assertEqual(second._name, 'p0_f0')
    self.assertIsNot(first, second)

  def test_pool_close_closes_every_source_and_rejects_new_playback(self):
    self.write()
    other = self.directory / 'other.dump'
    self.write(path=other)
    pool = self.pool()
    a, b = pool.source(self.path), pool.source(other)
    cursor = self.cursor(a, [0])
    pool.close()
    pool.close()
    self.assertFalse(a.stats()['reader']['open'] or b.stats()['reader']['open'])
    with self.assertRaises(RuntimeError):
      pool.source(self.path)
    with self.assertRaises(RuntimeError):
      cursor.take()

  def test_ai_only_recorded_action_rows_can_be_consumed_and_exhausted(self):
    self.write(2, (0, 0))
    source = self.pool().source(self.path)
    cursor = self.cursor(source, [])
    self.assertEqual(cursor.take(), [])
    self.assertEqual(cursor.take(), [])
    with self.assertRaises(ReplayExhausted):
      cursor.take()


if __name__ == '__main__':
  unittest.main()
