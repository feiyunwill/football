"""Input contract: independent expected directions, masks and release behavior."""
import math
import threading
import unittest

from gfootball.frame_sync.graphical_input import BufferedControls, InputBuffer


class GraphicalInputTest(unittest.TestCase):
  def test_diagonal_and_opposite_keys_have_consistent_speed(self):
    state = InputBuffer()
    state.feed(keys=('w', 'd', 'up'))
    value = state.sample()
    self.assertAlmostEqual(value.dir_x, math.sqrt(.5), places=6)
    self.assertAlmostEqual(value.dir_y, math.sqrt(.5), places=6)
    state.feed(keys=('w', 's', 'a', 'd'), connected=True, axes=(1, 1))
    self.assertEqual((state.sample().dir_x, state.sample().dir_y), (0, 0))
    state.feed(keys=())
    self.assertEqual((state.sample().dir_x, state.sample().dir_y), (0, 0))

  def test_short_tap_is_delivered_once_but_held_action_persists(self):
    state = InputBuffer()
    state.feed(keys=('z', 'lshift'))
    state.feed(keys=())
    self.assertEqual(state.sample().buttons, (1 << 2) | (1 << 9))
    self.assertEqual(state.sample().buttons, 0)
    state.feed(keys=('v',))
    self.assertEqual([state.sample().buttons for _ in range(4)], [8] * 4)
    state.feed(keys=())
    self.assertEqual(state.sample().buttons, 0)

  def test_events_between_ui_polls_and_multiple_actions_are_latched(self):
    state = InputBuffer()
    state.feed(pressed_keys=('z', 'x', 'v'))
    state.feed(pressed_keys=('space',))
    self.assertEqual(state.sample().buttons, 4 | 2 | 8 | 64)
    self.assertEqual(state.sample().buttons, 0)

  def test_radial_deadzone_rescales_without_diagonal_acceleration(self):
    state = InputBuffer(.2)
    for axes, expected in [((.1, .1), (0, 0)), ((.6, 0), (.5, 0)), ((1, 1), (math.sqrt(.5), math.sqrt(.5)))]:
      state.feed(connected=True, axes=axes)
      value = state.sample()
      self.assertAlmostEqual(value.dir_x, expected[0], places=6)
      self.assertAlmostEqual(value.dir_y, expected[1], places=6)

  def test_pad_actions_dpad_priority_and_hot_disconnect(self):
    state = InputBuffer()
    state.feed(connected=True, axes=(1, 0), buttons=(1 << 11) | (1 << 0) | (1 << 10))
    value = state.sample()
    self.assertEqual((value.dir_x, value.dir_y, value.buttons), (0, 1, 4 | 512))
    state.feed(connected=True, pressed_buttons=1 << 1)
    state.feed(connected=False, keys=('x',))
    self.assertEqual(state.sample().buttons, 2)
    state.feed(connected=True)
    self.assertEqual(state.sample().buttons, 0)

  def test_focus_loss_discards_held_and_pending_inputs_and_save(self):
    state = InputBuffer()
    state.feed(keys=('w', 'z', 'p'), connected=True, buttons=1)
    state.feed(keys=('w', 'z'), connected=True, buttons=1, focused=False)
    value = state.sample()
    self.assertEqual((value.dir_x, value.dir_y, value.buttons), (0, 0, 0))
    self.assertEqual(state.commands(), (False, False))
    state.feed()
    self.assertEqual(state.sample().buttons, 0)

  def test_save_is_edge_triggered_quit_is_sticky_and_commands_do_not_consume_actions(self):
    state = InputBuffer()
    controls = BufferedControls(state)
    state.feed(keys=('p', 'z'))
    self.assertFalse(state.quit_requested)
    self.assertFalse(state.quit_requested)
    controls.read()
    self.assertTrue(controls.save)
    self.assertEqual(state.sample().buttons, 4)
    state.feed(keys=('p',))
    controls.read()
    self.assertFalse(controls.save)
    state.feed(connected=True, pressed_buttons=(1 << 6) | (1 << 4))
    self.assertEqual(state.commands(), (True, True))
    self.assertEqual(state.commands(), (True, False))
    state.close()
    state.close()
    self.assertEqual(state.sample().buttons, 0)
    with self.assertRaises(RuntimeError):
      state.feed()

  def test_invalid_input_is_atomic_and_bounded(self):
    state = InputBuffer()
    state.feed(keys=('w', 'v'))
    for arguments in [dict(keys=['w'] * 100), dict(keys={'unknown'}), dict(axes=(float('nan'), 0)),
                      dict(axes=(1.1, 0)), dict(buttons=True), dict(pressed_buttons=65536),
                      dict(focused=1), dict(connected='yes'), dict(keys=(v for v in ('w',)))]:
      with self.assertRaises(ValueError):
        state.feed(**arguments)
      self.assertEqual(state.sample().buttons, 8)
    for value in (True, -.1, .6, float('inf')):
      with self.assertRaises(ValueError):
        InputBuffer(value)

  def test_producer_and_consumer_only_observe_complete_samples(self):
    state, failures = InputBuffer(), []
    def feed():
      try:
        for _ in range(4000):
          state.feed(keys=('w', 'v'))
          state.feed(keys=('d', 'z'))
      except BaseException as error:
        failures.append(error)
    producer = threading.Thread(target=feed, name='football-input-test')
    producer.start()
    for _ in range(4000):
      value = state.sample()
      self.assertIn((value.dir_x, value.dir_y), ((0, 0), (0, 1), (1, 0)))
      self.assertIn(value.buttons, (0, 4, 8, 12))
    producer.join(3)
    self.assertFalse(producer.is_alive())
    self.assertFalse(failures)


if __name__ == '__main__':
  unittest.main()
