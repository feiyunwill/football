# 2026-09-09: bounded publication, render ownership and logic/display contracts.
# Engine/render doubles expose call identity; this is not native GPU validation.
import dataclasses
import math
import struct
import sys
import threading
import time
import unittest
import weakref

from gfootball.frame_sync.client import ClientLogicLoop
from gfootball.frame_sync.presentation import LogicStateHolder, PresentationLoop
from gfootball.frame_sync.presentation_state import PresentationCapacityError, PresentationState
from gfootball.frame_sync.test_client_logic_budget import Client, Engine, inputs


class Clock:
  def __init__(self):
    self.now = 0.0

  def __call__(self):
    return self.now


class Display:
  def __init__(self):
    self.state = None
    self.restored = []
    self.drawn = []
    self.on_restore = None
    self.on_draw = None

  def set_state(self, state):
    self.restored.append(state)
    self.state = state
    if self.on_restore:
      self.on_restore()

  def render(self):
    if self.on_draw:
      self.on_draw()
    self.drawn.append(self.state)


class HolderBudgetTest(unittest.TestCase):
  def test_public_sample_rejects_mutable_oversized_or_inconsistent_values(self):
    valid = dict(state=b'valid', frame_id=0, confirmed_frame_id=-1, timestamp=0.0,
                 waiting_for_authority=False, revision=1, state_revision=1, discontinuity=False)
    for name, value in (('state', bytearray(b'mutable')), ('state', b'x' * (1024 * 1024)),
                        ('frame_id', True), ('confirmed_frame_id', 1), ('timestamp', float('nan')),
                        ('timestamp', True), ('revision', 0), ('state_revision', 2), ('discontinuity', 1)):
      with self.subTest(name=name), self.assertRaises(ValueError):
        PresentationState(**{**valid, name: value})

  def test_invalid_limits_rejected_before_any_storage(self):
    for kwargs in ({'buffer_size': 0}, {'buffer_size': True}, {'buffer_size': 65},
                   {'snapshot_bytes': 63}, {'snapshot_bytes': 2**30}, {'history_bytes': 2**30},
                   {'history_bytes': False}, {'clock': 1}):
      with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
        LogicStateHolder(**kwargs)

  def test_count_eviction_clear_refill_and_close_release_records(self):
    holder = LogicStateHolder(buffer_size=3)
    for frame in range(1000):
      holder.write(str(frame), frame, frame)
      self.assertLessEqual(holder.buffer_depth, 3)
    sample = holder.read_sample()
    reference = weakref.ref(sample)
    old_revision = sample.revision
    del sample
    holder.clear()
    self.assertIsNone(reference())
    self.assertEqual(holder.read(), (None, -1, -1, None, False))
    self.assertEqual(holder.stats()['retained_bytes'], 0)
    holder.write('new session', 0, 0)
    self.assertGreater(holder.read_sample().revision, old_revision)
    holder.close()
    holder.close()
    self.assertTrue(holder.stats()['closed'])
    self.assertEqual(holder.buffer_depth, 0)
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      holder.write('after close', 0)

  def test_byte_eviction_uses_actual_object_size_not_serialized_length(self):
    payload = b'x' * 50
    size = sys.getsizeof(payload)
    holder = LogicStateHolder(buffer_size=20, snapshot_bytes=128, history_bytes=2 * size)
    for frame in range(100):
      holder.write(payload + bytes([frame]), frame)
      self.assertEqual(holder.buffer_depth, 1)  # two objects are 2 bytes over the limit
      self.assertEqual(holder.stats()['retained_bytes'], size + 1)
    self.assertEqual(holder.read()[1], 99)

  def test_large_or_mutable_state_rejection_preserves_latest_sample(self):
    holder = LogicStateHolder(snapshot_bytes=128, history_bytes=128)
    holder.write(b'valid', 0)
    previous = holder.read_sample()
    for state in (bytearray(b'mutable'), memoryview(b'mutable'), None, ['state']):
      with self.assertRaises(ValueError):
        holder.write(state, 1)
      self.assertIs(holder.read_sample(), previous)
    for state in (b'a' * 128, '\U0001f600' * 25):
      self.assertGreater(sys.getsizeof(state), 128)
      with self.assertRaises(PresentationCapacityError):
        holder.write(state, 1)
      self.assertIs(holder.read_sample(), previous)
    # The aggregate budget also rejects one otherwise valid snapshot.
    small_history = LogicStateHolder(snapshot_bytes=256, history_bytes=64)
    with self.assertRaises(PresentationCapacityError):
      small_history.write(b'a' * 64, 0)
    self.assertIsNone(small_history.read_sample())

  def test_frame_and_flag_validation_preserves_previous_session(self):
    holder = LogicStateHolder()
    holder.write('base', 3, 2)
    previous = holder.read_sample()
    for args, kwargs in (((True,), {}), ((0xfffffff8,), {}), ((-2,), {}),
                         ((4, 5), {}), ((4, 1), {}), ((1,), {}),
                         ((4,), {'waiting_for_authority': 1}), ((4,), {'discontinuity': 'yes'})):
      with self.assertRaises(ValueError):
        holder.write('bad', *args, **kwargs)
      self.assertIs(holder.read_sample(), previous)

  def test_immutable_atomic_sample_and_legacy_tuple_contract(self):
    clock = Clock()
    holder = LogicStateHolder(clock=clock)
    holder.write(b'state', 4, 2, True)
    sample = holder.read_sample()
    self.assertEqual(holder.read(), (b'state', 4, 2, 0.0, True))
    with self.assertRaises(dataclasses.FrozenInstanceError):
      sample.frame_id = 9
    holder.write(b'new', 5, 3)
    self.assertEqual(sample.state, b'state')  # reader-owned earlier sample stays coherent
    self.assertEqual(sample.frame_id, 4)

  def test_metadata_update_reuses_payload_revision_and_replaces_one_record(self):
    clock = Clock()
    holder = LogicStateHolder(clock=clock)
    holder.write('state', 0)
    first = holder.read_sample()
    clock.now = 0.05
    holder.write('state', 0, 0, True)
    latest = holder.read_sample()
    self.assertGreater(latest.revision, first.revision)
    self.assertEqual(latest.state_revision, first.state_revision)
    self.assertEqual(latest.timestamp, 0.0)
    self.assertTrue(latest.waiting_for_authority)
    self.assertEqual(holder.buffer_depth, 1)
    self.assertEqual(holder.stats()['retained_bytes'], sys.getsizeof('state'))

  def test_same_frame_correction_rewind_and_explicit_cut_drop_stale_history(self):
    for operation in ('same', 'rewind', 'forward_correction'):
      with self.subTest(operation=operation):
        holder = LogicStateHolder()
        holder.write('s0', 0, -1)
        holder.write('s1', 1, 0)
        holder.write('s2', 2, 0)
        old = weakref.ref(holder.read_sample())
        frame = 2 if operation == 'same' else 1 if operation == 'rewind' else 3
        holder.write('corrected', frame, 0, discontinuity=operation == 'forward_correction')
        self.assertEqual(holder.buffer_depth, 1)
        self.assertIsNone(old())
        self.assertTrue(holder.read_sample().discontinuity)
        self.assertEqual(holder.read_interpolated(), ('corrected', 0.0))

  def test_phase_uses_latest_publication_monotonic_time_and_never_blends_payload(self):
    clock = Clock()
    holder = LogicStateHolder(clock=clock)
    holder.write('old', 0)
    clock.now = 0.1
    holder.write('new', 1)
    self.assertEqual(holder.read_interpolated(), ('new', 0.0))
    clock.now = 0.125
    state, phase = holder.read_interpolated()
    self.assertEqual(state, 'new')
    self.assertAlmostEqual(phase, 0.25)
    clock.now = 3
    self.assertEqual(holder.read_interpolated(), ('new', 0.999))
    holder.write('new', 1, waiting_for_authority=True)
    self.assertEqual(holder.read_interpolated(), ('new', 0.0))
    for fps in (0, True, float('nan'), float('inf'), 241):
      with self.assertRaises(ValueError):
        holder.set_logic_fps(fps)
    holder.set_logic_fps(15)
    self.assertEqual(holder._logic_fps, 15.0)

  def test_bad_clock_does_not_replace_good_publication(self):
    clock = Clock()
    holder = LogicStateHolder(clock=clock)
    clock.now = 1
    holder.write('valid', 0)
    sample = holder.read_sample()
    for now in (0.5, float('nan'), float('inf'), -1, True):
      clock.now = now
      with self.assertRaises(ValueError):
        holder.write('bad time', 1)
      self.assertIs(holder.read_sample(), sample)

  def test_metadata_timestamp_is_preserved_but_write_clock_cannot_regress(self):
    clock = Clock()
    holder = LogicStateHolder(clock=clock)
    holder.write('payload', 0)
    clock.now = 1
    holder.write('payload', 0, waiting_for_authority=True)
    previous = holder.read_sample()
    self.assertEqual(previous.timestamp, 0.0)
    clock.now = 0.5
    with self.assertRaisesRegex(ValueError, 'backwards'):
      holder.write('new', 1)
    self.assertIs(holder.read_sample(), previous)
    holder.clear()
    holder.write('new session', 0)
    self.assertGreater(holder.read_sample().revision, previous.revision)

  def test_revision_exhaustion_rejects_without_reusing_identity(self):
    holder = LogicStateHolder()
    holder._revision = 0xfffffffffffffffe
    holder.write('last', 0)
    sample = holder.read_sample()
    with self.assertRaises(OverflowError):
      holder.write('overflow', 1)
    self.assertIs(holder.read_sample(), sample)
    holder.close()
    self.assertEqual(holder.stats()['retained_bytes'], 0)

  def test_one_writer_and_three_readers_observe_coherent_bounded_state(self):
    holder = LogicStateHolder(buffer_size=8, history_bytes=1024)
    begin = threading.Barrier(4)
    done = threading.Event()
    checkpoint = threading.Event()
    checkpoint_frame = [-1]
    acknowledged = [threading.Event() for _ in range(3)]
    errors = []
    observed = [0, 0, 0]
    def producer():
      try:
        begin.wait(2)
        for frame in range(5000):
          holder.write(struct.pack('<II', frame, frame ^ 0x12345678), frame, frame)
          # 2026-09-09: sleep(0) does not guarantee another thread runs on
          # Windows. Require actual reads at 20 checkpoints without serializing
          # the remaining publication/read race between those checkpoints.
          # if frame % 25 == 0:
          #   time.sleep(0)
          if frame % 250 == 0:
            for event in acknowledged:
              event.clear()
            checkpoint_frame[0] = frame
            checkpoint.set()
            deadline = time.monotonic() + 2
            if not all(event.wait(max(0, deadline - time.monotonic())) for event in acknowledged):
              raise AssertionError('concurrent readers did not acknowledge publication')
            checkpoint.clear()
      except BaseException as error:
        errors.append(error)
      finally:
        done.set()
    def reader(index):
      try:
        begin.wait(2)
        previous = -1
        while not done.is_set():
          sample = holder.read_sample()
          if sample is not None:
            frame, check = struct.unpack('<II', sample.state)
            self.assertEqual((frame, frame), (sample.frame_id, sample.confirmed_frame_id))
            self.assertEqual(check, frame ^ 0x12345678)
            self.assertGreaterEqual(frame, previous)
            self.assertLessEqual(holder.stats()['retained_bytes'], 1024)
            previous = frame
            observed[index] += 1
            if checkpoint.is_set() and frame >= checkpoint_frame[0]:
              acknowledged[index].set()
          time.sleep(0)
      except BaseException as error:
        errors.append(error)
    threads = [threading.Thread(target=producer, name='presentation-budget-writer')]
    threads += [threading.Thread(target=reader, args=(i,), name='presentation-budget-reader') for i in range(3)]
    for thread in threads:
      thread.start()
    for thread in threads:
      thread.join(5)
    self.assertTrue(all(not thread.is_alive() for thread in threads))
    self.assertEqual(errors, [])
    # 2026-09-09: prove every reader consumed at least the 20 checkpoints.
    # self.assertTrue(all(observed))
    self.assertTrue(all(count >= 20 for count in observed))
    self.assertEqual(holder.read()[1], 4999)
    self.assertEqual(holder.buffer_depth, 8)


