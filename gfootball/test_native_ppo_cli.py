"""Actual native CLI update, frozen evaluation and new-process resume contracts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('GFOOTBALL_NATIVE_PPO_TRAIN'), 'Build via isolated native validator')
class NativePpoCliTest(unittest.TestCase):
  def run_cli(self, *arguments, success=True):
    result = subprocess.run([os.environ['GFOOTBALL_NATIVE_PPO_TRAIN'], *map(str, arguments)],
                            capture_output=True, timeout=120)
    if success:
      self.assertEqual(result.returncode, 0, result.stderr.decode())
      return json.loads(result.stdout)
    self.assertNotEqual(result.returncode, 0)
    return result

  def test_invalid_options_fail_before_training(self):
    for args in (('--unknown', '1'), ('--updates', '-1'), ('--rollout', '257'),
                 ('--players', '0'), ('--hidden', '65'), ('--eval-episodes', '65'),
                 ('--eval-steps', '0'), ('--seed', '42garbage'), ('--seed', '1', '--seed', '2'),
                 ('--scenario', 'missing'), ('--scenario', 'empty_goal', '--players', '11')):
      self.run_cli(*args, success=False)

  def test_actual_updates_frozen_evaluation_and_new_process_resume(self):
    common = ('--seed', 7, '--hidden', 8, '--epochs', 2, '--minibatch', 4,
              '--rollout', 8, '--eval-episodes', 1, '--eval-steps', 16)
    with tempfile.TemporaryDirectory() as directory:
      full, half, resumed = [Path(directory) / name for name in ('full.bin', 'half.bin', 'resumed.bin')]
      baseline = self.run_cli(*common, '--updates', 2, '--save', full)
      prefix = self.run_cli(*common, '--updates', 1, '--save', half)
      continuation = self.run_cli(*common, '--updates', 1, '--load', half, '--save', resumed)
      self.assertEqual(baseline['iterations'][:1], prefix['iterations'])
      self.assertEqual(baseline['iterations'][1:], continuation['iterations'])
      self.assertEqual(baseline['state_sha256'], continuation['state_sha256'])
      self.assertEqual(full.read_bytes(), resumed.read_bytes())
      self.assertEqual(baseline['evaluation'], continuation['evaluation'])
      self.assertEqual(baseline['version'], 2)
      self.assertTrue(all(row['parameter_delta'] > 0 for row in baseline['iterations']))
      for report in (baseline, prefix, continuation):
        self.assertTrue(report['evaluation']['isolated'])
        self.assertEqual(report['state_before_evaluation_sha256'], report['state_sha256'])
        strategies = report['evaluation']['strategies']
        self.assertEqual({s['name'] for s in strategies}, {'sample', 'argmax', 'uniform_random', 'builtin_ai'})
        self.assertEqual(len({s['episodes'][0]['engine_seed'] for s in strategies}), 1)
      frozen = self.run_cli(*common, '--updates', 0, '--load', full)
      self.assertEqual(frozen['evaluation'], baseline['evaluation'])
      self.assertEqual(frozen['state_sha256'], baseline['state_sha256'])
      self.assertEqual(frozen['iterations'], [])

  def test_joint_right_stacked_v2_cli(self):
    report = self.run_cli('--scenario', '11v11', '--players', 11, '--right', '--stacked', '--compact', '--v2',
                          '--hidden', 2, '--epochs', 1, '--minibatch', 4, '--rollout', 4,
                          '--updates', 1, '--eval-episodes', 0)
    self.assertEqual((report['players'], report['features'], report['actions']), (11, 460, 20))
    self.assertTrue(report['right_team'])
    self.assertFalse(report['fixed_positions'])
    self.assertEqual(report['ppo']['epochs'], 1)
    self.assertEqual(report['total_transitions'], 4)
    self.assertGreater(report['iterations'][0]['parameter_delta'], 0)
    self.assertTrue(report['evaluation']['isolated'])


if __name__ == '__main__': unittest.main()
