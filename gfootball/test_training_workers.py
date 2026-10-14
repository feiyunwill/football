"""Real-process contracts for the bounded native training sampler."""
import hashlib
import multiprocessing
import os
import signal
import struct
import threading
import time
import unittest
from unittest import mock

import numpy as np

from gfootball import training_workers as workers


def _partial_worker(channel, config):
  channel.sendall(workers._encode({'id': 0, 'operation': 'startup', 'ok': True, 'pid': os.getpid()}))
  request, _ = workers._receive(channel)
  # Advertise a complete frame, then stall after only a partial metadata header.
  channel.sendall(struct.pack('!I', 100) + b'\x00')
  time.sleep(60)


def _oversized_worker(channel, config):
  channel.sendall(workers._encode({'id': 0, 'operation': 'startup', 'ok': True, 'pid': os.getpid()}))
  workers._receive(channel)
  channel.sendall(struct.pack('!I', workers.MAX_MESSAGE + 1))
  time.sleep(60)


def _startup_stall(channel, config):
  time.sleep(60)


class WorkerPoolTest(unittest.TestCase):
  def config(self, **kwargs):
    return dict(env_name='academy_empty_goal_close', **kwargs,
                other_config_options={'render_resolution_x': 160, 'render_resolution_y': 90,
                                      'physics_steps_per_frame': 2, 'game_engine_random_seed': 0})

  def assert_reaped(self, pool):
    self.assertTrue(pool.closed)
    self.assertEqual(len(pool.exit_codes), len(pool.worker_pids))
    self.assertTrue(all(code is not None for code in pool.exit_codes))
    self.assertFalse(set(pool.worker_pids) & {child.pid for child in multiprocessing.active_children()})

  def test_seed_and_constructor_bounds(self):
    self.assertEqual(workers.episode_seed(42, 17), workers.episode_seed(42, 17))
    self.assertNotEqual(workers.episode_seed(42, 17), workers.episode_seed(42, 18))
    for args in ((True, 0), (-1, 0), (2**64, 0), (0, -1), (0, 2**63)):
      with self.assertRaises(ValueError): workers.episode_seed(*args)
    for count in (0, 5, True):
      with self.assertRaises(ValueError): workers.NativeWorkerPool({}, workers=count)
    for timeout in (0, -1, float('nan'), float('inf'), True, 301):
      with self.assertRaises(ValueError): workers.NativeWorkerPool({}, timeout=timeout)
    with self.assertRaises(ValueError): workers.NativeWorkerPool({'env_name': 'x' * 8192})
    with self.assertRaises(ValueError): workers.NativeWorkerPool({'backend': 'python'})

  def test_scalar_parity_joint_right_stack_and_subsets(self):
    from gfootball.gymnasium import FootballEnv
    joint = self.config(representation='simple115v2', stacked=True,
                        number_of_left_players_agent_controls=0,
                        number_of_right_players_agent_controls=2, rewards='scoring,checkpoints')
    joint['env_name'] = '11_vs_11_easy_stochastic'
    for config in (self.config(representation='simple115'), joint):
      with self.subTest(config=config), workers.NativeWorkerPool(config, workers=2, base_seed=42) as pool:
        self.assertEqual(len(set(pool.worker_pids)), 2)
        self.assertNotIn(os.getpid(), pool.worker_pids)
        episodes = {0: 17, 1: 18}
        reset = pool.reset(episodes)
        direct = [FootballEnv(backend='native', **config) for _ in episodes]
        try:
          for worker, env in enumerate(direct):
            observation = env.reset(seed=workers.episode_seed(42, episodes[worker]))[0]
            np.testing.assert_array_equal(reset[worker].observation, observation)
            self.assertEqual(reset[worker].episode_id, episodes[worker])
          for frame in range(12):
            actions = {i: frame % 19 if direct[i]._env._count == 1 else [frame % 19, (frame + 1) % 19]
                       for i in episodes}
            results = pool.step(actions)
            for worker, env in enumerate(direct):
              observation, reward, terminal, truncated, info = env.step(actions[worker])
              actual = results[worker]
              np.testing.assert_array_equal(actual.observation, observation)
              np.testing.assert_array_equal(actual.agent_rewards, info['agent_rewards'])
              self.assertEqual((actual.reward, actual.terminated, actual.truncated, actual.score_reward),
                               (reward, terminal, truncated, info['score_reward']))
          digests = pool.digests()
          for worker, env in enumerate(direct):
            self.assertEqual(digests[worker], hashlib.sha256(env._env._native.get_state_digest()).digest())
          untouched = digests[1]
          pool.reset({0: 99})
          self.assertEqual(pool.digests()[1], untouched)
          # Returned arrays own storage and cannot corrupt later observations.
          reset[0].observation.fill(float('nan'))
          action = np.int64(0) if direct[0]._env._count == 1 else np.zeros(2, dtype=np.int64)
          self.assertTrue(np.isfinite(pool.step({0: action})[0].observation).all())
        finally:
          for env in direct: env.close()
      self.assert_reaped(pool)
      self.assertEqual(pool.exit_codes, (0, 0))

  def test_invalid_round_preserves_all_workers(self):
    with workers.NativeWorkerPool(self.config(), workers=2) as pool:
      with self.assertRaises(ValueError): pool.step({0: 0})
      pool.reset({0: 0, 1: 1})
      before = pool.digests()
      for actions in ({0: 0, 1: 19}, {0: 0, 1: True}, {0: 0, 2: 0}, {0: [0]}, {}):
        with self.assertRaises(ValueError): pool.step(actions)
        self.assertEqual(pool.digests(), before)
      with self.assertRaises(ValueError): pool.reset({0: 2, 1: -1})
      self.assertEqual(pool.digests(), before)
      pool.step({0: 0, 1: 0})

  def test_startup_remote_error_reaps_every_child(self):
    before = {child.pid for child in multiprocessing.active_children()}
    with self.assertRaisesRegex(workers.WorkerError, 'startup.*ValueError'):
      workers.NativeWorkerPool(self.config(representation='pixels'), workers=2)
    self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

  def test_startup_deadline_reaps_every_child(self):
    before = {child.pid for child in multiprocessing.active_children()}
    start = time.monotonic()
    with mock.patch.object(workers, '_worker_main', _startup_stall):
      with self.assertRaisesRegex(workers.WorkerError, 'startup deadline'):
        workers.NativeWorkerPool(self.config(), workers=2, startup_timeout=0.2)
    self.assertLess(time.monotonic() - start, 5)
    self.assertEqual({child.pid for child in multiprocessing.active_children()}, before)

  def test_remote_exception_closes_pool(self):
    pool = workers.NativeWorkerPool(self.config())
    try:
      # Deliberately bypass the client validator to exercise a real child exception.
      with self.assertRaisesRegex(workers.WorkerError, 'step.*ResetNeeded'):
        pool._request('step', {0: {'action': 0}})
      self.assert_reaped(pool)
      with self.assertRaises(RuntimeError): pool.reset({0: 1})
    finally:
      pool.close()

  def test_worker_exit_aborts_entire_pool(self):
    pool = workers.NativeWorkerPool(self.config(), workers=2)
    try:
      pool.reset({0: 0, 1: 1})
      os.kill(pool.worker_pids[1], signal.SIGKILL)
      with self.assertRaises(workers.WorkerError): pool.step({0: 0, 1: 0})
      self.assert_reaped(pool)
    finally:
      pool.close()

  def test_maximum_observation_fits_message_budget(self):
    config = self.config(stacked=True, number_of_left_players_agent_controls=11)
    config['env_name'] = '11_vs_11_easy_stochastic'
    with workers.NativeWorkerPool(config) as pool:
      self.assertEqual(pool.reset({0: 7})[0].observation.shape, (11, 460))
      result = pool.step({0: [0] * 11})[0]
      self.assertEqual(result.agent_rewards.shape, (11,))
      self.assertEqual(result.observation.dtype, np.float32)
      before = pool.digests()
      # A huge zero-copy input must reject before allocating a Python action list.
      huge = np.broadcast_to(np.int64(0), (100_000_000,))
      with self.assertRaises(ValueError): pool.step({0: huge})
      self.assertEqual(pool.digests(), before)

  def test_partial_message_obeys_deadline(self):
    with mock.patch.object(workers, '_worker_main', _partial_worker):
      pool = workers.NativeWorkerPool(self.config(), timeout=0.2)
    start = time.monotonic()
    try:
      with self.assertRaisesRegex(workers.WorkerError, 'deadline'):
        pool.reset({0: 0})
      self.assertLess(time.monotonic() - start, 5)
      self.assert_reaped(pool)
    finally:
      pool.close()

  def test_oversized_frame_rejected_before_allocation(self):
    with mock.patch.object(workers, '_worker_main', _oversized_worker):
      pool = workers.NativeWorkerPool(self.config())
    try:
      with self.assertRaisesRegex(workers.WorkerError, 'message budget'):
        pool.reset({0: 0})
      self.assert_reaped(pool)
    finally:
      pool.close()

  def test_wrong_thread_and_process_do_not_mutate_pool(self):
    with workers.NativeWorkerPool(self.config()) as pool:
      pool.reset({0: 0})
      errors = []
      def close_elsewhere():
        try: pool.close()
        except RuntimeError as error: errors.append(str(error))
      thread = threading.Thread(target=close_elsewhere)
      thread.start(); thread.join()
      self.assertEqual(len(errors), 1)
      if hasattr(os, 'fork'):
        pid = os.fork()
        if pid == 0:
          try:
            pool.step({0: 0})
          except RuntimeError:
            os._exit(0)
          os._exit(1)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
      pool.step({0: 0})

  def test_terminal_requires_explicit_reset(self):
    # Real match-clock terminal; no policy-dependent goal fixture.
    config = self.config()
    config['other_config_options']['physics_steps_per_frame'] = 1000
    with workers.NativeWorkerPool(config) as pool:
      pool.reset({0: 0})
      terminal = False
      for _ in range(64):
        terminal = pool.step({0: 0})[0].terminated
        if terminal: break
      self.assertTrue(terminal)
      with self.assertRaises(ValueError): pool.step({0: 0})
      pool.reset({0: 1})
      pool.step({0: 0})


if __name__ == '__main__':
  unittest.main()
