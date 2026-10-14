"""Long replay/resource contracts for native snapshots, with real processes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np


class TrainingResourceTest(unittest.TestCase):
  def make(self, level='academy_empty_goal_close', players=1):
    from gfootball.gymnasium import FootballEnv
    return FootballEnv(backend='native', env_name=level, stacked=True, rewards='scoring,checkpoints',
                       number_of_left_players_agent_controls=players,
                       other_config_options={'render_resolution_x':160, 'render_resolution_y':90})

  def test_fatal_native_restore_refunds_actual_engine_reservation(self):
    from gfootball.engine_pool import ENGINE_POOL
    from gfootball.owned_engine import OwnedEngine
    baseline = ENGINE_POOL.stats()
    env = self.make()
    self.addCleanup(env.close)
    env.reset(seed=7)
    saved = env.get_state()
    native = env._env._native._resource()
    invoke = OwnedEngine._invoke
    def failed_restore(owner, name, *args, **kwargs):
      if name == 'set_state':
        native.close()
        raise RuntimeError('injected fatal kernel rollback failure')
      return invoke(owner, name, *args, **kwargs)
    with mock.patch.object(OwnedEngine, '_invoke', new=failed_restore):
      with self.assertRaisesRegex(RuntimeError, 'fatal kernel rollback'):
        env.set_state(saved)
    self.assertTrue(env._closed)
    self.assertEqual(ENGINE_POOL.stats()['leased'], baseline['leased'])
    self.assertEqual(ENGINE_POOL.stats()['live'], baseline['live'])

  def test_repeated_reset_restore_close_has_bounded_fds_rss_and_pool(self):
    from gfootball.engine_pool import ENGINE_POOL
    def rss():
      return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    baseline_pool = ENGINE_POOL.stats()
    measurements = []
    for iteration in range(12):
      env = self.make(players=2 if iteration % 2 else 1)
      try:
        env.reset(seed=iteration + 7)
        for episode in range(3):
          action = 5 if env._env._count == 1 else np.array([5, 0])
          for _ in range(4): env.step(action)
          saved = env.get_state()
          env.step(action)
          env.set_state(saved)
          env.reset()
      finally:
        env.close()
      self.assertEqual(ENGINE_POOL.stats()['leased'], baseline_pool['leased'])
      self.assertEqual(ENGINE_POOL.stats()['live'], baseline_pool['live'])
      if iteration >= 3:
        measurements.append((rss(), len(list(Path('/proc/self/fd').iterdir()))))
    self.assertEqual(len({item[1] for item in measurements}), 1)
    self.assertLessEqual(max(item[0] for item in measurements) - min(item[0] for item in measurements), 64 * 1024 * 1024)
    print('Training resource samples:', json.dumps(measurements), flush=True)

  def test_multi_scenario_seed_long_cross_process_digest(self):
    for level, seed in (('academy_empty_goal_close', 7), ('academy_run_to_score', 42),
                        ('11_vs_11_easy_stochastic', 101)):
      with self.subTest(level=level, seed=seed), tempfile.TemporaryDirectory() as folder:
        env = self.make(level)
        try:
          env.reset(seed=seed)
          for _ in range(32):
            if env.step(0)[2]: env.reset()
          path, output = Path(folder) / 'state.bin', Path(folder) / 'rollout.json'
          env.save_state(path)
          # Reproduce the prelude too, so any initial terminal/reset selects the same target scenario.
          code = '''
import hashlib,json,sys
from gfootball.gymnasium import FootballEnv
env = FootballEnv(backend='native', env_name=sys.argv[3], stacked=True, rewards='scoring,checkpoints',
                  other_config_options={'render_resolution_x':160,'render_resolution_y':90})
try:
  env.reset(seed=int(sys.argv[4]))
  for _ in range(32):
    if env.step(0)[2]: env.reset()
  env.load_state(sys.argv[1])
  hash = hashlib.sha256(); frames = 0
  for frame in range(256):
    row = env.step(frame % 19)
    hash.update(row[0].tobytes()); hash.update(row[4]['agent_rewards'].tobytes())
    hash.update(env._env._native.get_state_digest()); frames += 1
    if row[2]: env.reset()
  open(sys.argv[2],'w').write(json.dumps({'sha256':hash.hexdigest(),'frames':frames}))
finally:
  env.close()
'''
          child = subprocess.run([sys.executable, '-c', code, str(path), str(output), level, str(seed)],
                                 cwd=folder, capture_output=True, timeout=120)
          self.assertEqual(child.returncode, 0, child.stderr.decode())
          digest = hashlib.sha256()
          for frame in range(256):
            row = env.step(frame % 19)
            digest.update(row[0].tobytes()); digest.update(row[4]['agent_rewards'].tobytes())
            digest.update(env._env._native.get_state_digest())
            if row[2]: env.reset()
          actual = json.loads(output.read_text())
          self.assertEqual(actual, {'sha256':digest.hexdigest(), 'frames':256})
          print('Cross-process trajectory:', level, seed, actual['sha256'], flush=True)
        finally:
          env.close()


if __name__ == '__main__':
  unittest.main()
