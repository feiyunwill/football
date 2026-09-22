"""Deterministic scheduling, cancellation and real input/reconciliation contracts."""
import asyncio
import threading
import unittest

from gfootball.frame_sync.frame_pacing import FramePacer, MAX_CLOCK_NS
from gfootball.frame_sync.graphical_input import InputBuffer, BufferedControls
from gfootball.frame_sync.client_logic import ClientLogicLoop
from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.test_client_logic_budget import Client, Engine


class Clock:
  def __init__(self):
    self.ns = 0
    self.waits = []
    self.overshoot = 0

  def __call__(self):
    return self.ns

  def wait(self, seconds):
    self.waits.append(seconds)
    self.ns += round(seconds * 1_000_000_000)
    if seconds:
      self.ns += self.overshoot
    return False


class FramePacingTest(unittest.TestCase):
  def test_processing_cost_and_wakeup_overshoot_do_not_accumulate_drift(self):
    clock = Clock()
    pacer = FramePacer(10, clock_ns=clock)
    clock.overshoot = 1_000_000
    starts = []
    for _ in range(1000):
      self.assertTrue(pacer.wait_next(clock.wait))
      starts.append(clock.ns)
      clock.ns += 17_000_000
    self.assertEqual(starts, [0] + [n * 100_000_000 + 1_000_000 for n in range(1, 1000)])
    self.assertEqual(pacer.stats()['missed_deadlines'], 0)
    self.assertEqual(pacer.stats()['max_lateness_ns'], 1_000_000)

  def test_stall_discards_schedule_debt_without_a_catchup_burst(self):
    clock = Clock()
    pacer = FramePacer(10, clock_ns=clock)
    pacer.wait_next(clock.wait)
    clock.ns = 10_055_000_000
    pacer.wait_next(clock.wait)
    self.assertEqual(pacer.stats()['ticks'], 2)
    self.assertEqual(pacer.stats()['missed_deadlines'], 99)
    pacer.wait_next(clock.wait)
    self.assertEqual(clock.ns, 10_100_000_000)
    self.assertEqual(pacer.stats()['ticks'], 3)

  def test_boundary_lateness_and_60hz_interval_rounding(self):
    clock = Clock()
    pacer = FramePacer(60, clock_ns=clock)
    pacer.wait_next(clock.wait)
    period = 16_666_667
    clock.ns = 2 * period
    pacer.wait_next(clock.wait)
    self.assertEqual(pacer.stats()['missed_deadlines'], 1)
    pacer.wait_next(clock.wait)
    self.assertEqual(clock.ns, 3 * period)

  def test_early_wakeup_rechecks_deadline_without_admitting_early(self):
    clock = Clock()
    pacer = FramePacer(clock_ns=clock)
    pacer.wait_next(clock.wait)
    def early(seconds):
      clock.ns += min(round(seconds * 1_000_000_000), 7_000_000)
    pacer.wait_next(early)
    self.assertEqual(clock.ns, 100_000_000)
    self.assertEqual(pacer.stats()['ticks'], 2)

  def test_cancel_before_first_tick_or_during_wait_does_not_admit_work(self):
    clock = Clock()
    pacer = FramePacer(clock_ns=clock)
    self.assertFalse(pacer.wait_next(lambda _: True))
    self.assertEqual(pacer.stats()['ticks'], 0)
    pacer.wait_next(clock.wait)
    self.assertFalse(pacer.wait_next(lambda seconds: seconds > 0))
    self.assertEqual(pacer.stats()['ticks'], 1)
    pacer.wait_next(clock.wait)
    self.assertEqual(clock.ns, 100_000_000)

  def test_bad_clock_and_stalled_wait_fail_instead_of_spinning(self):
    for value in (-1, True, .1, MAX_CLOCK_NS + 1):
      with self.assertRaises(ValueError):
        FramePacer(clock_ns=lambda: value).wait_next(lambda _: False)
    clock = Clock()
    pacer = FramePacer(clock_ns=clock)
    pacer.wait_next(clock.wait)
    with self.assertRaisesRegex(RuntimeError, 'without advancing'):
      pacer.wait_next(lambda _: False)
    clock.ns = 200_000_000
    pacer.wait_next(clock.wait)
    clock.ns -= 1
    with self.assertRaisesRegex(ValueError, 'backwards'):
      pacer.wait_next(clock.wait)

  def test_invalid_configuration_and_exhausted_clock_are_rejected(self):
    for rate in (True, 0, 241, float('nan'), float('inf')):
      with self.assertRaises(ValueError):
        FramePacer(rate)
    with self.assertRaises(ValueError):
      FramePacer(clock_ns=3)
    with self.assertRaises(OverflowError):
      FramePacer(clock_ns=lambda: MAX_CLOCK_NS).wait_next(lambda _: False)
    with self.assertRaises(ValueError):
      FramePacer().wait_next(3)

  def test_foreign_thread_and_reentrancy_are_rejected_without_sticking_active(self):
    clock = Clock()
    pacer = FramePacer(clock_ns=clock)
    caught = []
    def foreign():
      try:
        pacer.wait_next(clock.wait)
      except RuntimeError as error:
        caught.append(str(error))
    thread = threading.Thread(target=foreign, name='football-pacing-owner-test')
    thread.start()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(len(caught), 1)
    with self.assertRaisesRegex(RuntimeError, 'reentrant'):
      pacer.wait_next(lambda _: pacer.wait_next(clock.wait))
    self.assertTrue(pacer.wait_next(clock.wait))
    self.assertEqual(pacer.stats()['ticks'], 1)

  def test_real_event_wakes_input_wait_without_consuming_save_or_actions(self):
    inputs = InputBuffer()
    controls = BufferedControls(inputs)
    entered, completed = threading.Event(), threading.Event()
    values = []
    def waiting():
      entered.set()
      values.append(controls.wait(1))
      completed.set()
    thread = threading.Thread(target=waiting, name='football-pacing-input-test')
    thread.start()
    try:
      self.assertTrue(entered.wait(1))
      inputs.feed(pressed_keys=('p', 'v'))
      self.assertFalse(completed.is_set())
      inputs.request_quit()
      self.assertTrue(completed.wait(.5))
    finally:
      inputs.close()
      thread.join(2)
    self.assertEqual(values, [True])

  def test_quit_sources_wake_wait_and_save_read_is_independent(self):
    for state in (dict(quit=True, focused=False), dict(keys=('escape',)),
                  dict(connected=True, pressed_buttons=1 << 4)):
      inputs = InputBuffer()
      inputs.feed(pressed_keys=('p', 'z'))
      self.assertFalse(inputs.wait_for_quit(0))
      self.assertEqual(inputs.sample().buttons, 4)
      self.assertEqual(inputs.commands(), (False, True))
      inputs.feed(**state)
      self.assertTrue(inputs.wait_for_quit(0))
    for value in (-1, 2, True, float('nan')):
      with self.assertRaises(ValueError):
        InputBuffer().wait_for_quit(value)

  def test_waiting_retry_stall_and_correction_never_resample_a_sent_frame(self):
    clock, inputs, client, env = Clock(), InputBuffer(), Client(), Engine()
    pacer = FramePacer(clock_ns=clock)
    sampled = []
    def sample():
      frame = logic.get_current_frame_id()
      value = inputs.sample(frame)
      sampled.append((frame, value.buttons))
      return [(0, value)]
    logic = ClientLogicLoop(client, env, 1, sample, clock=lambda: clock.ns / 1e9)
    self.addCleanup(logic.stop)
    inputs.feed(pressed_keys=('v',))
    for _ in range(4):
      pacer.wait_next(clock.wait)
      logic.run_one_tick()
    self.assertEqual(sampled, [(0, 8), (1, 0), (2, 0), (3, 0)])
    inputs.feed(pressed_keys=('z',))
    clock.ns += 10_000_000_000
    for _ in range(6):
      pacer.wait_next(clock.wait)
      logic.run_one_tick()
    self.assertEqual(len(sampled), 4)
    self.assertEqual(env.frame, 3)
    self.assertTrue(all(entries[0][1].buttons == 8 for frame, entries in client.sent if frame == 0))
    client.auth.append((0, [wire.default_slot_input()]))  # Correct the initial shot.
    pacer.wait_next(clock.wait)
    logic.run_one_tick()
    self.assertGreater(logic.get_rollback_count(), 0)
    self.assertEqual(len(sampled), 4)
    pacer.wait_next(clock.wait)
    logic.run_one_tick()
    self.assertEqual(sampled[-1], (4, 4))
    self.assertEqual(inputs.sample().buttons, 0)


