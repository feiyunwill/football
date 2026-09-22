"""Planned actual GameEnv checks; requires the real native/Gym installation.

Rendering checks additionally require a working SDL/OpenGL display. No fallback
engine, fake import or skipped test can satisfy this suite.
"""
import tempfile
import unittest
from unittest import mock

import numpy as np

from gfootball.engine_pool import EnginePool, RendererBusyError
from gfootball.env import config, football_env_core


class _NativePoolFixture:
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory(prefix='football-engine-pool-native-')
    self.addCleanup(self.directory.cleanup)
    self.pool = EnginePool()
    self.addCleanup(self.pool.close)
    patch = mock.patch.object(football_env_core, 'ENGINE_POOL', self.pool)
    patch.start()
    self.addCleanup(patch.stop)
    self.values = dict(level='tests.corner_test', players=[], physics_steps_per_frame=10,
                       render_resolution_x=64, render_resolution_y=48,
                       tracesdir=self.directory.name, display_game_stats=False,
                       write_video=False, dump_full_episodes=False)

  def core(self, cls=football_env_core.FootballEnvCore, **values):
    core = cls(config.Config(dict(self.values, **values)))
    self.addCleanup(core.close, finalize=False)
    return core

class EnginePoolNativeTest(_NativePoolFixture, unittest.TestCase):
  def test_same_geometry_reuses_real_engine_with_new_cadence(self):
    first = self.core()
    native = first._env
    first.close()
    second = self.core(physics_steps_per_frame=5)
    self.assertIs(second._env, native)
    self.assertEqual(native.game_config.physics_steps_per_frame, 5)
    second.step([])
    second.close(False)
    with self.assertRaises(RuntimeError):
      native.get_info()
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_changed_geometry_retires_real_engine(self):
    first = self.core()
    native = first._env
    first.close()
    second = self.core(render_resolution_x=80, render_resolution_y=60)
    self.assertIsNot(second._env, native)
    with self.assertRaises(RuntimeError):
      native.get_info()
    self.assertEqual(second._env.game_config.render_resolution_x, 80)
    self.assertEqual(second._env.game_config.render_resolution_y, 60)
    second.step([])

  def test_reset_replaces_headless_geometry_and_adopts_new_cadence(self):
    core = self.core()
    native = core._env
    core._config['render_resolution_x'] = 80
    core._config['render_resolution_y'] = 60
    core._config['physics_steps_per_frame'] = 5
    core.reset()
    self.assertIsNot(core._env, native)
    self.assertEqual(core._env.game_config.render_resolution_x, 80)
    self.assertEqual(core._env.game_config.physics_steps_per_frame, 5)
    core.step([])

  def test_failed_constructor_releases_started_native_engine(self):
    allocated = []
    failure = ValueError('Injected failure after actual native reset')
    class FailedReset(football_env_core.FootballEnvCore):
      def _reset(self, animations, inc):
        super()._reset(animations, inc)
        allocated.append(self._env)
        raise failure
    with self.assertRaises(ValueError) as raised:
      self.core(cls=FailedReset)
    self.assertIs(raised.exception, failure)
    self.assertEqual(len(allocated), 1)
    with self.assertRaises(RuntimeError):
      allocated[0].get_info()
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_failed_reset_does_not_reenter_cache_on_normal_close(self):
    core = self.core()
    native = core._env
    core._config['physics_steps_per_frame'] = 0
    with self.assertRaises(ValueError):
      core.reset()
    core.close()
    self.assertEqual(self.pool.stats()['live'], 0)
    with self.assertRaises(RuntimeError):
      native.get_info()

  def test_closed_core_releases_observation_and_rejects_operations(self):
    core = self.core()
    self.assertIsNotNone(core.observation())
    core.close(False)
    self.assertIsNone(core._observation)
    core.close(False)
    for operation in (core.reset, core.observation, lambda: core.step([]),
                       lambda: core.get_state({}), lambda: core.render('rgb_array')):
      with self.assertRaisesRegex(RuntimeError, 'closed'):
        operation()


class EnginePoolRenderingTest(_NativePoolFixture, unittest.TestCase):
  def test_render_swap_preserves_match_and_produces_correct_pixels(self):
    core = self.core()
    core.step([])
    digest = core._env.get_state_digest()
    observation = core.observation()
    frame = core.render('rgb_array')
    self.assertEqual(frame.shape, (48, 64, 3))
    self.assertEqual(frame.dtype, np.uint8)
    self.assertEqual(core._env.get_state_digest(), digest)
    for name, value in observation.items():
      np.testing.assert_equal(core.observation()[name], value, err_msg=name)
    core.disable_render()
    self.assertTrue(self.pool.stats()['renderer_reserved'])
    self.assertEqual(core.render('rgb_array').shape, frame.shape)

  def test_busy_renderer_leaves_second_match_usable(self):
    first, second = self.core(), self.core()
    first.render('human')
    native = second._env
    state = second.get_state({})
    with self.assertRaises(RendererBusyError):
      second.render('human')
    self.assertIs(second._env, native)
    self.assertEqual(second.get_state({}), state)
    self.assertTrue(second._engine_reusable)
    second.step([])
    first.close()
    self.assertTrue(second.render('human'))

  def test_observation_failure_rolls_back_real_renderer_and_match(self):
    class FailedObservation(football_env_core.FootballEnvCore):
      fail_render_observation = False
      def _retrieve_observation(self):
        if self.fail_render_observation and self._use_rendering_engine:
          raise ValueError('Injected after actual native render')
        return super()._retrieve_observation()
    core = self.core(cls=FailedObservation)
    native, state = core._env, core.get_state({})
    observation, step_count, step = core._observation, core._step_count, core._step
    trace = core._trace
    core.fail_render_observation = True
    with self.assertRaisesRegex(ValueError, 'actual native render'):
      core.render('human')
    self.assertIs(core._env, native)
    self.assertIs(core._observation, observation)
    self.assertIs(core._trace, trace)
    self.assertEqual((core._step_count, core._step), (step_count, step))
    self.assertEqual(core.get_state({}), state)
    self.assertFalse(self.pool.stats()['renderer_reserved'])
    self.assertTrue(core._engine_reusable)
    core.step([])
    core.fail_render_observation = False
    self.assertTrue(core.render('human'))

  def test_cached_renderer_different_geometry_is_recreated(self):
    first = self.core()
    first.render('human')
    old_renderer = first._env
    first.close()
    second = self.core(render_resolution_x=80, render_resolution_y=60)
    self.assertEqual(second.render('rgb_array').shape, (60, 80, 3))
    self.assertIsNot(second._env, old_renderer)
    with self.assertRaises(RuntimeError):
      old_renderer.get_info()


if __name__ == '__main__':
  unittest.main()
