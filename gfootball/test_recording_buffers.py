# 2026-09-09: actual NumPy ownership and bounded recording contracts, no GameEnv.
import gc
import pickle
import sys
import unittest
import weakref
import warnings

import numpy as np

from gfootball.recording_buffers import (
    ActionAdapter, ObservationHistory, ObservationState, RecordedAction,
    RecordingCapacityError, RecordingLimits, validate_dump_name,
)


def trace(frame=0, image=None, debug=None):
  observation = dict(ball=np.array([frame / 100, 0, 0], dtype=np.float32),
                     left_team=np.zeros((11, 2), np.float32), score=[0, 0])
  if image is not None:
    observation['frame'] = image
  return dict(observation=observation, debug=debug or {}, reward=0.0, cumulative_reward=0.0)


class Action:
  def __init__(self, backend, name, sticky=False, directional=False):
    self._backend_action = backend
    self._name = name
    self._sticky = sticky
    self._directional = directional


ADAPTER = ActionAdapter(Action, lambda value: Action(*value))


class RecordingOwnershipTest(unittest.TestCase):
  def test_limits_reject_invalid_counts_sizes_and_trace_smaller_than_one_step(self):
    for name, value in (('trace_steps', 0), ('trace_steps', True), ('trace_bytes', 2**40),
                        ('additional_frames', 65), ('debug_lines', -1), ('depth', 0),
                        ('dump_names', 3), ('nodes', 32769), ('string_bytes', 1)):
      with self.subTest(name=name), self.assertRaises(ValueError):
        RecordingLimits(**{name: value})
    with self.assertRaises(ValueError):
      RecordingLimits(trace_bytes=4096, step_bytes=8192)

  def test_freeze_preserves_input_and_detaches_nested_mutable_data(self):
    original = trace(debug={'nested': {'list': [1, 2], 'tuple': (3, 4)}})
    state = ObservationState(original)
    original['observation']['ball'][0] = 999
    original['debug']['nested']['list'].append(9)
    original['observation']['score'][0] = 7
    self.assertEqual(float(state['ball'][0]), 0)
    self.assertEqual(tuple(state['nested']['list']), (1, 2))
    self.assertEqual(tuple(state['score']), (0, 0))
    with self.assertRaises(TypeError):
      state._trace['reward'] = 1
    with self.assertRaises(TypeError):
      state['debug']['nested']['new'] = 1
    with self.assertRaises(ValueError):
      state['ball'][0] = 1
    with self.assertRaises(ValueError):
      state['ball'].setflags(write=True)
    restored = state.to_record()
    self.assertIsInstance(restored['debug']['nested']['list'], list)
    self.assertIsInstance(restored['debug']['nested']['tuple'], tuple)
    restored['debug']['nested']['list'].append(8)
    self.assertEqual(tuple(state['nested']['list']), (1, 2))

  def test_tiny_view_does_not_retain_large_base_or_dtype_metadata(self):
    large = np.arange(1024 * 1024, dtype=np.int64)
    reference = weakref.ref(large)
    small = large[::400000]
    payload = trace(debug={'small': small})
    state = ObservationState(payload)
    del payload, small, large
    gc.collect()
    self.assertIsNone(reference())
    self.assertIsInstance(state['small'].base, bytes)
    np.testing.assert_array_equal(state['small'], np.array([0, 400000, 800000], dtype=np.int64))
    self.assertLess(state.retained_bytes, 8192)
    dtype = np.dtype('float64', metadata={'external': b'x' * (1024 * 1024)})
    array = np.ones(3, dtype=dtype)
    state = ObservationState(trace(debug={'array': array}))
    self.assertIsNone(state['array'].dtype.metadata)
    self.assertLess(state.retained_bytes, 8192)

  def test_noncontiguous_arrays_and_scalar_types_keep_values(self):
    array = np.arange(48, dtype=np.float32).reshape(6, 8)[:, ::-2]
    state = ObservationState(trace(debug={'array': array, 'int': np.int64(4),
                                          'bool': np.bool_(True), 'zero_d': np.array(2.5)}))
    np.testing.assert_array_equal(state['array'], array)
    self.assertTrue(state['array'].flags.c_contiguous)
    self.assertFalse(state['array'].flags.owndata)
    self.assertIsInstance(state['array'].base, bytes)
    self.assertEqual(state['int'], 4)
    self.assertIs(state['bool'], True)
    self.assertEqual(state['zero_d'].shape, ())
    self.assertEqual(float(state['zero_d']), 2.5)

  def test_array_metadata_and_outgoing_dump_views_cannot_change_owned_shape(self):
    state = ObservationState(trace(image=np.zeros((8, 8, 3), np.uint8)))
    frame = state['frame']
    with self.assertRaises(AttributeError):
      frame.shape = (192,)
    with self.assertRaises(AttributeError):
      frame.dtype = np.float32
    outgoing = state.to_record()['observation']['frame']
    self.assertIs(type(outgoing), np.ndarray)
    # 2026-09-09: intentionally exercise mutable outgoing metadata on old/new
    # NumPy. Version 2.5 deprecates this setter; no unrelated warning is ignored.
    # outgoing.shape = (192,)
    with warnings.catch_warnings(record=True) as messages:
      warnings.simplefilter('always')
      outgoing.shape = (192,)
    self.assertTrue(all(issubclass(message.category, DeprecationWarning) for message in messages))
    self.assertEqual(state['frame'].shape, (8, 8, 3))
    with self.assertRaises(ValueError):
      outgoing.setflags(write=True)
    loaded = pickle.loads(pickle.dumps(state.to_record()))
    self.assertIs(type(loaded['observation']['frame']), np.ndarray)
    self.assertEqual(loaded['observation']['frame'].shape, (8, 8, 3))
    # The existing OpenCV video path must accept these real readonly inputs.
    import cv2
    resized = cv2.resize(frame[..., ::-1], (4, 4), interpolation=cv2.INTER_AREA)
    self.assertEqual(resized.shape, (4, 4, 3))
    self.assertTrue(resized.flags.writeable)

  def test_large_broadcast_object_dtype_unknown_objects_and_cycles_reject(self):
    broadcast = np.broadcast_to(np.array(1.0), (1000000,))
    for value in (broadcast, np.array([object()], dtype=object), object(), {'self': None}):
      if isinstance(value, dict):
        value['self'] = value
      with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
        ObservationState(trace(debug={'bad': value}))

  def test_debug_node_depth_integer_and_string_budgets(self):
    for debug, limits in (({'many': list(range(100))}, RecordingLimits(nodes=32)),
                           ({'nested': [[[[1]]]]}, RecordingLimits(depth=3)),
                           ({'text': 'x' * 1000}, RecordingLimits(string_bytes=64)),
                           ({'array': np.zeros(1000)}, RecordingLimits(debug_bytes=1024)),
                           ({'number': 2**100}, RecordingLimits())):
      with self.assertRaises(RecordingCapacityError):
        ObservationState(trace(debug=debug), limits=limits)

  def test_disabled_video_omits_only_owned_frame_without_changing_input(self):
    image = np.zeros((8, 8, 3), np.uint8)
    original = trace(image=image)
    before = original['observation']
    state = ObservationState(original, keep_frame=False)
    self.assertIs(original['observation'], before)
    self.assertIs(original['observation']['frame'], image)
    self.assertNotIn('frame', state['observation'])
    self.assertIn('ball', state['observation'])

  def test_frame_shape_dtype_and_byte_limits_are_checked(self):
    for image in (np.zeros((2, 2, 4), np.uint8), np.zeros((2, 2, 3), np.float32),
                  np.zeros((0, 2, 3), np.uint8), np.zeros((1, 4097, 3), np.uint8)):
      with self.assertRaises(ValueError):
        ObservationState(trace(image=image))
    with self.assertRaises(RecordingCapacityError):
      ObservationState(trace(image=np.zeros((16, 16, 3), np.uint8)),
                       limits=RecordingLimits(frame_bytes=256))

  def test_frame_byte_boundary_uses_actual_immutable_array_and_base_sizes(self):
    image = np.zeros((8, 8, 3), np.uint8)
    initial = ObservationState(trace(image=image))['frame']
    size = sys.getsizeof(initial) + sys.getsizeof(initial.base)
    accepted = ObservationState(trace(image=image), limits=RecordingLimits(frame_bytes=size))
    self.assertEqual(accepted['frame'].shape, image.shape)
    with self.assertRaises(RecordingCapacityError):
      ObservationState(trace(image=image), limits=RecordingLimits(frame_bytes=size - 1))

  def test_action_is_frozen_and_roundtrips_through_registered_adapter_and_pickle(self):
    action = Action(2, 'left', True, True)
    state = ObservationState(trace(debug={'action': [action]}), action_adapter=ADAPTER)
    action._name = 'changed by caller'
    value = state['action'][0]
    self.assertIsInstance(value, RecordedAction)
    self.assertEqual(value._name, 'left')
    with self.assertRaises(AttributeError):
      value._name = 'mutate'
    record = pickle.loads(pickle.dumps(state.to_record(include_frame=False)))
    self.assertIsInstance(record['debug']['action'][0], Action)
    self.assertEqual(vars(record['debug']['action'][0]), dict(
        _backend_action=2, _name='left', _sticky=True, _directional=True))
    self.assertEqual(state['action'][0]._name, 'left')

  def test_unregistered_malformed_and_lossy_action_adapter_reject(self):
    with self.assertRaises(ValueError):
      ObservationState(trace(debug={'action': [Action(1, 'x')]}))
    action = Action(1, 'x')
    action.extra = b'extra'
    with self.assertRaises(ValueError):
      ObservationState(trace(debug={'action': [action]}), action_adapter=ADAPTER)
    bad_adapter = ActionAdapter(Action, lambda value: Action(7, value.name))
    state = ObservationState(trace(debug={'action': [Action(1, 'x')]}), action_adapter=bad_adapter)
    with self.assertRaisesRegex(ValueError, 'changed recorded input'):
      state.to_record()

  def test_dump_record_does_not_remove_frame_or_inject_config_into_source(self):
    state = ObservationState(trace(image=np.zeros((8, 8, 3), np.uint8)))
    image = state['frame']
    record = state.to_record(include_frame=False, first_config={'level': 'test', 'players': ['agent']})
    self.assertNotIn('frame', record['observation'])
    self.assertEqual(record['debug']['config']['level'], 'test')
    self.assertNotIn('config', state['debug'])
    self.assertIs(state['frame'], image)
    class FailingWriter:
      def write(self, _):
        raise OSError('write failed')
    with self.assertRaisesRegex(OSError, 'write failed'):
      pickle.dump(record, FailingWriter())
    self.assertIs(state['frame'], image)
    self.assertNotIn('config', state['debug'])

  def test_first_config_is_bounded_and_copied_without_record_mutation(self):
    state = ObservationState(trace(), limits=RecordingLimits(debug_bytes=1024))
    with self.assertRaises(RecordingCapacityError):
      state.to_record(first_config={'array': np.zeros(1000)})
    config = {'players': ['agent']}
    record = state.to_record(first_config=config)
    config['players'].append('extra')
    self.assertEqual(record['debug']['config']['players'], ['agent'])
    self.assertNotIn('config', state['debug'])