class AsyncFramePacingTest(unittest.IsolatedAsyncioTestCase):
  async def test_async_deadlines_match_sync_and_yield_during_overrun(self):
    clock = Clock()
    pacer = FramePacer(clock_ns=clock)
    yields = []
    async def wait(seconds):
      await asyncio.sleep(0)
      yields.append(seconds)
      return clock.wait(seconds)
    await pacer.wait_next_async(wait)
    clock.ns = 455_000_000
    await pacer.wait_next_async(wait)
    await pacer.wait_next_async(wait)
    self.assertEqual(clock.ns, 500_000_000)
    self.assertEqual(pacer.stats()['missed_deadlines'], 3)
    self.assertEqual(sum(value == 0 for value in yields), 3)

  async def test_cancelled_task_releases_wait_guard_and_never_admits_tick(self):
    pacer = FramePacer(clock_ns=lambda: 0)
    entered = asyncio.Event()
    async def wait(seconds):
      entered.set()
      await asyncio.Event().wait()
    task = asyncio.create_task(pacer.wait_next_async(wait))
    await entered.wait()
    task.cancel()
    with self.assertRaises(asyncio.CancelledError):
      await task
    self.assertEqual(pacer.stats()['ticks'], 0)
    self.assertTrue(await pacer.wait_next_async())


if __name__ == '__main__':
  unittest.main()
