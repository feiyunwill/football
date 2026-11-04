"""Closed-loop and streaming contracts against real independent native engines."""
import hashlib
from itertools import repeat
import multiprocessing
import os
import unittest
from unittest import mock

import numpy as np

from gfootball.gymnasium import FootballEnv
from gfootball.profile_native_training import policy as heuristic
from gfootball.training_sampler import collect_episodes
from gfootball.training_workers import NativeWorkerPool, episode_seed


def config(cadence=2):
  return {'env_name': '11_vs_11_easy_stochastic', 'representation': 'simple115v2',
          'other_config_options': {'render_resolution_x': 160, 'render_resolution_y': 90,
                                   'physics_steps_per_frame': cadence, 'game_engine_random_seed': 0}}


class TrainingSamplerTest(unittest.TestCase):
  def test_partial_final_batch_hashes_only_finished_workers(self):
    with NativeWorkerPool(config(), workers=4) as pool:
      with mock.patch.object(pool, '_request', wraps=pool._request) as request:
        actual = collect_episodes(pool, (0, 1, 2, 3, 4), lambda obs, ctx: 0, max_steps=2)
      selections = [tuple(call.args[1]) for call in request.call_args_list if call.args[0] == 'digest']
      self.assertEqual(selections, [(0, 1, 2, 3), (0,)])
      # Reproduce the previous all-worker request behavior against real engines.
      original = pool.digests
      with mock.patch.object(pool, 'digests', side_effect=lambda selected: original()):
        baseline = collect_episodes(pool, (0, 1, 2, 3, 4), lambda obs, ctx: 0, max_steps=2)
      self.assertEqual(actual.episodes, baseline.episodes)
      self.assertEqual(actual.transitions, baseline.transitions)

  def test_latest_observation_stream_and_worker_count_replay(self):
    episodes = (9, 2, 7, 0, 5)
    expected = {}
    direct = FootballEnv(backend='native', **config())
    try:
      for episode in episodes:
        observation = direct.reset(seed=episode_seed(42, episode))[0]
        trace = []
        for step in range(12):
          action = heuristic(observation)
          following, reward, terminal, _, info = direct.step(action)
          trace.append((observation.copy(), action, following.copy(), reward, terminal,
                        info['agent_rewards'].copy(), info['score_reward']))
          observation = following
        expected[episode] = (trace, hashlib.sha256(direct._env._native.get_state_digest()).hexdigest())
    finally:
      direct.close()
    reference = None
    for count in (1, 2, 4):
      seen = {episode: 0 for episode in episodes}
      def choose(observation, context):
        self.assertFalse(observation.flags.writeable)
        self.assertEqual(context.seed, episode_seed(42, context.episode_id))
        row = expected[context.episode_id][0][context.step]
        np.testing.assert_array_equal(observation, row[0])
        return heuristic(observation)
      def consume(event):
        episode, step = event.context.episode_id, event.context.step
        self.assertEqual(step, seen[episode])
        seen[episode] += 1
        pre, action, post, reward, terminal, agents, score = expected[episode][0][step]
        np.testing.assert_array_equal(event.observation, pre)
        np.testing.assert_array_equal(event.following.observation, post)
        np.testing.assert_array_equal(event.following.agent_rewards, agents)
        self.assertEqual(event.actions, (action,))
        self.assertEqual((event.following.reward, event.following.terminated, event.following.score_reward),
                         (reward, terminal, score))
        self.assertEqual(event.following.truncated, step == 11 and not terminal)
        # Even deliberate callback mutation must not affect the next decision.
        event.following.observation.setflags(write=True)
        event.following.observation.fill(float('nan'))
      with NativeWorkerPool(config(), workers=count, base_seed=42) as pool:
        result = collect_episodes(pool, episodes, choose, max_steps=12, on_transition=consume)
        self.assertEqual(result.transitions, 60)
        self.assertEqual([row.episode_id for row in result.episodes], list(episodes))
        for row in result.episodes:
          self.assertEqual(row.kernel_sha256, expected[row.episode_id][1])
        comparable = result.episodes
        if reference is None: reference = comparable
        self.assertEqual(comparable, reference)
        self.assertTrue(all(value == 12 for value in seen.values()))
      self.assertEqual(pool.exit_codes, (0,) * count)

  def test_invalid_collection_preserves_pool(self):
    with NativeWorkerPool(config()) as pool:
      pool.reset({0: 0})
      before = pool.digests()
      for episodes in ((), (0, 0), (True,), (-1,), repeat(0)):
        with self.assertRaises(ValueError): collect_episodes(pool, episodes, lambda obs, ctx: 0)
        self.assertEqual(pool.digests(), before)
      for steps in (0, 4097, True):
        with self.assertRaises(ValueError): collect_episodes(pool, (0,), lambda obs, ctx: 0, max_steps=steps)
      self.assertEqual(pool.digests(), before)

  def test_policy_reusable_joint_buffer_is_detached_per_decision(self):
    kwargs = config()
    kwargs['number_of_left_players_agent_controls'] = 2
    reusable = np.zeros(2, dtype=np.int64)
    def choose(obs, context):
      reusable[:] = (context.episode_id % 19, (context.episode_id + context.step) % 19)
      return reusable
    seen = []
    with NativeWorkerPool(kwargs, workers=2) as pool:
      collect_episodes(pool, (1, 7), choose, max_steps=4, on_transition=seen.append)
    for event in seen:
      self.assertEqual(event.actions, (event.context.episode_id % 19,
                                       (event.context.episode_id + event.context.step) % 19))

  def test_callback_failure_closes_and_reaps_pool(self):
    def fail(observation, context): raise LookupError('policy failure')
    for policy, sink in ((fail, None), (lambda obs, ctx: 19, None),
                         (lambda obs, ctx: 0, lambda event: fail(None, None))):
      pool = NativeWorkerPool(config(), workers=2)
      try:
        with self.assertRaises((LookupError, ValueError)):
          collect_episodes(pool, (0, 1), policy, max_steps=2, on_transition=sink)
        self.assertTrue(pool.closed)
        self.assertTrue(all(code is not None for code in pool.exit_codes))
        self.assertFalse(set(pool.worker_pids) & {p.pid for p in multiprocessing.active_children()})
      finally:
        pool.close()

  def test_engine_terminal_precedes_horizon(self):
    kwargs = config(1000)
    kwargs['env_name'] = 'academy_empty_goal_close'
    with NativeWorkerPool(kwargs, workers=2) as pool:
      result = collect_episodes(pool, (0, 1, 2), lambda obs, ctx: 0, max_steps=64)
      self.assertTrue(all(row.terminated and not row.truncated and row.steps < 64 for row in result.episodes))
    with NativeWorkerPool(config()) as pool:
      result = collect_episodes(pool, (0,), lambda obs, ctx: 0, max_steps=1)
      self.assertTrue(result.episodes[0].truncated)
      self.assertFalse(result.episodes[0].terminated)

  @unittest.skipUnless(os.path.isdir('/proc/self/fd'), 'Linux process resource contract')
  def test_repeated_four_worker_collection_and_fd_cleanup(self):
    # First pool initializes multiprocessing's persistent resource tracker.
    with NativeWorkerPool(config()) as pool:
      collect_episodes(pool, (0,), lambda obs, ctx: 0, max_steps=1)
    baseline = len(os.listdir('/proc/self/fd'))
    child_baseline = {p.pid for p in multiprocessing.active_children()}
    reference = None
    for cycle in range(3):
      with NativeWorkerPool(config(), workers=4) as pool:
        for _ in range(3):
          result = collect_episodes(pool, (0, 1, 2, 3), lambda obs, ctx: 0, max_steps=8)
          if reference is None: reference = result.episodes
          self.assertEqual(result.episodes, reference)
        self.assertTrue(all(os.path.isdir(f'/proc/{pid}') for pid in pool.worker_pids))
      self.assertFalse(any(os.path.exists(f'/proc/{pid}') for pid in pool.worker_pids))
      self.assertEqual(len(os.listdir('/proc/self/fd')), baseline)
      self.assertEqual({p.pid for p in multiprocessing.active_children()}, child_baseline)


if __name__ == '__main__': unittest.main()