class RecordingHistoryTest(unittest.TestCase):
  def test_count_fill_evict_clear_refill_and_retained_reader_ownership(self):
    history = ObservationHistory(RecordingLimits(trace_steps=3))
    first = history.append(trace(0))
    reference = weakref.ref(first)
    for frame in range(1, 1000):
      history.append(trace(frame))
      self.assertLessEqual(len(history), 3)
      self.assertEqual(history.stats()['retained_bytes'], sum(item.retained_bytes for item in history))
    self.assertEqual(float(first['ball'][0]), 0)
    self.assertIsNone(first._owner)
    del first
    gc.collect()
    self.assertIsNone(reference())
    history.clear()
    self.assertEqual(history.stats()['retained_bytes'], 0)
    self.assertEqual(len(history), 0)
    history.append(trace(1))
    self.assertEqual(len(history), 1)

  def test_byte_eviction_and_invalid_append_are_transactional(self):
    limits = RecordingLimits(step_bytes=8192, trace_bytes=8192)
    history = ObservationHistory(limits)
    for frame in range(20):
      history.append(trace(frame))
      self.assertLessEqual(history.stats()['retained_bytes'], limits.trace_bytes)
    self.assertLess(len(history), 20)
    previous = history[-1]
    previous_stats = history.stats()
    with self.assertRaises(RecordingCapacityError):
      history.append(trace(debug={'big': np.zeros(10000)}))
    self.assertIs(history[-1], previous)
    self.assertEqual(history.stats(), previous_stats)

  def test_frame_cache_eviction_and_mutation_refund_global_trace_bytes(self):
    limits = RecordingLimits(step_bytes=8192, trace_bytes=16384, additional_frames=2, additional_bytes=4096)
    history = ObservationHistory(limits)
    for index in range(4):
      history.append(trace(index))
    state = history[-1]
    for index in range(20):
      frame = np.full((16, 16, 3), index, np.uint8)
      state.add_frame(frame)
      frame[:] = 255
      self.assertLessEqual(len(state._additional_frames), 2)
      self.assertLessEqual(state.retained_bytes, limits.step_bytes)
      self.assertEqual(history.stats()['retained_bytes'], sum(item.retained_bytes for item in history))
      self.assertLessEqual(history.stats()['retained_bytes'], limits.trace_bytes)
    self.assertEqual(int(state._additional_frames[-1][0, 0, 0]), 19)
    self.assertIsInstance(state._additional_frames[-1].base, bytes)
    self.assertGreater(state.stats()['dropped_frames'], 0)

  def test_debug_text_ring_bounds_and_rejects_giant_or_non_text_line(self):
    limits = RecordingLimits(debug_lines=3, debug_line_bytes=128, debug_text_bytes=384)
    history = ObservationHistory(limits)
    state = history.append(trace())
    for index in range(1000):
      state.add_debug('line ' + str(index))
      self.assertLessEqual(len(state._debugs), 3)
      self.assertLessEqual(state.stats()['debug_text_bytes'], 384)
      self.assertEqual(history.stats()['retained_bytes'], state.retained_bytes)
    self.assertEqual(state._debugs[-1], 'line 999')
    previous = state.stats()
    for value in (b'bytes', ['list'], 'x' * 128):
      with self.assertRaises(ValueError):
        state.add_debug(value)
      self.assertEqual(state.stats(), previous)

  def test_disabled_optional_caches_do_not_retain_new_values(self):
    limits = RecordingLimits(additional_frames=0, debug_lines=0)
    state = ObservationState(trace(), limits=limits)
    before = state.retained_bytes
    for _ in range(100):
      self.assertFalse(state.add_frame(np.zeros((8, 8, 3), np.uint8)))
      self.assertFalse(state.add_debug('text'))
    self.assertEqual(state.retained_bytes, before)
    self.assertEqual(state.stats()['dropped_frames'], 100)
    self.assertEqual(state.stats()['dropped_debug_lines'], 100)

  def test_aggregate_step_limit_does_not_drop_the_valid_base_observation(self):
    limits = RecordingLimits(step_bytes=4096, trace_bytes=4096, additional_bytes=4096)
    history = ObservationHistory(limits)
    state = history.append(trace())
    before = state.to_record()
    self.assertFalse(state.add_frame(np.zeros((24, 24, 3), np.uint8)))
    self.assertLessEqual(state.retained_bytes, limits.step_bytes)
    self.assertEqual(len(history), 1)
    np.testing.assert_array_equal(state['ball'], before['observation']['ball'])

  def test_mutating_an_evicted_reader_does_not_change_live_history_accounting(self):
    history = ObservationHistory(RecordingLimits(trace_steps=1))
    evicted = history.append(trace(0))
    current = history.append(trace(1))
    before = history.stats()
    evicted.add_frame(np.zeros((8, 8, 3), np.uint8))
    evicted.add_debug('reader-owned')
    self.assertEqual(history.stats(), before)
    self.assertIs(history[-1], current)

  def test_dump_names_allow_short_local_names_and_reject_escape_or_unbounded_text(self):
    for name in ('score', 'episode_done', '进球', 'debug.1'):
      self.assertEqual(validate_dump_name(name), name)
    for name in ('', '..', '../escape', 'a/b', 'a\\b', 'C:escape', 'nul', 'CON.txt',
                 'trailing.', 'trailing ', 'a\x00b', 'x' * 65, '进' * 22):
      with self.subTest(name=name), self.assertRaises(ValueError):
        validate_dump_name(name)


if __name__ == '__main__':
  unittest.main()
