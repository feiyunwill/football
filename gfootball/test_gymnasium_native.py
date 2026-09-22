"""Actual Gymnasium contracts, legacy compatibility and native ownership."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cv2
import gymnasium as gym
from gymnasium.utils.env_checker import check_env
import numpy as np

from gfootball.engine_pool import EnginePool
from gfootball.env import create_environment, football_env_core
from gfootball.gymnasium import FootballEnv


class GymnasiumNativeTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory(prefix='football-gymnasium-')
    self.addCleanup(self.directory.cleanup)
    self.pool = EnginePool()
    self.addCleanup(self.pool.close)
    patch = mock.patch.object(football_env_core, 'ENGINE_POOL', self.pool)
    patch.start()
    self.addCleanup(patch.stop)
    self.options = dict(render_resolution_x=160, render_resolution_y=90,
                        tracesdir=self.directory.name, display_game_stats=False)

  def make(self, **kwargs):
    options = dict(env_name='11_vs_11_easy_stochastic',
                   representation='simple115v2', other_config_options=self.options)
    options.update(kwargs)
    env = FootballEnv(**options)
    self.addCleanup(env.close)
    return env

  def test_official_checker_with_joint_actions_and_observation_wrappers(self):
    for representation in ('extracted', 'simple115', 'simple115v2'):
      for players in (1, 2):
        with self.subTest(representation=representation, players=players):
          env = self.make(representation=representation,
                          number_of_left_players_agent_controls=players,
                          stacked=representation == 'extracted',
                          rewards='scoring,checkpoints')
          check_env(env, skip_render_check=True)
          observation, info = env.reset(seed=19)
          self.assertTrue(env.observation_space.contains(observation))
          _, reward, terminated, truncated, info = env.step(env.action_space.sample())
          self.assertIs(type(reward), float)
          self.assertEqual(info['agent_rewards'].shape, (players,))
          self.assertEqual(reward, float(info['agent_rewards'].mean()))
          self.assertIs(type(terminated), bool)
          self.assertIs(type(truncated), bool)
          env.close()
    self.assertEqual(self.pool.stats()['leased'], 0)

  def test_seed_reproduces_native_state_and_does_not_mutate_global_rng(self):
    import random
    python_state, numpy_state = random.getstate(), np.random.get_state()
    env = self.make(rewards='scoring,checkpoints', stacked=True)
    def rollout(seed):
      observation, _ = env.reset(seed=seed)
      observations = [observation.copy()]
      for action in (1, 5, 13, 0, 4, 0, 14, 0):
        observations.append(env.step(action)[0].copy())
      native = env._env.unwrapped._env._env
      return observations, native.get_state_digest()
    first, digest = rollout(37)
    second, other = rollout(37)
    for a, b in zip(first, second):
      np.testing.assert_array_equal(a, b)
    self.assertEqual(digest, other)
    self.assertNotEqual(digest, rollout(38)[1])
    self.assertEqual(python_state, random.getstate())
    after = np.random.get_state()
    self.assertEqual(numpy_state[0], after[0])
    np.testing.assert_array_equal(numpy_state[1], after[1])
    self.assertEqual(numpy_state[2:], after[2:])

  def test_external_time_limit_truncates_and_match_clock_terminates(self):
    limited = gym.make('gfootball.gymnasium:GFootball-11_vs_11_easy_stochastic-SMM-v0',
                       max_episode_steps=2, other_config_options=self.options)
    self.addCleanup(limited.close)
    limited.reset(seed=2)
    self.assertEqual(limited.step(0)[2:4], (False, False))
    self.assertEqual(limited.step(0)[2:4], (False, True))
    limited.close()
    env = self.make(env_name='tests.second_half')
    env.reset(seed=2)
    for _ in range(32):
      observation, _, terminated, truncated, _ = env.step(0)
      if terminated:
        break
    self.assertTrue(terminated)
    self.assertFalse(truncated)
    self.assertTrue(env.observation_space.contains(observation))
    self.assertIsNone(env.render())
    with self.assertRaises(gym.error.ResetNeeded):
      env.step(0)
    env.reset(seed=2)
    self.assertEqual(env.step(0)[2:4], (False, False))

  def test_invalid_requests_preserve_live_state_and_close_is_idempotent(self):
    env = self.make()
    with self.assertRaises(gym.error.ResetNeeded):
      env.step(0)
    env.reset(seed=4)
    native = env._env.unwrapped._env._env
    digest = native.get_state_digest()
    for action in (-1, 19, 1.2, [0, 1]):
      with self.assertRaises(ValueError):
        env.step(action)
    for seed in (-1, True, 1.5, '4'):
      with self.assertRaises(ValueError):
        env.reset(seed=seed)
    with self.assertRaises(ValueError):
      env.reset(options={'unknown': 1})
    self.assertEqual(digest, native.get_state_digest())
    env.close()
    env.close()
    with self.assertRaises(RuntimeError):
      env.reset()
    self.assertEqual(self.pool.stats()['leased'], 0)

  def test_actual_rgb_array_and_terminal_frame(self):
    env = self.make(env_name='tests.second_half', representation='pixels',
                    render_mode='rgb_array')
    observation, _ = env.reset(seed=5)
    self.assertEqual(observation.shape, (72, 96, 3))
    for _ in range(32):
      _, _, terminated, _, _ = env.step(0)
      if terminated:
        break
    self.assertTrue(terminated)
    frame = env.render()
    self.assertEqual(frame.shape, (90, 160, 3))
    self.assertEqual(frame.dtype, np.uint8)
    self.assertGreater(int(frame.max()) - int(frame.min()), 20)
    evidence = os.environ.get('FOOTBALL_GYMNASIUM_EVIDENCE_DIR')
    if evidence:
      path = Path(evidence) / 'terminal-rgb.png'
      self.assertTrue(cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)))
    env.close()
    self.assertFalse(self.pool.stats()['renderer_reserved'])

  def test_legacy_factory_keeps_four_results_and_wrapper_snapshot(self):
    env = create_environment(env_name='11_vs_11_easy_stochastic',
                             representation='extracted', stacked=True,
                             rewards='scoring,checkpoints',
                             other_config_options=self.options)
    self.addCleanup(env.close)
    observation = env.reset()
    self.assertIsInstance(observation, np.ndarray)
    state = env.get_state()
    expected = env.step(1)
    self.assertEqual(len(expected), 4)
    env.set_state(state)
    actual = env.step(1)
    np.testing.assert_array_equal(expected[0], actual[0])
    self.assertEqual(expected[1:3], actual[1:3])

  def test_wrapper_constructor_error_releases_actual_native_engine(self):
    # 2026-09-10: also cover failure after the real renderer was acquired.
    # with self.assertRaisesRegex(ValueError, 'Unsupported representation'):
    #   create_environment(env_name='11_vs_11_easy_stochastic',
    #                      representation='invalid', other_config_options=self.options)
    # self.assertEqual(self.pool.stats()['leased'], 0)
    # self.assertEqual(self.pool.stats()['live'], 0)
    for render in (False, True):
      with self.assertRaisesRegex(ValueError, 'Unsupported representation'):
        create_environment(env_name='11_vs_11_easy_stochastic',
                           representation='invalid', render=render,
                           other_config_options=self.options)
      self.assertEqual(self.pool.stats()['leased'], 0)
      # 2026-09-10: enabling rendering may retain the valid headless predecessor
      # in the bounded pool. Failed renderers must be retired, and pool closure
      # must release that predecessor as well.
      # self.assertEqual(self.pool.stats()['live'], 0)
      self.assertEqual(self.pool.stats()['idle_rendering'], 0)
      self.assertLessEqual(self.pool.stats()['live'], 1)
      self.assertFalse(self.pool.stats()['renderer_reserved'])
    self.pool.close()
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_post_step_failure_releases_engine_and_preserves_primary_error(self):
    env = self.make()
    env.reset(seed=5)
    native = env._env.unwrapped._env._env
    step, close = env._env.step, env._env.close
    failure = ValueError('Failure after a real native transition')
    def fail_step(action):
      step(action)
      raise failure
    def fail_cleanup(**kwargs):
      close(**kwargs)
      raise RuntimeError('Secondary cleanup failure')
    with mock.patch.object(env._env, 'step', side_effect=fail_step), \
         mock.patch.object(env._env, 'close', side_effect=fail_cleanup):
      with self.assertRaises(ValueError) as raised:
        env.step(0)
    self.assertIs(raised.exception, failure)
    with self.assertRaises(RuntimeError):
      native.get_info()
    self.assertEqual(self.pool.stats()['leased'], 0)
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_gymnasium_vector_env_owns_two_independent_matches(self):
    vector = gym.vector.SyncVectorEnv([self.make, self.make])
    self.addCleanup(vector.close)
    observation, _ = vector.reset(seed=[9, 10])
    self.assertEqual(observation.shape, (2, 115))
    _, reward, terminated, truncated, _ = vector.step(np.array([0, 1]))
    self.assertEqual(reward.shape, (2,))
    self.assertFalse(terminated.any() or truncated.any())
    self.assertEqual(self.pool.stats()['leased'], 2)
    vector.close()
    self.assertEqual(self.pool.stats()['leased'], 0)


if __name__ == '__main__':
  unittest.main()