class RenderBudgetTest(unittest.TestCase):
  def make(self, **options):
    self.clock = Clock()
    self.holder = LogicStateHolder(clock=self.clock)
    self.display = Display()
    self.loop = PresentationLoop(self.display, self.holder, clock=self.clock, **options)
    return self.loop

  def test_invalid_configuration_and_missing_atomic_interface_rejected(self):
    for options in ({'rate_hz': 0}, {'rate_hz': True}, {'rate_hz': float('nan')},
                    {'jitter_samples': 0}, {'jitter_samples': 1025}, {'jitter_samples': True}):
      with self.assertRaises(ValueError):
        self.make(**options)
    with self.assertRaises(ValueError):
      PresentationLoop(Display(), object())

  def test_same_state_draws_600_times_with_only_one_restore_and_no_payload_cache(self):
    loop = self.make()
    state = bytes(range(256)) * 4
    self.holder.write(state, 0)
    # The test display records its own calls; clear them to inspect consumer ownership.
    loop.run_one_frame()
    self.display.restored.clear()
    self.display.drawn.clear()
    before = sys.getrefcount(state)
    for frame in range(599):
      self.clock.now = (frame + 1) / 60
      self.assertTrue(loop.run_one_frame())
      self.display.drawn.clear()
    self.assertEqual(sys.getrefcount(state), before)
    self.assertEqual(loop.stats()['restore_count'], 1)
    self.assertEqual(loop.render_count, 600)
    self.assertEqual(loop.stats()['jitter_samples'], 100)

  def test_new_payload_same_frame_restores_but_metadata_only_update_does_not(self):
    loop = self.make()
    self.holder.write('predicted', 2, 0)
    loop.run_one_frame()
    self.holder.write('corrected', 2, 1)
    loop.run_one_frame()
    self.holder.write('corrected', 2, 2, True)
    loop.run_one_frame()
    self.assertEqual(self.display.restored, ['predicted', 'corrected'])
    self.assertEqual(self.display.drawn, ['predicted', 'corrected', 'corrected'])

  def test_clear_suppresses_stale_draw_and_same_payload_new_session_restores(self):
    loop = self.make()
    self.holder.write('session', 0)
    loop.run_one_frame()
    self.holder.clear()
    self.assertFalse(loop.run_one_frame())
    self.holder.write('session', 0)
    loop.run_one_frame()
    self.assertEqual(self.display.restored, ['session', 'session'])
    self.assertEqual(loop.render_count, 2)

  def test_one_atomic_sample_per_frame_no_split_read_and_no_holder_lock_around_engine(self):
    class Holder(LogicStateHolder):
      def read(self):
        raise AssertionError('split legacy read')
      def read_interpolated(self):
        raise AssertionError('split legacy interpolation read')
    holder, display = Holder(), Display()
    holder.write('first', 0)
    def publish_inside_restore():
      holder.write('second', 1)
    display.on_restore = publish_inside_restore
    loop = PresentationLoop(display, holder)
    loop.run_one_frame()
    self.assertEqual(display.drawn, ['first'])
    display.on_restore = None
    loop.run_one_frame()
    self.assertEqual(display.drawn, ['first', 'second'])

  def test_skips_obsolete_display_frames_and_draws_latest_snapshot(self):
    loop = self.make()
    for frame in range(100):
      self.holder.write(str(frame), frame, frame)
    loop.run_one_frame()
    self.assertEqual(self.display.restored, ['99'])
    self.assertEqual(self.display.drawn, ['99'])

  def test_restore_and_render_failure_stop_without_repeating_engine_calls(self):
    for stage in ('restore', 'render'):
      loop = self.make()
      self.holder.write('state', 0)
      def fail():
        raise RuntimeError('display failure')
      if stage == 'restore':
        self.display.on_restore = fail
      else:
        self.display.on_draw = fail
      with self.assertRaisesRegex(RuntimeError, 'display failure'):
        loop.run_one_frame()
      before = len(self.display.restored), len(self.display.drawn)
      for _ in range(20):
        self.assertFalse(loop.run_one_frame())
      self.assertEqual(before, (len(self.display.restored), len(self.display.drawn)))
      self.assertEqual(loop.failure_reason, stage + '_failed')
      self.assertEqual(loop.render_count, 0)

  def test_stop_in_restore_callback_prevents_draw(self):
    loop = self.make()
    self.holder.write('state', 0)
    self.display.on_restore = loop.stop
    self.assertFalse(loop.run_one_frame())
    self.assertEqual(self.display.drawn, [])
    self.assertEqual(loop.stats()['restore_count'], 1)
    self.assertIsNone(loop.failure_reason)

  def test_frame_and_loop_reentry_fail_without_deadlock(self):
    for name in ('run_one_frame', 'run_loop'):
      loop = self.make()
      self.holder.write('state', 0)
      self.display.on_restore = getattr(loop, name)
      with self.assertRaisesRegex(RuntimeError, 'reentrant|active frame'):
        loop.run_one_frame()
      self.assertEqual(loop.failure_reason, 'restore_failed')
      self.assertEqual(self.display.drawn, [])

  def test_jitter_zero_origin_bounded_samples_and_nearest_rank_percentile(self):
    loop = self.make(rate_hz=100, jitter_samples=20)
    self.holder.write('state', 0)
    loop.run_one_frame()  # zero is a real timestamp, not the uninitialized marker
    for index in range(1, 101):
      self.clock.now += 0.01 + index / 1000
      loop.run_one_frame()
    mean, maximum, p95 = loop.get_jitter_stats()
    self.assertAlmostEqual(mean, 90.5)
    self.assertAlmostEqual(maximum, 100)
    self.assertAlmostEqual(p95, 99)
    self.assertEqual(loop.stats()['jitter_samples'], 20)

  def test_bad_or_regressing_clock_stops_before_engine_work(self):
    for now in (float('nan'), -1, True):
      loop = self.make()
      self.holder.write('state', 0)
      self.clock.now = now
      with self.assertRaises(ValueError):
        loop.run_one_frame()
      self.assertEqual(self.display.restored, [])
      self.assertEqual(loop.failure_reason, 'clock_failed')
    loop = self.make()
    self.holder.write('state', 0)
    self.clock.now = 2
    loop.run_one_frame()
    self.clock.now = 1
    with self.assertRaises(ValueError):
      loop.run_one_frame()
    self.assertEqual(loop.render_count, 1)

  def test_stop_wakes_low_rate_loop_and_second_loop_cannot_overlap(self):
    loop = self.make(rate_hz=1)
    self.holder.write('state', 0)
    drawn = threading.Event()
    self.display.on_draw = drawn.set
    errors = []
    def run():
      try:
        loop.run_loop()
      except BaseException as error:
        errors.append(error)
    thread = threading.Thread(target=run, name='presentation-budget-loop')
    thread.start()
    try:
      self.assertTrue(drawn.wait(2))
      with self.assertRaisesRegex(RuntimeError, 'already running'):
        loop.run_loop()
      start = time.monotonic()
      loop.stop()
      thread.join(0.5)
      self.assertFalse(thread.is_alive())
      self.assertLess(time.monotonic() - start, 0.5)
    finally:
      loop.stop()
      thread.join(2)
    self.assertEqual(errors, [])


