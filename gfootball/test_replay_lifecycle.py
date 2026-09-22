# 2026-09-09: driver interface contracts and actual private replay file ownership.
# Driver call recorders below do not simulate GameEnv or prove native replay identity.
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gfootball import replay_io
from gfootball.replay_io import (
    AtomicReplayFile, ReplayExhausted, ReplayFormatError, ReplayReader,
    drive_replay, temporary_replay_directory,
)
from gfootball.test_recording_buffers import ADAPTER
from gfootball.test_replay_io import trace


class DriverCalls:
  def __init__(self, *, done_at=None, failure=None, error=None, close_error=None, shutdown_error=None):
    self.done_at, self.failure = done_at, failure
    self.error, self.close_error, self.shutdown_error = error, close_error, shutdown_error
    self.events = []
    self.frames = 0

  def _record(self, event):
    self.events.append(event)
    if event == self.failure:
      raise self.error

  def render(self):
    self._record('render')

  def reset(self):
    self._record('reset')

  def step(self, actions):
    if actions != []:
      raise AssertionError('Replay should be driven by its configured players')
    self._record('step')
    self.frames += 1
    return None, None, self.frames == self.done_at, {}

  def write_dump(self, name):
    self.events.append(('dump', name))
    if self.shutdown_error is not None:
      raise self.shutdown_error

  def close(self, *, finalize):
    self.events.append(('close', finalize))
    if self.close_error is not None:
      raise self.close_error


