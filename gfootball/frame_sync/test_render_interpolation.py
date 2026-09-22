"""Presentation timing and numerical pose checks; no imitation GameEnv module."""
from collections import deque
import math
import struct
import threading
import unittest

from gfootball.frame_sync.presentation_loop import PresentationLoop
from gfootball.frame_sync.presentation_state import LogicStateHolder


class Clock:
  def __init__(self):
    self.now = 1.0
  def __call__(self):
    return self.now


class PoseDisplay:
  """Independent one-dimensional pose oracle; physics and display are separate."""
  def __init__(self):
    self.physics = self.visible = self.previous = 0.0
    self.restores = 0
    self.calls = deque(maxlen=8)
    self.fail = None

  def set_state(self, state):
    if self.fail == 'restore':
      raise RuntimeError('restore failed')
    self.physics, = struct.unpack('<d', state)
    self.restores += 1

  def save_render_state(self, from_display=False):
    if self.fail == 'capture':
      raise RuntimeError('capture failed')
    self.previous = self.visible if from_display else self.physics
    self.calls.append(('capture', from_display, self.previous))

  def render(self):
    self.visible = self.physics

  def render_interpolated(self, alpha):
    if self.fail == 'render':
      raise RuntimeError('render failed')
    self.visible = (1 - alpha) * self.previous + alpha * self.physics
    self.calls.append(('render', alpha, self.visible))


