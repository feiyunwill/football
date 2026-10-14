"""Snapshot envelope/file contracts; real Gym restore tests added alongside them."""
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import select
import threading
from unittest import mock
import numpy as np

from gfootball import training_snapshot as snapshot


class SnapshotFileTest(unittest.TestCase):
  def payload(self, value=1):
    return snapshot.encode({'value': value}, b'native-fixture!!')

  def test_envelope_rejects_corruption_truncation_and_type(self):
    data = self.payload()
    self.assertEqual(snapshot.decode(data), ({'value': 1}, b'native-fixture!!'))
    for length in range(len(data)):
      with self.assertRaises(ValueError):
        snapshot.decode(data[:length])
    for offset in range(len(data)):
      changed = bytearray(data)
      changed[offset] ^= 1
      with self.assertRaises(ValueError):
        snapshot.decode(bytes(changed))
    with self.assertRaises(TypeError):
      snapshot.decode(bytearray(data))
    with self.assertRaises(ValueError):
      snapshot.decode(data + b'x')

  def test_metadata_and_total_budget(self):
    for invalid in (float('nan'), float('inf'), object(), 1 << 257):
      with self.assertRaises(ValueError):
        snapshot.encode({'value': invalid}, b'native-fixture!!')
    with self.assertRaises(ValueError):
      snapshot.encode({'value': 'x' * 8193}, b'native-fixture!!')
    nested = {}
    for _ in range(10):
      nested = {'nested': nested}
    with self.assertRaises(ValueError):
      snapshot.encode(nested, b'native-fixture!!')
    with self.assertRaises(ValueError):
      snapshot.encode({}, b'x' * (snapshot.MAX_NATIVE_BYTES + 1))

  def test_atomic_replace_and_pre_replace_failures_preserve_old_file(self):
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'snapshot.bin'
      old, new = self.payload(1), self.payload(2)
      snapshot.save(path, old)
      self.assertEqual(snapshot.load(path), old)
      for operation in ('fsync', 'replace'):
        with mock.patch.object(snapshot.os, operation, side_effect=OSError('interrupted')):
          with self.assertRaises(OSError):
            snapshot.save(path, new)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(list(Path(folder).iterdir()), [path])
      snapshot.save(path, new)
      self.assertEqual(snapshot.load(path), new)
      with mock.patch.object(snapshot.os, 'fsync', side_effect=OSError('primary write failure')):
        with mock.patch.object(snapshot.os, 'unlink', side_effect=OSError('cleanup failure')):
          with self.assertRaisesRegex(OSError, 'primary write failure'):
            snapshot.save(path, old)
      self.assertEqual(snapshot.load(path), new)

  def test_file_and_path_budgets(self):
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'snapshot.bin'
      with path.open('wb') as stream:
        stream.truncate(snapshot.MAX_BYTES + 1)
      with self.assertRaises(ValueError):
        snapshot.load(path)
      with self.assertRaises(ValueError):
        snapshot.load(folder)
      if hasattr(os, 'mkfifo'):
        fifo = Path(folder) / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
          snapshot.load(fifo)
      for invalid in ('', '\0', 'x' * 4097):
        with self.assertRaises(ValueError):
          snapshot.save(invalid, self.payload())

  @unittest.skipUnless(os.name == 'posix', 'POSIX process interruption contract')
  def test_process_interruption_before_replace_preserves_previous_file(self):
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'snapshot.bin'
      old = self.payload(1)
      snapshot.save(path, old)
      code = '''
import sys
from gfootball import training_snapshot as snapshot
def stop_before_replace(fd):
  print('ready', flush=True)
  sys.stdin.read()
snapshot.os.fsync = stop_before_replace
snapshot.save(sys.argv[1], snapshot.encode({'value':2}, b'native-fixture!!'))
'''
      child = subprocess.Popen([sys.executable, '-c', code, str(path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      try:
        ready, _, _ = select.select([child.stdout], [], [], 10)
        self.assertTrue(ready, 'Writer did not reach fsync boundary')
        self.assertEqual(child.stdout.readline().strip(), b'ready')
        child.kill()
        child.communicate(timeout=10)
        self.assertEqual(snapshot.load(path), old)
      finally:
        if child.poll() is None:
          child.kill()
          child.communicate(timeout=10)


class NativeSnapshotTest(unittest.TestCase):
  def make(self):
    from gfootball.gymnasium import FootballEnv
    env = FootballEnv(backend='native', env_name='academy_empty_goal_close',
                      rewards='scoring,checkpoints', stacked=True,
                      other_config_options={'render_resolution_x': 160, 'render_resolution_y': 90})
    self.addCleanup(env.close)
    return env

  def equal_transition(self, a, b):
    np.testing.assert_array_equal(a[0], b[0])
    self.assertEqual(a[1:4], b[1:4])
    np.testing.assert_array_equal(a[4]['agent_rewards'], b[4]['agent_rewards'])
    self.assertEqual(a[4]['score_reward'], b[4]['score_reward'])

  def test_native_gym_round_trip_file_and_future_reset_rng(self):
    a, b = self.make(), self.make()
    a.reset(seed=7); b.reset(seed=7)
    for action in (13, 5, 8):
      a.step(action)
    saved = a.get_state()
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'state.bin'
      a.save_state(path)
      b.load_state(path)
    for action in (0, 5, 12, 0):
      self.equal_transition(a.step(action), b.step(action))
    np.testing.assert_array_equal(a.reset()[0], b.reset()[0])
    self.assertEqual(a.np_random.bit_generator.state, b.np_random.bit_generator.state)
    self.assertEqual(a._env._config._values['episode_number'], b._env._config._values['episode_number'])
    metadata, native = snapshot.decode(saved)
    self.assertEqual(metadata['kind'], 'native-gym-v1')
    self.assertEqual(native[:4], b'FTRN')

  def test_rejected_metadata_and_bytes_preserve_rng_config_and_kernel(self):
    env = self.make()
    env.reset(seed=7); env.step(5)
    saved = env.get_state()
    before_rng = env.np_random.bit_generator.state
    before_digest = env._env._native.get_state_digest()
    metadata, native = snapshot.decode(saved)
    metadata['needs_reset'] = True
    with self.assertRaises(ValueError):
      env.set_state(snapshot.encode(metadata, native))
    metadata, _ = snapshot.decode(saved)
    metadata['rng']['state']['inc'] = 0
    with self.assertRaises(ValueError):
      env.set_state(snapshot.encode(metadata, native))
    metadata, _ = snapshot.decode(saved)
    metadata['config']['values'].pop('episode_number')
    with self.assertRaises(ValueError):
      env.set_state(snapshot.encode(metadata, native))
    with self.assertRaises(TypeError):
      env.set_state(bytearray(saved))
    with self.assertRaises(TypeError):
      env._env._native.set_state(bytearray(native))
    with self.assertRaises(ValueError):
      env._env._native.set_state(b'x' * (snapshot.MAX_NATIVE_BYTES + 1))
    self.assertEqual(before_rng, env.np_random.bit_generator.state)
    self.assertEqual(before_digest, env._env._native.get_state_digest())
    env.step(0)

  def test_snapshot_ownership_rejects_thread_before_file_access(self):
    env = self.make()
    env.reset(seed=7)
    before = env._env._native.get_state_digest()
    errors = []
    def wrong_thread():
      for operation in (env.get_state, lambda: env.load_state('/nonexistent-snapshot'),
                        lambda: snapshot.load_state(env, '/nonexistent-snapshot')):
        try:
          operation()
        except BaseException as error:
          errors.append(error)
    thread = threading.Thread(target=wrong_thread)
    thread.start(); thread.join(timeout=10)
    self.assertFalse(thread.is_alive())
    self.assertEqual(len(errors), 3)
    self.assertTrue(all(type(error) is RuntimeError for error in errors))
    self.assertEqual(before, env._env._native.get_state_digest())
    env.step(0)

  def test_terminal_snapshot_keeps_reset_needed_and_live_snapshot_can_resume(self):
    from gfootball.scenarios import academy_empty_goal_close as scene
    original = scene.build_scenario
    def short(builder):
      original(builder)
      builder.config().game_duration = 2
    with mock.patch.object(scene, 'build_scenario', side_effect=short):
      a, b = self.make(), self.make()
      a.reset(seed=7); b.reset(seed=7)
      live = a.get_state()
      for _ in range(20):
        if a.step(0)[2]:
          break
      self.assertTrue(a._needs_reset)
      b.set_state(a.get_state())
      import gymnasium as gym
      with self.assertRaises(gym.error.ResetNeeded):
        b.step(0)
      b.set_state(live)
      self.assertFalse(b._needs_reset)
      b.step(0)

  def wrapped(self, maximum=5):
    import gymnasium as gym
    raw = self.make()
    return gym.wrappers.TimeLimit(gym.wrappers.OrderEnforcing(gym.wrappers.PassiveEnvChecker(raw)), maximum)

  def test_wrapped_round_trip_keeps_time_limit_and_checker_history(self):
    a, b = self.wrapped(), self.wrapped()
    a.reset(seed=7); b.reset(seed=7)
    # PassiveEnvChecker still owns a previous observation after the first step.
    a.step(5)
    saved = snapshot.get_state(a)
    snapshot.set_state(b, saved)
    self.assertEqual(b._elapsed_steps, 1)
    for index, action in enumerate((0, 5, 0, 0), start=2):
      x, y = a.step(action), b.step(action)
      self.equal_transition(x, y)
      self.assertEqual(x[3], index == 5)
    self.assertEqual(a.env.env._previous_data, None)
    self.assertEqual(b.env.env._previous_data, None)
    # Preserve the already truncated wrapper as well, without auto-reset.
    snapshot.set_state(b, snapshot.get_state(a))
    self.assertEqual(b._elapsed_steps, 5)

  def test_wrapper_admission_and_post_kernel_failure_roll_back(self):
    a, b = self.wrapped(), self.wrapped()
    a.reset(seed=7); b.reset(seed=7)
    a.step(5); a.step(0)
    b.step(0)
    saved, before = snapshot.get_state(a), b.unwrapped.get_state()
    metadata, native = snapshot.decode(saved)
    metadata['wrapper_chain'][0]['maximum'] = 9
    with self.assertRaises(ValueError):
      snapshot.set_state(b, snapshot.encode(metadata, native))
    self.assertEqual(b._elapsed_steps, 1)
    self.assertEqual(snapshot.decode(before)[0], snapshot.decode(b.unwrapped.get_state())[0])
    real_commit = snapshot._commit_wrappers
    calls = []
    def fail_once(values):
      calls.append(1)
      if len(calls) == 1:
        values[0][0]._elapsed_steps = 99
        raise MemoryError('injected wrapper commit failure')
      real_commit(values)
    digest = b.unwrapped._env._native.get_state_digest()
    with mock.patch.object(snapshot, '_commit_wrappers', side_effect=fail_once):
      with self.assertRaises(MemoryError):
        snapshot.set_state(b, saved)
    self.assertEqual(b._elapsed_steps, 1)
    self.assertEqual(digest, b.unwrapped._env._native.get_state_digest())
    self.assertEqual(snapshot.decode(before)[0], snapshot.decode(b.unwrapped.get_state())[0])
    import gymnasium as gym
    with self.assertRaises(ValueError):
      snapshot.get_state(gym.Wrapper(a))
    b.step(0)

  def test_new_process_restores_file_and_same_subsequent_trajectory(self):
    a = self.make()
    a.reset(seed=7)
    for action in (13, 5, 0):
      a.step(action)
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'state.bin'
      output = Path(folder) / 'rollout.npz'
      a.save_state(path)
      code = '''
import sys, numpy as np
from gfootball.gymnasium import FootballEnv
env = FootballEnv(backend='native', env_name='academy_empty_goal_close', rewards='scoring,checkpoints', stacked=True,
                  other_config_options={'render_resolution_x':160, 'render_resolution_y':90})
try:
  env.reset(seed=7)
  env.load_state(sys.argv[1])
  rows = [env.step(action) for action in (0, 5, 0, 12)]
  reset_observation = env.reset()[0]
  np.savez(sys.argv[2], observations=np.stack([row[0] for row in rows]),
           rewards=[row[1] for row in rows], terminated=[row[2] for row in rows],
           agent_rewards=np.stack([row[4]['agent_rewards'] for row in rows]), reset=reset_observation)
finally:
  env.close()
'''
      result = subprocess.run([sys.executable, '-c', code, str(path), str(output)],
                              cwd=folder, capture_output=True, timeout=60)
      self.assertEqual(result.returncode, 0, result.stderr.decode())
      rows = [a.step(action) for action in (0, 5, 0, 12)]
      with np.load(output, allow_pickle=False) as actual:
        np.testing.assert_array_equal(actual['observations'], np.stack([row[0] for row in rows]))
        np.testing.assert_array_equal(actual['rewards'], [row[1] for row in rows])
        np.testing.assert_array_equal(actual['terminated'], [row[2] for row in rows])
        np.testing.assert_array_equal(actual['agent_rewards'], np.stack([row[4]['agent_rewards'] for row in rows]))
        np.testing.assert_array_equal(actual['reset'], a.reset()[0])


if __name__ == '__main__':
  unittest.main()
