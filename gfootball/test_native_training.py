"""C++ training parity against the maintained Python implementation."""
import random
import multiprocessing
import threading
import unittest
from unittest import mock

import gymnasium as gym
from gymnasium.utils.env_checker import check_env
import numpy as np

from gfootball.engine_pool import ENGINE_POOL
from gfootball.gymnasium import FootballEnv


class NativeTrainingTest(unittest.TestCase):
  def make(self, backend='native', **kwargs):
    values = dict(env_name='11_vs_11_easy_stochastic', representation='simple115v2',
                  other_config_options=dict(game_engine_random_seed=42,
                                            render_resolution_x=160, render_resolution_y=90,
                                            display_game_stats=False))
    values.update(kwargs)
    env = FootballEnv(backend=backend, **values)
    self.addCleanup(env.close)
    return env

  @staticmethod
  def digest(env, backend):
    if backend == 'native':
      return env._env._native.get_state_digest()
    return env._env.unwrapped._env._env.get_state_digest()

  def test_python_parity_for_both_teams_sparse_and_joint_actions(self):
    for level, left, right, steps in (
        ('11_vs_11_easy_stochastic', 1, 0, 40),
        ('11_vs_11_easy_stochastic', 0, 2, 40),
        ('11_vs_11_easy_stochastic', 11, 0, 16),
        ('academy_empty_goal_close', 1, 0, 80),
        ('tests.second_half', 2, 0, 32)):
      with self.subTest(level=level, left=left, right=right):
        options = dict(env_name=level, number_of_left_players_agent_controls=left,
                       number_of_right_players_agent_controls=right)
        reference, native = self.make('python', **options), self.make(**options)
        a, b = reference.reset(seed=19)[0], native.reset(seed=19)[0]
        np.testing.assert_array_equal(a, b)
        self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
        for frame in range(steps):
          value = frame % 19
          action = value if left + right == 1 else np.array(
              [(frame + player) % 19 for player in range(left + right)], dtype=np.int64)
          a, b = reference.step(action), native.step(action)
          np.testing.assert_array_equal(a[0], b[0])
          self.assertEqual(a[1:4], b[1:4])
          np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
          self.assertEqual(a[4]['score_reward'], b[4]['score_reward'])
          self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
          if b[2]:
            break
        if level == 'tests.second_half':
          self.assertTrue(b[2])
        reference.close()
        native.close()

  def test_checker_seed_replay_invalid_action_and_lifetime(self):
    before = ENGINE_POOL.stats()['leased']
    env = self.make()
    check_env(env, skip_render_check=True)
    python_rng, numpy_rng = random.getstate(), np.random.get_state()
    def rollout():
      rows = [env.reset(seed=37)[0].copy()]
      for action in (1, 5, 13, 0, 4, 0, 14, 18):
        rows.append(env.step(action)[0].copy())
      return rows, self.digest(env, 'native')
    first, digest = rollout()
    second, other = rollout()
    np.testing.assert_array_equal(first, second)
    self.assertEqual(digest, other)
    self.assertEqual(python_rng, random.getstate())
    after = np.random.get_state()
    np.testing.assert_array_equal(numpy_rng[1], after[1])
    self.assertEqual(numpy_rng[0], after[0])
    self.assertEqual(numpy_rng[2:], after[2:])
    for action in (-1, 19, 1.5, [0, 1]):
      with self.assertRaises(ValueError):
        env.step(action)
    self.assertEqual(digest, self.digest(env, 'native'))
    # Native joint validation must reject the entire batch before mutation.
    with self.assertRaises(ValueError):
      env._env._native.step([19])
    self.assertEqual(digest, self.digest(env, 'native'))
    env.close()
    env.close()
    self.assertEqual(ENGINE_POOL.stats()['leased'], before)
    with self.assertRaises(RuntimeError):
      env.reset()

  def test_native_does_not_call_python_step_or_observation_conversion(self):
    from gfootball.env import football_env_core, wrappers
    env = self.make()
    with mock.patch.object(football_env_core.FootballEnvCore, 'step', side_effect=AssertionError), \
         mock.patch.object(wrappers.Simple115StateWrapper, 'convert_observation', side_effect=AssertionError):
      env.reset(seed=2)
      env.step(0)

  def test_time_limit_and_finished_match(self):
    raw = self.make(env_name='tests.second_half')
    env = gym.wrappers.TimeLimit(raw, max_episode_steps=2)
    env.reset(seed=2)
    self.assertEqual(env.step(0)[2:4], (False, False))
    self.assertEqual(env.step(0)[2:4], (False, True))
    raw.reset(seed=2)
    for _ in range(32):
      result = raw.step(0)
      if result[2]:
        break
    self.assertTrue(result[2])
    self.assertFalse(result[3])
    with self.assertRaises(gym.error.ResetNeeded):
      raw.step(0)
    self.assertIsNone(raw.render())

  def test_reject_unsupported_options_without_leaking(self):
    before = ENGINE_POOL.stats()['leased']
    # 2026-10-14: checkpoints are supported; scoring remains required.
    # for options in (dict(representation='pixels'), dict(rewards='scoring,checkpoints'),
    for options in (dict(representation='pixels'), dict(rewards='checkpoints'),
                    # 2026-10-14: numeric frame stacking is supported; only boolean flags are valid.
                    # dict(stacked=True),
                    dict(stacked=1), dict(render_mode='human'), dict(extra_players=[]),
                    dict(other_config_options={'write_video': True}),
                    dict(env_name='tests.multiagent_wrapper')):
      with self.subTest(options=options), self.assertRaises(ValueError):
        self.make(**options)
    self.assertEqual(ENGINE_POOL.stats()['leased'], before)

  def test_owned_engine_rejects_wrong_thread(self):
    env = self.make()
    env.reset(seed=3)
    errors = []
    def wrong_thread():
      try:
        env._env._native.step([0])
      except RuntimeError as error:
        errors.append(str(error))
    thread = threading.Thread(target=wrong_thread)
    thread.start()
    thread.join()
    self.assertEqual(len(errors), 1)
    env.step(0)

  def test_public_native_api_rejects_wrong_thread_before_mutating_lifetime(self):
    env = self.make()
    env.reset(seed=3)
    digest = self.digest(env, 'native')
    leased = ENGINE_POOL.stats()['leased']
    rng_state = env.np_random.bit_generator.state
    for operation in (lambda: env.step(0), lambda: env.reset(seed=7), env.close,
                      env.render, lambda: env.step_many([0])):
      errors = []
      def invoke():
        try:
          operation()
        except RuntimeError as error:
          errors.append(str(error))
      thread = threading.Thread(target=invoke)
      thread.start()
      thread.join(timeout=5)
      self.assertFalse(thread.is_alive())
      self.assertEqual(len(errors), 1)
      self.assertFalse(env._closed)
      self.assertFalse(env._needs_reset)
      self.assertEqual(rng_state, env.np_random.bit_generator.state)
      self.assertEqual(digest, self.digest(env, 'native'))
      self.assertEqual(leased, ENGINE_POOL.stats()['leased'])
    env.step(0)
    env.close()
    self.assertEqual(leased - 1, ENGINE_POOL.stats()['leased'])

  @unittest.skipUnless('fork' in multiprocessing.get_all_start_methods(), 'fork is Unix-specific')
  def test_public_native_api_rejects_fork_before_touching_inherited_resources(self):
    env = self.make()
    env.reset(seed=3)
    digest = self.digest(env, 'native')
    rng_state = env.np_random.bit_generator.state
    context = multiprocessing.get_context('fork')
    receiver, sender = context.Pipe(duplex=False)
    def child():
      try:
        for operation in (lambda: env.step(0), lambda: env.reset(seed=7), env.close,
                          env.render, lambda: env.step_many([0])):
          try:
            operation()
          except RuntimeError:
            pass
          else:
            raise AssertionError('Inherited native operation was accepted')
          if env._closed or env._needs_reset or env.np_random.bit_generator.state != rng_state:
            raise AssertionError('Inherited ownership rejection changed public state')
        sender.send(None)
      except BaseException as error:
        sender.send(repr(error))
      finally:
        sender.close()
    process = context.Process(target=child)
    try:
      process.start()
      sender.close()
      self.assertTrue(receiver.poll(5), 'Child ownership rejection did not finish')
      self.assertIsNone(receiver.recv())
      process.join(5)
      self.assertEqual(process.exitcode, 0)
    finally:
      if process.is_alive():
        process.terminate()
      process.join()
      receiver.close()
      sender.close()
    self.assertEqual(digest, self.digest(env, 'native'))
    env.step(0)

  def test_constructor_and_mutating_reset_failure_refund_native_reservation(self):
    from gfootball.owned_engine import OwnedEngine
    invoke = OwnedEngine._invoke
    class ResetFailure(RuntimeError):
      pass
    def reject_reset(owner, name, *args, **kwargs):
      if name == 'reset':
        raise ResetFailure('constructor reset failed')
      return invoke(owner, name, *args, **kwargs)
    leased = ENGINE_POOL.stats()['leased']
    with mock.patch.object(OwnedEngine, '_invoke', reject_reset):
      with self.assertRaisesRegex(ResetFailure, 'constructor reset failed'):
        self.make()
    self.assertEqual(leased, ENGINE_POOL.stats()['leased'])
    env = self.make()
    env.reset(seed=3)
    def fail_after_mutation(owner, name, *args, **kwargs):
      if name == 'reset':
        invoke(owner, 'step', [0])
        raise ResetFailure('mutating reset failed')
      return invoke(owner, name, *args, **kwargs)
    with mock.patch.object(OwnedEngine, '_invoke', fail_after_mutation):
      with self.assertRaisesRegex(ResetFailure, 'mutating reset failed'):
        env.reset(seed=7)
    self.assertEqual(leased, ENGINE_POOL.stats()['leased'])
    self.assertTrue(env._closed)
    with self.assertRaises(RuntimeError):
      env.reset(seed=3)

  def test_independent_out_of_play_and_possession_termination_match_python(self):
    from gfootball.env.scenario_builder import Role, Team
    import gfootball.scenarios.academy_run_to_score as run_to_score
    for flag in ('end_episode_on_out_of_play', 'end_episode_on_possession_change'):
      with self.subTest(flag=flag):
        possession = flag.endswith('possession_change')
        def build(builder):
          if possession:
            run_to_score.build_scenario(builder)
          else:
            builder.SetBallPosition(0.0, 0.40)
            builder.SetTeam(Team.e_Left)
            builder.AddPlayer(-1.0, 0.0, Role.e_PlayerRole_GK, lazy=True)
            builder.AddPlayer(0.0, 0.39, Role.e_PlayerRole_CF, lazy=True)
            builder.SetTeam(Team.e_Right)
            builder.AddPlayer(-1.0, 0.0, Role.e_PlayerRole_GK, lazy=True)
          config = builder.config()
          config.game_duration = 600
          config.end_episode_on_score = False
          config.end_episode_on_out_of_play = not possession
          config.end_episode_on_possession_change = possession
          config.offsides = False
        with mock.patch('gfootball.scenarios.academy_empty_goal_close.build_scenario', build):
          options = dict(env_name='academy_empty_goal_close', other_config_options=dict(
              game_engine_random_seed=42, action_set='v2'))
          reference, native = self.make('python', **options), self.make(**options)
          np.testing.assert_array_equal(reference.reset(seed=7)[0], native.reset(seed=7)[0])
          previous_owner, previous_mode = -1, -1
          for frame in range(600):
            a, b = reference.step(19 if possession else 7), native.step(19 if possession else 7)
            np.testing.assert_array_equal(a[0], b[0])
            self.assertEqual(a[1:4], b[1:4])
            self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
            owner, mode = int(np.argmax(b[0][94:97])) - 1, int(np.argmax(b[0][108:115]))
            if b[2]:
              if possession:
                self.assertNotEqual(owner, -1)
                self.assertNotEqual(previous_owner, -1)
                self.assertNotEqual(owner, previous_owner)
              else:
                self.assertEqual(previous_mode, 0)
                self.assertNotEqual(mode, 0)
              break
            if owner != -1:
              previous_owner = owner
            previous_mode = mode
          else:
            self.fail('Scenario did not trigger ' + flag)
          self.assertLess(frame, 599, 'Termination must occur before the match clock limit')
          self.assertFalse(b[3])
          reference.close()
          native.close()

  def test_both_layouts_match_python_for_full_sparse_rotated_scalar_and_batch(self):
    for level, left, right in (('11_vs_11_easy_stochastic', 2, 0),
                               ('academy_empty_goal_close', 1, 0),
                               ('academy_empty_goal_close', 0, 1),
                               ('tests.second_half', 2, 0)):
      origins = {}
      for representation in ('simple115', 'simple115v2'):
        with self.subTest(level=level, left=left, right=right, representation=representation):
          options = dict(env_name=level, representation=representation,
                         number_of_left_players_agent_controls=left,
                         number_of_right_players_agent_controls=right)
          reference, native = self.make('python', **options), self.make(**options)
          a, b = reference.reset(seed=31)[0], native.reset(seed=31)[0]
          np.testing.assert_array_equal(a, b)
          self.assertEqual(b.dtype, np.float32)
          self.assertTrue(np.isfinite(b).all())
          origins[representation] = b.copy()
          for frame in range(12):
            action = frame % 19 if left + right == 1 else np.array(
                [(frame + player) % 19 for player in range(left + right)], dtype=np.int64)
            a, b = reference.step(action), native.step(action)
            np.testing.assert_array_equal(a[0], b[0])
            self.assertEqual(a[1:4], b[1:4])
            self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
            if b[2]:
              break
          reference.reset(seed=31)
          native.reset(seed=31)
          actions = np.array([[(frame + player) % 19 for player in range(left + right)]
                              for frame in range(16)], dtype=np.int64)
          expected = []
          for row in actions:
            expected.append(reference.step(int(row[0]) if left + right == 1 else row))
            if expected[-1][2]:
              break
          result = native.step_many(actions)
          np.testing.assert_array_equal(result[0], np.stack([row[0] for row in expected]))
          np.testing.assert_array_equal(result[1], [row[1] for row in expected])
          np.testing.assert_array_equal(result[2], [row[2] for row in expected])
          np.testing.assert_array_equal(result[4]['agent_rewards'],
                                        np.stack([row[4]['agent_rewards'] for row in expected]))
          self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
          reference.close()
          native.close()
      if level == '11_vs_11_easy_stochastic':
        np.testing.assert_array_equal(origins['simple115'], origins['simple115v2'])
      else:
        self.assertFalse(np.array_equal(origins['simple115'], origins['simple115v2']),
                         'Sparse layouts must use distinct padding positions')

  @staticmethod
  def checkpoint_wrapper(reference):
    from gfootball.env.wrappers import CheckpointRewardWrapper
    wrapper = reference._env
    while not isinstance(wrapper, CheckpointRewardWrapper):
      wrapper = wrapper.env
    return wrapper

  @staticmethod
  def checkpoint_scene(builder, right=False, score_end=False):
    from gfootball.env.scenario_builder import Role, Team
    config = builder.config()
    config.game_duration = 400
    config.deterministic = True
    config.end_episode_on_score = score_end
    config.end_episode_on_possession_change = False
    config.end_episode_on_out_of_play = False
    config.offsides = False
    builder.SetBallPosition(-0.4 if right else 0.4, 0.0)
    builder.SetTeam(Team.e_Left)
    if right:
      builder.AddPlayer(0.5, 0.3, Role.e_PlayerRole_GK, lazy=True)
    else:
      builder.AddPlayer(-1.0, 0.0, Role.e_PlayerRole_GK, lazy=True)
      builder.AddPlayer(0.38, 0.0, Role.e_PlayerRole_CF, lazy=True)
    builder.SetTeam(Team.e_Right)
    if right:
      builder.AddPlayer(-1.0, 0.0, Role.e_PlayerRole_GK, lazy=True)
      builder.AddPlayer(0.38, 0.0, Role.e_PlayerRole_CF, lazy=True)
    else:
      builder.AddPlayer(0.5, 0.3, Role.e_PlayerRole_GK, lazy=True)

  def test_checkpoint_dense_rewards_match_python_and_reset_for_both_views(self):
    for left, right, representation in ((1, 0, 'simple115'), (2, 0, 'simple115v2'),
                                         (0, 1, 'simple115v2'), (0, 2, 'simple115')):
      with self.subTest(left=left, right=right, representation=representation):
        def build(builder):
          self.checkpoint_scene(builder, right=bool(right))
        with mock.patch('gfootball.scenarios.academy_empty_goal_close.build_scenario', build):
          options = dict(env_name='academy_empty_goal_close', representation=representation,
                         rewards='scoring,checkpoints', number_of_left_players_agent_controls=left,
                         number_of_right_players_agent_controls=right)
          reference, native = self.make('python', **options), self.make(**options)
          reference.reset(seed=7)
          native.reset(seed=7)
          expected = []
          action = 0 if left + right == 1 else np.zeros(left + right, dtype=np.int64)
          for frame in range(10):
            a, b = reference.step(action), native.step(action)
            expected.append(a)
            np.testing.assert_array_equal(a[0], b[0])
            np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
            self.assertEqual(a[1:4], b[1:4])
            self.assertEqual(a[4]['score_reward'], 0)
            self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
          counts = self.checkpoint_wrapper(reference)._collected_checkpoints
          self.assertEqual(max(counts.values()), 5)
          self.assertTrue(any(row[1] > 0 for row in expected))
          self.assertEqual(expected[-1][1], 0)
          digest = self.digest(native, 'native')
          invalid = np.zeros((2, left + right), dtype=np.int64)
          invalid[-1, -1] = 19
          with self.assertRaises(ValueError):
            native.step_many(invalid)
          self.assertEqual(digest, self.digest(native, 'native'))
          a, b = reference.step(action), native.step(action)
          np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
          reference.reset(seed=7)
          native.reset(seed=7)
          result = native.step_many(np.zeros((10, left + right), dtype=np.int64))
          np.testing.assert_array_equal(result[0], np.stack([row[0] for row in expected]))
          np.testing.assert_array_equal(result[1], [row[1] for row in expected])
          np.testing.assert_array_equal(result[4]['agent_rewards'],
                                        np.stack([row[4]['agent_rewards'] for row in expected]))
          reference.close()
          native.close()

  def test_checkpoint_goal_fills_remaining_credit_for_each_agent(self):
    for left, right in ((2, 0), (0, 2)):
      with self.subTest(left=left, right=right):
        def build(builder):
          self.checkpoint_scene(builder, right=bool(right), score_end=True)
        with mock.patch('gfootball.scenarios.academy_empty_goal_close.build_scenario', build):
          options = dict(env_name='academy_empty_goal_close', rewards='checkpoints,scoring',
                         number_of_left_players_agent_controls=left,
                         number_of_right_players_agent_controls=right)
          reference, native = self.make('python', **options), self.make(**options)
          reference.reset(seed=7)
          native.reset(seed=7)
          # First claim only the five near midfield checkpoints, then shoot.
          # Let the actual player acquire the ball before claiming partial credit.
          for _ in range(10):
            a = reference.step(np.zeros(2, dtype=np.int64))
            b = native.step(np.zeros(2, dtype=np.int64))
            np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
          initial = self.checkpoint_wrapper(reference)._collected_checkpoints
          self.assertEqual(max(initial.values()), 5)
          for frame in range(120):
            before = dict(self.checkpoint_wrapper(reference)._collected_checkpoints)
            action = np.full(2, 12 if frame % 5 == 0 else 5, dtype=np.int64)
            a, b = reference.step(action), native.step(action)
            np.testing.assert_array_equal(a[0], b[0])
            np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
            self.assertEqual(a[1:4], b[1:4])
            self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
            if b[2]:
              self.assertEqual(b[4]['score_reward'], -1 if right else 1)
              expected = np.array([1 + 0.1 * (10 - before.get(agent, 0)) for agent in range(2)],
                                  dtype=np.float32)
              np.testing.assert_array_equal(expected, b[4]['agent_rewards'])
              self.assertTrue(any(0 < value < 10 for value in before.values()))
              self.assertTrue(all(value == 10 for value in self.checkpoint_wrapper(reference)._collected_checkpoints.values()))
              break
          else:
            self.fail('Checkpoint goal fixture did not score')
          reference.close()
          native.close()

  def test_native_frame_stack_matches_python_across_views_layouts_and_rewards(self):
    for representation in ('simple115', 'simple115v2'):
      for right in (False, True):
        for players in (1, 2):
          for rewards in ('scoring', 'scoring,checkpoints'):
            with self.subTest(representation=representation, right=right, players=players, rewards=rewards):
              def build(builder):
                self.checkpoint_scene(builder, right=right)
              with mock.patch('gfootball.scenarios.academy_empty_goal_close.build_scenario', build):
                options = dict(env_name='academy_empty_goal_close', representation=representation,
                               rewards=rewards, stacked=True,
                               number_of_left_players_agent_controls=0 if right else players,
                               number_of_right_players_agent_controls=players if right else 0)
                reference, native = self.make('python', **options), self.make(**options)
                a, b = reference.reset(seed=17)[0], native.reset(seed=17)[0]
                np.testing.assert_array_equal(a, b)
                self.assertEqual(b.shape, (460,) if players == 1 else (players, 460))
                self.assertTrue(native.observation_space.contains(b))
                for age in range(4):
                  np.testing.assert_array_equal(b[..., age * 115:(age + 1) * 115], b[..., :115])
                origin = b.copy()
                previous = b.copy()
                for frame in range(8):
                  action = frame % 19 if players == 1 else np.full(players, frame % 19, dtype=np.int64)
                  a, b = reference.step(action), native.step(action)
                  np.testing.assert_array_equal(a[0], b[0])
                  np.testing.assert_array_equal(b[0][..., :345], previous[..., 115:])
                  np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
                  self.assertEqual(a[1:4], b[1:4])
                  self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
                  previous = b[0].copy()
                digest = self.digest(native, 'native')
                invalid = np.zeros((2, players), dtype=np.int64)
                invalid[-1, -1] = 19
                with self.assertRaises(ValueError):
                  native.step_many(invalid)
                self.assertEqual(digest, self.digest(native, 'native'))
                action = 0 if players == 1 else np.zeros(players, dtype=np.int64)
                a, b = reference.step(action), native.step(action)
                np.testing.assert_array_equal(a[0], b[0])
                np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
                saved = b[0].copy()
                np.testing.assert_array_equal(native.reset(seed=17)[0], origin)
                reference.reset(seed=17)
                actions = np.array([[(frame + player) % 19 for player in range(players)]
                                    for frame in range(12)], dtype=np.int64)
                expected = [reference.step(int(row[0]) if players == 1 else row) for row in actions]
                result = native.step_many(actions)
                np.testing.assert_array_equal(result[0], np.stack([row[0] for row in expected]))
                np.testing.assert_array_equal(result[1], [row[1] for row in expected])
                np.testing.assert_array_equal(result[4]['agent_rewards'],
                                              np.stack([row[4]['agent_rewards'] for row in expected]))
                np.testing.assert_array_equal(saved, b[0])
                self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
                reference.close()
                native.close()

  def test_native_frame_stack_batch_keeps_terminal_history_and_checker(self):
    for representation in ('simple115', 'simple115v2'):
      with self.subTest(representation=representation):
        options = dict(env_name='tests.second_half', stacked=True, representation=representation,
                       rewards='scoring,checkpoints', number_of_left_players_agent_controls=2)
        reference, native = self.make('python', **options), self.make(**options)
        check_env(native, skip_render_check=True)
        reference.reset(seed=9)
        native.reset(seed=9)
        expected = []
        for _ in range(32):
          expected.append(reference.step(np.zeros(2, dtype=np.int64)))
          if expected[-1][2]:
            break
        result = native.step_many(np.zeros((32, 2), dtype=np.int64))
        self.assertLess(len(expected), 32)
        np.testing.assert_array_equal(result[0], np.stack([row[0] for row in expected]))
        np.testing.assert_array_equal(result[2], [row[2] for row in expected])
        np.testing.assert_array_equal(result[4]['agent_rewards'],
                                      np.stack([row[4]['agent_rewards'] for row in expected]))
        self.assertTrue(result[2][-1])
        self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
        snapshot = result[0].copy()
        native.reset(seed=9)
        native.step(np.zeros(2, dtype=np.int64))
        np.testing.assert_array_equal(snapshot, result[0])

  def test_goal_reward_and_score_termination_match_python(self):
    from gfootball.env.scenario_builder import Role, Team
    def goal_scenario(builder):
      builder.config().game_duration = 400
      builder.config().deterministic = True
      builder.config().end_episode_on_score = True
      builder.config().offsides = False
      builder.SetBallPosition(0.98, 0.0)
      builder.SetTeam(Team.e_Left)
      builder.AddPlayer(-1.0, 0.0, Role.e_PlayerRole_GK, lazy=True)
      builder.AddPlayer(0.96, 0.0, Role.e_PlayerRole_CF, lazy=True)
      builder.SetTeam(Team.e_Right)
      builder.AddPlayer(0.5, 0.3, Role.e_PlayerRole_GK, lazy=True)
    with mock.patch('gfootball.scenarios.academy_empty_goal_close.build_scenario', goal_scenario):
      reference = self.make('python', env_name='academy_empty_goal_close')
      native = self.make(env_name='academy_empty_goal_close')
      np.testing.assert_array_equal(reference.reset(seed=7)[0], native.reset(seed=7)[0])
      total = 0
      for frame in range(120):
        action = 12 if frame % 5 == 0 else 5
        a, b = reference.step(action), native.step(action)
        np.testing.assert_array_equal(a[0], b[0])
        self.assertEqual(a[1:4], b[1:4])
        self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
        total += b[1]
        if b[2]:
          break
      self.assertEqual(total, 1.0)
      self.assertTrue(b[2])

  def test_v2_builtin_ai_and_cadence_match_python(self):
    options = dict(game_engine_random_seed=42, action_set='v2', physics_steps_per_frame=2)
    reference = self.make('python', other_config_options=options)
    native = self.make(other_config_options=options)
    np.testing.assert_array_equal(reference.reset(seed=8)[0], native.reset(seed=8)[0])
    for action in (19, 0, 5, 12, 13, 14, 15, 16, 17, 18):
      a, b = reference.step(action), native.step(action)
      np.testing.assert_array_equal(a[0], b[0])
      self.assertEqual(a[1:4], b[1:4])
      self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))

  def test_batch_matches_python_for_single_and_joint_right_actions(self):
    for left, right in ((1, 0), (0, 2), (11, 0)):
      with self.subTest(left=left, right=right):
        options = dict(number_of_left_players_agent_controls=left,
                       number_of_right_players_agent_controls=right)
        reference, native = self.make('python', **options), self.make(**options)
        reference.reset(seed=21)
        native.reset(seed=21)
        actions = np.array([[(frame + player) % 19 for player in range(left + right)]
                            for frame in range(32)], dtype=np.int64)
        expected = [reference.step(int(row[0]) if left + right == 1 else row) for row in actions]
        # Accept noncontiguous NumPy inputs and the convenient single-player vector.
        supplied = actions[:, 0]
        if left + right > 1:
          supplied = np.stack((actions, actions), axis=2)[:, :, 0]
        result = native.step_many(supplied)
        np.testing.assert_array_equal(result[0], np.stack([row[0] for row in expected]))
        np.testing.assert_array_equal(result[1], [row[1] for row in expected])
        np.testing.assert_array_equal(result[2], [row[2] for row in expected])
        np.testing.assert_array_equal(result[3], [row[3] for row in expected])
        np.testing.assert_array_equal(result[4]['agent_rewards'],
                                      np.stack([row[4]['agent_rewards'] for row in expected]))
        np.testing.assert_array_equal(result[4]['score_reward'], [row[4]['score_reward'] for row in expected])
        self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
        previous = result[0].copy()
        native.step(0 if left + right == 1 else np.zeros(left + right, dtype=np.int64))
        np.testing.assert_array_equal(previous, result[0])

  def test_batch_invalid_suffix_shape_type_and_capacity_preserve_state(self):
    env = self.make()
    env.reset(seed=5)
    digest = self.digest(env, 'native')
    invalid = ([], np.zeros(257, dtype=np.int64), [[0, 0]], [0, 0, 19],
               [0.0, 1.0], [False, True], np.array([2**64 - 1], dtype=np.uint64))
    for actions in invalid:
      with self.subTest(actions=actions), self.assertRaises(ValueError):
        env.step_many(actions)
      self.assertEqual(digest, self.digest(env, 'native'))
    for actions in (np.array([[0.5]]), np.array([[True]]),
                    np.array([[2**64 - 1]], dtype=np.uint64), np.array([[0], [19]])):
      with self.assertRaises(ValueError):
        env._env._native.step_many(actions)
      self.assertEqual(digest, self.digest(env, 'native'))
    self.assertEqual(env.step_many(np.zeros(256, dtype=np.int64))[0].shape, (256, 115))

  def test_batch_stops_at_terminal_and_reseeds(self):
    reference, native = self.make('python', env_name='tests.second_half'), self.make(env_name='tests.second_half')
    reference.reset(seed=9)
    native.reset(seed=9)
    expected = []
    for _ in range(32):
      expected.append(reference.step(0))
      if expected[-1][2]:
        break
    first = native.step_many([0] * 32)
    self.assertEqual(first[0].shape[0], len(expected))
    self.assertLess(len(expected), 32)
    np.testing.assert_array_equal(first[0], np.stack([row[0] for row in expected]))
    self.assertTrue(first[2][-1])
    self.assertFalse(first[2][:-1].any())
    self.assertFalse(first[3].any())
    self.assertEqual(self.digest(reference, 'python'), self.digest(native, 'native'))
    with self.assertRaises(gym.error.ResetNeeded):
      native.step_many([0])
    native.reset(seed=9)
    second = native.step_many([0] * 32)
    for a, b in zip(first[:4], second[:4]):
      np.testing.assert_array_equal(a, b)

  def test_batch_rejects_python_backend_and_aborts_processing_failure(self):
    reference = self.make('python')
    reference.reset(seed=5)
    digest = self.digest(reference, 'python')
    with self.assertRaises(ValueError):
      reference.step_many([0])
    self.assertEqual(digest, self.digest(reference, 'python'))
    env = self.make()
    env.reset(seed=5)
    leased = ENGINE_POOL.stats()['leased']
    def fail_after_transition(actions):
      env._env._native.step_many(actions)
      raise RuntimeError('output failure')
    with mock.patch.object(env._env, 'step_many', fail_after_transition):
      with self.assertRaisesRegex(RuntimeError, 'output failure'):
        env.step_many([0])
    self.assertEqual(ENGINE_POOL.stats()['leased'], leased - 1)
    with self.assertRaises(gym.error.ResetNeeded):
      env.step_many([0])


if __name__ == '__main__':
  unittest.main()
