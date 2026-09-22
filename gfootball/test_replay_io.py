# 2026-09-09: real pickle/NumPy/files and timing oracles; no native substitutes.
import gc
import os
from pathlib import Path
import pickle
import sys
import tempfile
import unittest
from unittest import mock
import weakref

import numpy as np

from gfootball.recording_buffers import ObservationState, RecordingCapacityError, RecordingLimits
from gfootball.replay_io import (
    AtomicReplayFile, ReplayFormatError, ReplayLimits, ReplayReader,
    expanded_actions, export_text, first_config, load_replay, replay_timing, retained_bytes,
)
from gfootball.test_recording_buffers import Action, ADAPTER


def trace(index=0, *, config=False, steps=10, players=2):
  debug = dict(frame_cnt=index, action=[Action(index + 1, 'action%d' % index)] * players)
  if config:
    debug['config'] = dict(physics_steps_per_frame=steps, players=['agent:left_players=2'], seed=42)
  return dict(observation={'ball': np.array([index, 0, 0], np.float32), 'score': [0, 0]},
              debug=debug, reward=0.0, cumulative_reward=0.0)


class ReplayFilesTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-replay-io-test-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.path = self.directory / 'source.dump'

  def write_records(self, values, protocol=4):
    with self.path.open('wb') as stream:
      for value in values:
        pickle.dump(value, stream, protocol=protocol)
    return self.path

  def reader(self, **options):
    reader = ReplayReader(self.path, action_adapter=ADAPTER, **options)
    self.addCleanup(reader.close)
    return reader

  def assert_no_temporary_payload(self):
    self.assertEqual(list(self.directory.glob('.recording-*')), [])

  def test_limits_reject_invalid_types_and_excessive_capacities(self):
    for options in ({'records': True}, {'file_bytes': 2**40}, {'record_bytes': 0},
                    {'load_bytes': 1}, {'padding_steps': -1}, {'consumers': 23}):
      with self.assertRaises(ValueError):
        ReplayLimits(**options)
    for value in (False, 0, {}, []):
      with self.assertRaises(ValueError):
        ReplayReader(self.path, limits=value)
      with self.assertRaises(ValueError):
        ReplayReader(self.path, observation_limits=value)
      with self.assertRaises(ValueError):
        list(expanded_actions([], 10, Action(0, 'idle'), action_adapter=ADAPTER, limits=value))

  def test_real_pickle_protocols_and_numpy_values_roundtrip(self):
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
      self.write_records([trace(0, config=True), trace(1)], protocol)
      with self.reader() as reader:
        states = list(reader)
        self.assertEqual([value['frame_cnt'] for value in states], [0, 1])
        self.assertEqual(first_config(states[0])['seed'], 42)
        np.testing.assert_array_equal(states[1]['ball'], [1, 0, 0])
        self.assertFalse(reader.stats()['open'])
        self.assertTrue(reader.stats()['ended'])

  def test_empty_file_eof_and_explicit_close_are_distinct(self):
    self.write_records([])
    reader = self.reader()
    self.assertEqual(list(reader), [])
    self.assertEqual(list(reader), [])
    self.assertFalse(reader.stats()['open'])
    reader.reset()
    self.assertTrue(reader.stats()['open'])
    self.assertEqual(list(reader), [])
    reader.close()
    with self.assertRaises(RuntimeError):
      next(reader)
    with self.assertRaises(RuntimeError):
      reader.reset()

  def test_truncated_last_record_and_invalid_trailer_never_silently_succeed(self):
    good = pickle.dumps(trace(0, config=True), protocol=4)
    last = pickle.dumps(trace(1), protocol=4)
    for suffix in (last[:-1], last[:len(last)//2], b'not a pickle'):
      self.path.write_bytes(good + suffix)
      reader = self.reader()
      self.assertEqual(next(reader)['frame_cnt'], 0)
      with self.assertRaises(ReplayFormatError):
        next(reader)
      self.assertFalse(reader.stats()['open'])
      self.assertTrue(reader.stats()['closed'])

  def test_file_limit_rejects_before_unpickling(self):
    self.path.write_bytes(b'x' * 1024)
    with mock.patch('gfootball.replay_io.pickle.load', side_effect=AssertionError('unexpected decode')) as load:
      with self.assertRaises(RecordingCapacityError):
        self.reader(limits=ReplayLimits(file_bytes=128))
      load.assert_not_called()

  def test_serialized_record_limit_and_record_count_close_stream(self):
    self.write_records([trace(0, config=True), trace(1)])
    reader = self.reader(limits=ReplayLimits(record_bytes=64))
    with self.assertRaises(RecordingCapacityError):
      next(reader)
    self.assertFalse(reader.stats()['open'])
    reader = self.reader(limits=ReplayLimits(records=1))
    self.assertEqual(next(reader)['frame_cnt'], 0)
    with self.assertRaises(RecordingCapacityError):
      next(reader)
    self.assertEqual(reader.stats()['records'], 1)
    self.assertFalse(reader.stats()['open'])

  def test_decoded_structure_and_debug_limits_apply_before_retention(self):
    for value in ({'wrong': True}, dict(observation={}, debug={'object': object()}),
                  dict(observation={}, debug={'large': 'x' * 1024})):
      self.write_records([value])
      reader = self.reader(observation_limits=RecordingLimits(debug_bytes=128))
      with self.assertRaises(ValueError):
        next(reader)
      self.assertEqual(reader.stats()['records'], 0)
      self.assertFalse(reader.stats()['open'])

  def test_input_append_and_reset_replacement_are_detected(self):
    self.write_records([trace(0, config=True), trace(1)])
    reader = self.reader()
    next(reader)
    with self.path.open('ab') as stream:
      stream.write(b'extra')
    with self.assertRaises(ReplayFormatError):
      next(reader)
    self.write_records([trace(0, config=True)])
    reader = self.reader()
    self.assertEqual(len(list(reader)), 1)
    self.write_records([trace(1, config=True), trace(2)])
    with self.assertRaises(ReplayFormatError):
      reader.reset()
    self.assertFalse(reader.stats()['open'])

  def test_reset_reopens_the_same_file_and_replays_from_first_action(self):
    self.write_records([trace(0, config=True), trace(1)])
    reader = self.reader()
    self.assertEqual([state['frame_cnt'] for state in reader], [0, 1])
    reader.reset()
    self.assertEqual([state['frame_cnt'] for state in reader], [0, 1])
    self.assertEqual(reader.stats()['file_opens'], 2)

  def test_stream_does_not_retain_old_observations_across_one_thousand_steps(self):
    self.write_records(trace(index, config=index == 0) for index in range(1000))
    reader = self.reader()
    first = next(reader)
    reference = weakref.ref(first)
    del first
    gc.collect()
    self.assertIsNone(reference())
    for index, state in enumerate(reader, 1):
      self.assertEqual(state['frame_cnt'], index)
    self.assertEqual(reader.stats()['records'], 1000)
    self.assertLess(reader.stats()['peak_step_bytes'], 16 * 1024)
    self.assertFalse(reader.stats()['open'])

  def test_compatibility_load_preserves_mutable_arrays_and_bounds_list_bytes(self):
    self.write_records([trace(index, config=index == 0) for index in range(8)])
    records = load_replay(self.path, action_adapter=ADAPTER)
    records[0]['observation']['ball'][0] = 999
    records[0]['debug']['action'][0]._name = 'caller modified'
    again = load_replay(self.path, action_adapter=ADAPTER)
    self.assertEqual(again[0]['observation']['ball'][0], 0)
    self.assertEqual(again[0]['debug']['action'][0]._name, 'action0')
    self.assertGreater(sum(retained_bytes(record, ADAPTER) for record in again), 2048)
    with self.assertRaises(RecordingCapacityError):
      load_replay(self.path, action_adapter=ADAPTER, limits=ReplayLimits(load_bytes=2048))
    # The source is closed after capacity failure, including on Windows.
    self.path.rename(self.directory / 'renamed.dump')

  def test_atomic_file_pickle_commit_replaces_target_only_after_success(self):
    target = self.directory / 'target.dump'
    target.write_bytes(b'original')
    output = AtomicReplayFile(target, 4096)
    self.addCleanup(output.abort)
    output.dump(trace(0, config=True))
    self.assertEqual(target.read_bytes(), b'original')
    result = output.commit()
    self.assertEqual(output.commit(), result)
    with target.open('rb') as stream:
      self.assertEqual(pickle.load(stream)['debug']['frame_cnt'], 0)
    output.abort()
    self.assertTrue(target.exists())
    self.assert_no_temporary_payload()

  def test_atomic_capacity_and_write_failure_preserve_previous_output(self):
    target = self.directory / 'target.txt'
    target.write_bytes(b'preserve')
    output = AtomicReplayFile(target, 128)
    self.addCleanup(output.abort)
    with self.assertRaises(RecordingCapacityError):
      output.write(b'x' * 129)
    self.assertEqual(target.read_bytes(), b'preserve')
    self.assertEqual(output.budget.stats()['active_dumps'], 0)
    self.assert_no_temporary_payload()
    output = AtomicReplayFile(target, 128)
    self.addCleanup(output.abort)
    with mock.patch.object(output._writer.stream, 'write', side_effect=OSError('disk full')):
      with self.assertRaisesRegex(OSError, 'disk full'):
        output.write(b'partial')
    self.assertEqual(target.read_bytes(), b'preserve')
    self.assert_no_temporary_payload()

  def test_atomic_publication_failure_preserves_target_and_releases_lease(self):
    target = self.directory / 'target.txt'
    target.write_bytes(b'preserve')
    with mock.patch('gfootball.replay_io.os.replace', side_effect=OSError('replace failed')):
      with self.assertRaisesRegex(OSError, 'replace failed'):
        with AtomicReplayFile(target, 128) as output:
          output.write(b'new')
    self.assertEqual(target.read_bytes(), b'preserve')
    self.assertEqual(output.budget.stats()['active_dumps'], 0)
    self.assert_no_temporary_payload()

  def test_text_export_streams_and_does_not_change_input_or_global_numpy_options(self):
    self.write_records([trace(0, config=True), trace(1)])
    original = self.path.read_bytes()
    target = self.directory / 'view.txt'
    formatter = lambda value: 'UNEXPECTED GLOBAL FORMATTER'
    with np.printoptions(threshold=sys.maxsize, formatter={'all': formatter}):
      export_text(self.path, target, False, action_adapter=ADAPTER)
      self.assertIs(np.get_printoptions()['formatter']['all'], formatter)
    text = target.read_text(encoding='utf-8')
    self.assertNotIn('debug', text)
    self.assertNotIn('UNEXPECTED', text)
    self.assertIn('array(shape=(3,)', text)
    self.assertIn('cumulative_reward', text)
    self.assertEqual(self.path.read_bytes(), original)
    export_text(self.path, target, True, action_adapter=ADAPTER)
    self.assertIn('action0', target.read_text(encoding='utf-8'))
    self.assert_no_temporary_payload()

  def test_text_conversion_failure_and_same_file_alias_preserve_inputs(self):
    self.write_records([trace(0, config=True)])
    original = self.path.read_bytes()
    target = self.directory / 'view.txt'
    target.write_bytes(b'old report')
    with self.assertRaises(RecordingCapacityError):
      export_text(self.path, target, action_adapter=ADAPTER, limits=ReplayLimits(text_bytes=128))
    self.assertEqual(target.read_bytes(), b'old report')
    alias = self.directory / 'alias.dump'
    os.link(self.path, alias)
    with self.assertRaises(ValueError):
      export_text(self.path, alias, action_adapter=ADAPTER)
    self.assertEqual(alias.read_bytes(), original)
    self.path.write_bytes(original + b'invalid trailer')
    with self.assertRaises(ReplayFormatError):
      export_text(self.path, target, action_adapter=ADAPTER)
    self.assertEqual(target.read_bytes(), b'old report')
    self.assert_no_temporary_payload()


class ReplayTimingTest(unittest.TestCase):
  def states(self, steps=20, count=3):
    return [ObservationState(trace(index, config=index == 0, steps=steps), action_adapter=ADAPTER)
            for index in range(count)]

  def test_tick_rate_conversion_preserves_every_original_action_boundary(self):
    for old, fps, expected in ((20, 10, (10, 2)), (10, 20, (5, 2)),
                               (10, 10, (10, 1)), (4, 50, (2, 2)), (100, 1, (100, 1))):
      self.assertEqual(replay_timing(old, fps), expected)
    for old, fps in ((20, 60), (20, 1), (7, 10), (10, True), (True, 10), (0, 10), (10, 0)):
      with self.assertRaises(ValueError):
        replay_timing(old, fps)

  def test_expansion_uses_private_action_only_records_and_keeps_first_configuration(self):
    states = self.states()
    result = list(expanded_actions(states, 10, Action(0, 'idle'), action_adapter=ADAPTER,
                                   limits=ReplayLimits(padding_steps=2)))
    self.assertEqual(len(result), 8)
    self.assertEqual([value['debug']['frame_cnt'] for value in result], list(range(8)))
    self.assertEqual([value['debug']['action'][0]._name for value in result],
                     ['action0', 'idle', 'action1', 'idle', 'action2', 'idle', 'idle', 'idle'])
    self.assertTrue(all(value['observation'] == {} for value in result))
    self.assertEqual(result[0]['debug']['config']['physics_steps_per_frame'], 10)
    self.assertTrue(all('config' not in value['debug'] for value in result[1:]))
    self.assertEqual(first_config(states[0])['physics_steps_per_frame'], 20)
    result[0]['debug']['action'][0]._name = 'changed'
    self.assertEqual(states[0]['action'][0].name, 'action0')

  def test_output_record_limit_includes_intermediate_and_padding_steps(self):
    with self.assertRaises(RecordingCapacityError):
      list(expanded_actions(self.states(count=2), 10, Action(0, 'idle'), action_adapter=ADAPTER,
                            limits=ReplayLimits(output_records=4, padding_steps=1)))
    result = list(expanded_actions(self.states(count=2), 10, Action(0, 'idle'), action_adapter=ADAPTER,
                                   limits=ReplayLimits(output_records=5, padding_steps=1)))
    self.assertEqual(len(result), 5)

  def test_empty_nonzero_origin_missing_config_and_changing_action_counts_reject(self):
    bad = trace(1, config=True)
    missing = trace(0)
    changes = [trace(0, config=True), trace(1, players=1)]
    for values in ([], [bad], [missing], changes):
      states = [ObservationState(value, action_adapter=ADAPTER) for value in values]
      with self.assertRaises(ReplayFormatError):
        list(expanded_actions(states, 10, Action(0, 'idle'), action_adapter=ADAPTER))

  def test_ai_only_expansion_and_invalid_frame_sequences(self):
    first = trace(0, config=True, players=0)
    first['debug']['config']['players'] = []
    result = list(expanded_actions([ObservationState(first, action_adapter=ADAPTER)], 20,
                                   Action(0, 'idle'), action_adapter=ADAPTER,
                                   limits=ReplayLimits(padding_steps=0)))
    self.assertEqual([record['debug']['action'] for record in result], [[], []])
    for invalid in (True, False, 0.0, -1, 0, 2):
      values = [trace(0, config=True), trace(1)]
      values[1]['debug']['frame_cnt'] = invalid
      with self.assertRaises(ReplayFormatError):
        list(expanded_actions([ObservationState(value, action_adapter=ADAPTER) for value in values],
                              10, Action(0, 'idle'), action_adapter=ADAPTER))


if __name__ == '__main__':
  unittest.main()
