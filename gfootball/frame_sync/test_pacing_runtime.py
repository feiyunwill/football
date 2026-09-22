"""Actual TCP/files and loop ownership under an explicit controllable clock."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gfootball.engine_pool import EnginePool, EngineKey
from gfootball.owned_engine import create_owned_engine
from gfootball.frame_sync import local_runtime, client_logic, presentation_loop
from gfootball.frame_sync.frame_pacing import FramePacer
from gfootball.frame_sync.graphical_input import InputBuffer, BufferedControls
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import playback
from gfootball.frame_sync.presentation_state import LogicStateHolder
from gfootball.frame_sync.test_frame_pacing import Clock
from gfootball.frame_sync.test_match_archive import MatchOracle
from gfootball.frame_sync.test_client_logic_budget import Client, Engine


class PacingRuntimeTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.pool = EnginePool(max_live=2, idle_headless=0, idle_rendering=0)
    self.key = EngineKey.current(1280, 720)
    self.engines = []

  def tearDown(self):
    self.pool.close()
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertTrue(all(env.closed == 1 for env in self.engines))

  def factory(self, settings):
    def create():
      env = MatchOracle(settings)
      self.engines.append(env)
      return env
    return create_owned_engine(self.key, create, pool=self.pool)

  def test_slow_frame_preserves_sequential_authority_inputs_and_replay(self):
    clock, inputs, sampled, starts = Clock(), InputBuffer(), [], []
    pacer = FramePacer(clock_ns=clock)
    class Controls(BufferedControls):
      def wait(self, seconds):
        if self.buffer.quit_requested:
          return True
        return clock.wait(seconds)
    def sample(frame):
      value = inputs.sample(frame)
      sampled.append((frame, value.buttons))
      starts.append(clock.ns)
      return value
    def published(state):
      if state['frame'] == 0:
        clock.ns += 3_050_000_000
        inputs.feed(pressed_keys=('z',))
        inputs.feed()  # Released before the next simulation admission.
    path = str(self.root / 'paced.replay')
    with LocalPlayer(engine_factory=self.factory, record_path=path,
                     input_provider=sample, on_frame=published) as match:
      with mock.patch.object(local_runtime, 'FramePacer', return_value=pacer):
        result = match.run(4, controls=Controls(inputs))
    self.assertEqual(result['frames'], 4)
    self.assertEqual(result['pacing']['ticks'], 4)
    self.assertEqual(result['pacing']['missed_deadlines'], 29)
    self.assertEqual(sampled, [(0, 0), (1, 4), (2, 0), (3, 0)])
    self.assertEqual(starts, [0, 3_050_000_000, 3_100_000_000, 3_200_000_000])
    self.assertEqual(playback(path, engine_factory=self.factory)['digest'], result['last']['digest'])

  def test_quit_during_deadline_wait_saves_without_an_extra_simulation_frame(self):
    clock, inputs, sampled = Clock(), InputBuffer(), []
    pacer = FramePacer(clock_ns=clock)
    class Controls(BufferedControls):
      def wait(self, seconds):
        if seconds:
          self.buffer.request_quit()
          return self.buffer.wait_for_quit(0)
        return clock.wait(seconds)
    path = str(self.root / 'quit.replay')
    with LocalPlayer(engine_factory=self.factory, record_path=path,
                     input_provider=lambda frame: (sampled.append(frame), inputs.sample(frame))[1]) as match:
      with mock.patch.object(local_runtime, 'FramePacer', return_value=pacer):
        result = match.run(10, controls=Controls(inputs))
    self.assertEqual(sampled, [0])
    self.assertEqual(result['pacing']['ticks'], 1)
    self.assertEqual(playback(path, engine_factory=self.factory)['frames'], 1)

  def test_wait_failure_preserves_previous_recording_and_closes_both_owners(self):
    clock, inputs = Clock(), InputBuffer()
    class Controls(BufferedControls):
      def wait(self, seconds):
        if seconds:
          raise RuntimeError('Injected wait failure')
        return clock.wait(seconds)
    path = self.root / 'prior.replay'
    path.write_bytes(b'previous recording')
    with self.assertRaisesRegex(RuntimeError, 'Injected wait failure'):
      with LocalPlayer(engine_factory=self.factory, record_path=str(path), input_provider=inputs.sample) as match:
        with mock.patch.object(local_runtime, 'FramePacer', return_value=FramePacer(clock_ns=clock)):
          match.run(4, controls=Controls(inputs))
    self.assertEqual(path.read_bytes(), b'previous recording')
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_scheduler_construction_failure_closes_started_match(self):
    with LocalPlayer(engine_factory=self.factory) as match:
      with mock.patch.object(local_runtime, 'FramePacer', side_effect=MemoryError('scheduler allocation')):
        with self.assertRaisesRegex(MemoryError, 'scheduler allocation'):
          match.run(2)
      self.assertTrue(match.stats()['closed'])
      self.assertEqual(self.pool.stats()['live'], 0)

  def test_logic_scheduler_failure_releases_loop_lock_and_retained_inputs(self):
    loop = client_logic.ClientLogicLoop(Client(), Engine(), 1, lambda: [])
    with mock.patch.object(client_logic, 'FramePacer', side_effect=MemoryError('scheduler allocation')):
      with self.assertRaises(MemoryError):
        loop.run_loop()
    self.assertFalse(loop._loop_lock.locked())
    self.assertFalse(loop._running)
    self.assertEqual(loop.stats()['sampled_input_frames'], 0)
    loop.stop()

  def test_presentation_scheduler_failure_releases_loop_lock_without_owning_display(self):
    class Display:
      def set_state(self, state):
        raise AssertionError('No state should be restored')
      def render(self):
        raise AssertionError('No frame should be rendered')
    holder = LogicStateHolder()
    self.addCleanup(holder.close)
    loop = presentation_loop.PresentationLoop(Display(), holder)
    with mock.patch.object(presentation_loop, 'FramePacer', side_effect=MemoryError('scheduler allocation')):
      with self.assertRaises(MemoryError):
        loop.run_loop()
    self.assertFalse(loop._loop_lock.locked())
    self.assertFalse(loop._running)
    self.assertEqual(loop.stats()['render_count'], 0)
    loop.stop()


if __name__ == '__main__':
  unittest.main()