class LogicPresentationTest(unittest.TestCase):
  def make(self):
    self.client, self.engine, self.display = Client(), Engine(), Display()
    self.holder = LogicStateHolder(buffer_size=4, snapshot_bytes=128, history_bytes=256)
    self.logic = ClientLogicLoop(self.client, self.engine, 2, lambda: [(0, inputs()[0])],
                                 state_holder=self.holder, clock=lambda: 0.0)
    self.render = PresentationLoop(self.display, self.holder)

  def test_corrected_replay_invalidates_history_even_when_display_frame_advances(self):
    self.make()
    for _ in range(3):
      self.logic.run_one_tick()
      self.render.run_one_frame()
    self.assertEqual(self.holder.buffer_depth, 3)
    previous_frame = self.holder.read_sample().frame_id
    self.client.auth.append((0, inputs(-1, 1)))
    self.logic.run_one_tick()
    sample = self.holder.read_sample()
    self.assertGreater(sample.frame_id, previous_frame)
    self.assertEqual(sample.confirmed_frame_id, 0)
    self.assertTrue(sample.discontinuity)
    self.assertEqual(self.holder.buffer_depth, 1)
    self.render.run_one_frame()
    self.assertEqual(self.display.state, self.engine.get_state(''))
    self.assertEqual(self.render.stats()['restore_count'], 4)

  def test_many_render_ticks_do_not_step_or_restore_the_logic_engine(self):
    self.make()
    self.logic.run_one_tick()
    before = self.engine.frame, self.engine.value, len(self.engine.steps), self.engine.restores
    for _ in range(300):
      self.render.run_one_frame()
    self.assertEqual((self.engine.frame, self.engine.value, len(self.engine.steps), self.engine.restores), before)
    self.assertEqual(self.render.render_count, 300)
    self.assertEqual(self.render.stats()['restore_count'], 1)
    self.assertEqual(self.display.state, self.engine.get_state(''))


if __name__ == '__main__':
  unittest.main()