class ReplayLifecycleTest(unittest.TestCase):
  def test_natural_termination_finalizes_once_and_stops_at_exact_frame(self):
    environment = DriverCalls(done_at=3)
    config = {'seed': 42}
    factories = []

    def factory(received):
      factories.append(received)
      return environment

    result = drive_replay(factory, config, 10)
    self.assertEqual(result, dict(frames=3, episode_done=True, source_exhausted=False))
    self.assertEqual(factories, [config])
    self.assertIs(factories[0], config)
    self.assertEqual(environment.events, ['render', 'reset', 'step', 'step', 'step', ('close', True)])

  def test_frame_budget_stops_ai_only_or_override_players_without_waiting_for_eof(self):
    environment = DriverCalls()
    result = drive_replay(lambda config: environment, {}, 4, render=False)
    self.assertEqual(result, dict(frames=4, episode_done=False, source_exhausted=True))
    self.assertEqual(environment.events, ['reset'] + ['step'] * 4 + [('close', True)])

  def test_bad_arguments_are_rejected_before_factory_resources_open(self):
    factory = mock.Mock()
    for count, render in ((0, True), (True, True), (1.0, True), (1000001, True), (1, 1)):
      with self.assertRaises(ValueError):
        drive_replay(factory, {}, count, render=render)
    factory.assert_not_called()

  def test_render_reset_and_step_failures_abort_once_preserving_original(self):
    for operation in ('render', 'reset', 'step'):
      original = OSError('original ' + operation)
      environment = DriverCalls(failure=operation, error=original)
      with self.assertRaises(OSError) as caught:
        drive_replay(lambda config: environment, {}, 4)
      self.assertIs(caught.exception, original)
      self.assertEqual(environment.events[-1], ('close', False))
      self.assertEqual(sum(isinstance(event, tuple) and event[0] == 'close' for event in environment.events), 1)
      self.assertEqual(environment.events.count('step'), int(operation == 'step'))

  def test_premature_source_eof_is_an_error_and_aborts_incomplete_output(self):
    original = ReplayExhausted('shortened input')
    environment = DriverCalls(failure='step', error=original)
    with self.assertRaises(ReplayFormatError) as caught:
      drive_replay(lambda config: environment, {}, 2, render=False)
    self.assertIs(caught.exception.__cause__, original)
    self.assertEqual(environment.events, ['reset', 'step', ('close', False)])

  def test_successful_driver_reports_finalize_failure(self):
    original = OSError('commit failed')
    environment = DriverCalls(done_at=1, close_error=original)
    with self.assertRaises(OSError) as caught:
      drive_replay(lambda config: environment, {}, 3)
    self.assertIs(caught.exception, original)
    self.assertEqual(environment.events[-1], ('close', True))

  def test_cleanup_error_does_not_replace_original_failure(self):
    original = ValueError('bad simulation input')
    environment = DriverCalls(failure='step', error=original, close_error=OSError('close failed'))
    with self.assertRaises(ValueError) as caught:
      drive_replay(lambda config: environment, {}, 2)
    self.assertIs(caught.exception, original)
    if hasattr(original, 'add_note'):
      self.assertIn('Replay environment cleanup also failed.', original.__notes__)

  def test_interrupt_is_propagated_after_shutdown_attempt_and_abort(self):
    for during in ('reset', 'step'):
      original = KeyboardInterrupt()
      environment = DriverCalls(failure=during, error=original, shutdown_error=OSError('shutdown failed'))
      with self.assertRaises(KeyboardInterrupt) as caught:
        drive_replay(lambda config: environment, {}, 2, render=False)
      self.assertIs(caught.exception, original)
      self.assertEqual(environment.events[-1], ('close', False))
      self.assertEqual(environment.events.count(('dump', 'shutdown')), int(during == 'step'))
      if during == 'step' and hasattr(original, 'add_note'):
        self.assertIn('Interrupted replay shutdown recording failed.', original.__notes__)

  def test_factory_exception_is_not_replaced_by_uninitialized_close(self):
    original = RuntimeError('construction failed')
    factory = mock.Mock(side_effect=original)
    with self.assertRaises(RuntimeError) as caught:
      drive_replay(factory, {}, 2)
    self.assertIs(caught.exception, original)
    factory.assert_called_once_with({})

  def test_real_atomic_file_reader_and_private_directory_are_closed_in_order(self):
    with tempfile.TemporaryDirectory(prefix='football-replay-sibling-test-') as outside:
      sentinel = Path(outside) / 'keep.txt'
      sentinel.write_bytes(b'owned by another caller')
      with temporary_replay_directory() as directory:
        self.assertEqual(directory.parent, Path(tempfile.gettempdir()).resolve())
        target = directory / 'input.dump'
        with AtomicReplayFile(target, 65536) as output:
          output.dump(trace(0, config=True))
          output.dump(trace(1))
        with ReplayReader(target, action_adapter=ADAPTER) as reader:
          self.assertEqual([state['frame_cnt'] for state in reader], [0, 1])
        self.assertFalse(reader.stats()['open'])
        self.assertEqual(output.budget.stats()['active_dumps'], 0)
      self.assertFalse(directory.exists())
      self.assertEqual(sentinel.read_bytes(), b'owned by another caller')

  def test_private_directory_is_removed_after_failure_with_live_payload(self):
    original = ValueError('conversion failed')
    with self.assertRaises(ValueError) as caught:
      with temporary_replay_directory() as directory:
        with AtomicReplayFile(directory / 'input.dump', 65536) as output:
          output.dump(trace(0, config=True))
        raise original
    self.assertIs(caught.exception, original)
    self.assertFalse(directory.exists())

  def test_directory_cleanup_failure_preserves_body_error_and_can_be_retried(self):
    with tempfile.TemporaryDirectory(prefix='football-replay-parent-test-') as parent:
      original = ValueError('playback failed')
      with mock.patch.object(replay_io.tempfile, 'gettempdir', return_value=parent):
        with self.assertRaises(ValueError) as caught:
          # 2026-09-09: lexical patch ownership keeps the failure active during
          # directory cleanup and restores rmtree before parent cleanup.
          # failure.start(); self.addCleanup(failure.stop); ...; failure.stop()
          with mock.patch.object(replay_io.shutil, 'rmtree', side_effect=OSError('in use')):
            with temporary_replay_directory() as directory:
              (directory / 'keep-until-cleanup').write_bytes(b'partial')
              raise original
      self.assertIs(caught.exception, original)
      self.assertTrue(directory.is_dir())
      if hasattr(original, 'add_note'):
        self.assertIn('Replay temporary directory cleanup also failed.', original.__notes__)
      # TemporaryDirectory owns the checked parent and removes the failed child.


if __name__ == '__main__':
  unittest.main()