class RenderInterpolationTest(unittest.TestCase):
  def setUp(self):
    self.clock, self.display = Clock(), PoseDisplay()
    self.holder = LogicStateHolder(clock=self.clock)
    self.loop = PresentationLoop(self.display, self.holder, clock=self.clock, interpolate=True)
    self.addCleanup(self.loop.stop)
    self.addCleanup(self.holder.close)

  def publish(self, frame, value, confirmed=None, **flags):
    self.holder.write(struct.pack('<d', value), frame, frame if confirmed is None else confirmed, **flags)

  def draw(self, now, expected, **options):
    self.clock.now = now
    self.assertTrue(self.loop.run_one_frame(**options))
    self.assertAlmostEqual(self.display.visible, expected, places=8)

  def initial(self):
    self.publish(0, 0)
    self.draw(1, 0)
    self.clock.now = 1.1
    self.publish(1, 10)

  def test_phase_uses_last_logic_time_and_stalls_never_extrapolate(self):
    self.initial()
    self.draw(1.125, 2.5)
    self.assertEqual(self.display.physics, 10)
    self.draw(1.15, 5)
    self.draw(1.3, 10)
    self.draw(1001.3, 10)
    self.assertEqual(self.display.restores, 2)
    self.assertEqual(self.loop.stats()['correction_blends'], 0)

  def test_slow_display_uses_coherent_latest_pair_without_replaying_old_states(self):
    self.initial()
    self.clock.now = 1.2
    self.publish(2, 20)
    self.draw(1.225, 12.5)
    self.assertEqual(self.display.restores, 3)
    self.assertEqual(self.display.calls[-2], ('capture', False, 10))
    self.assertEqual(self.holder.buffer_depth, 3)

  def test_long_regular_sequence_does_not_accumulate_visual_lag(self):
    self.publish(0, 0)
    self.draw(1, 0)
    for frame in range(1, 1001):
      timestamp = 1 + frame / 10
      self.clock.now = timestamp
      self.publish(frame, float(frame))
      self.draw(timestamp + .025, frame - .75)
    self.assertEqual(self.holder.buffer_depth, 4)
    self.assertEqual(self.display.restores, 1001)
    self.assertEqual(self.loop.stats()['correction_blends'], 0)

  def test_correction_starts_at_visible_pose_and_never_changes_physics(self):
    self.initial()
    self.draw(1.15, 5)
    self.clock.now = 1.16
    self.publish(1, -10)
    self.draw(1.16, 5)
    self.draw(1.21, -2.5)
    self.assertEqual(self.display.physics, -10)
    self.draw(1.27, -10)
    self.assertEqual(self.loop.stats()['correction_blends'], 1)

  def test_second_correction_blends_from_in_flight_visible_pose(self):
    self.initial()
    self.draw(1.15, 5)
    self.clock.now = 1.16
    self.publish(1, -10)
    self.draw(1.16, 5)
    self.draw(1.21, -2.5)
    self.clock.now = 1.22
    self.publish(1, 20)
    self.draw(1.22, -2.5)
    self.draw(1.27, 8.75)
    self.draw(1.33, 20)

  def test_identical_payload_discontinuity_is_not_restarted_each_draw(self):
    self.initial()
    self.draw(1.15, 5)
    self.clock.now = 1.16
    self.publish(1, 10, discontinuity=True)
    self.draw(1.16, 5)
    self.draw(1.21, 7.5)
    self.draw(1.27, 10)
    self.assertEqual(self.loop.stats()['correction_blends'], 1)

  def test_new_regular_frame_during_correction_preserves_visible_continuity(self):
    self.initial()
    self.draw(1.15, 5)
    self.clock.now = 1.16
    self.publish(1, -10)
    self.draw(1.16, 5)
    self.draw(1.19, .5)
    self.clock.now = 1.2
    self.publish(2, 20)
    self.draw(1.2, .5)
    self.draw(1.25, 10.25)
    self.draw(1.31, 20)

  def test_confirmations_and_waiting_flags_keep_original_publication_time(self):
    self.publish(0, 0)
    self.draw(1, 0)
    self.clock.now = 1.1
    self.publish(1, 10, confirmed=0)
    self.draw(1.12, 2)
    self.clock.now = 1.14
    self.publish(1, 10, waiting_for_authority=True)
    self.assertEqual(self.holder.read_sample().timestamp, 1.1)
    self.draw(1.16, 6)
    self.draw(1.3, 10)
    self.assertEqual(self.display.restores, 2)

  def test_settle_reaches_final_pose_and_next_draw_cannot_rewind(self):
    self.initial()
    self.draw(1.11, 10, settle=True)
    self.draw(1.12, 10)
    self.assertEqual(self.display.physics, 10)

  def test_clear_drops_pair_and_new_session_cannot_blend_with_old_pose(self):
    self.initial()
    self.draw(1.15, 5)
    self.holder.clear()
    self.assertEqual(self.holder.read_pair(), (None, None))
    self.assertFalse(self.loop.run_one_frame())
    self.publish(0, 500)
    self.draw(1.2, 500)
    self.assertEqual(self.loop.stats()['correction_blends'], 0)

  def test_future_time_fails_before_restore_or_render(self):
    self.publish(0, 50)
    self.clock.now = .5
    with self.assertRaisesRegex(ValueError, 'ahead'):
      self.loop.run_one_frame()
    self.assertEqual(self.display.restores, 0)
    self.assertEqual(self.loop.failure_reason, 'interpolation_failed')
    self.assertTrue(self.loop.stats()['stopped'])

  def test_native_hook_failures_stop_and_release_frame_guard(self):
    for failure in ('capture', 'restore', 'render'):
      with self.subTest(failure=failure):
        display = PoseDisplay()
        loop = PresentationLoop(display, self.holder, clock=self.clock, interpolate=True)
        self.addCleanup(loop.stop)
        if self.holder.read_sample() is None:
          self.publish(0, 0)
        loop.run_one_frame()
        self.clock.now += .1
        self.publish(self.holder.read_sample().frame_id + 1, self.clock.now)
        display.fail = failure
        with self.assertRaisesRegex(RuntimeError, failure):
          loop.run_one_frame()
        self.assertFalse(loop._frame_lock.locked())
        self.assertTrue(loop.stats()['stopped'])

  def test_required_hooks_and_strict_options(self):
    for options in (dict(interpolate=1), dict(logic_hz=True), dict(logic_hz=math.nan), dict(logic_hz=0)):
      with self.assertRaises(ValueError):
        PresentationLoop(self.display, self.holder, **options)
    for name in ('save_render_state', 'render_interpolated'):
      display = PoseDisplay()
      setattr(display, name, None)
      with self.assertRaisesRegex(ValueError, name):
        PresentationLoop(display, self.holder, interpolate=True)
    with self.assertRaises(ValueError):
      self.loop.run_one_frame(settle=1)

  def test_atomic_pair_never_combines_frames_from_different_publications(self):
    holder = LogicStateHolder()
    self.addCleanup(holder.close)
    ready, done = threading.Event(), threading.Event()
    errors = []
    def publish():
      try:
        ready.wait(2)
        for frame in range(1000):
          holder.write(struct.pack('<I', frame), frame, frame)
      except BaseException as error:
        errors.append(error)
      finally:
        done.set()
    thread = threading.Thread(target=publish, name='football-presentation-pair-test')
    thread.start()
    ready.set()
    try:
      while not done.is_set():
        previous, current = holder.read_pair()
        if previous is not None:
          self.assertEqual(previous.frame_id + 1, current.frame_id)
          self.assertEqual(struct.unpack('<I', current.state)[0], current.frame_id)
    finally:
      thread.join(3)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [])
    self.assertLessEqual(holder.buffer_depth, 4)


if __name__ == '__main__':
  unittest.main()
