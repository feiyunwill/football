"""Actual native CLI update, frozen evaluation and new-process resume contracts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('GFOOTBALL_NATIVE_PPO_TRAIN'), 'Build via isolated native validator')
class NativePpoCliTest(unittest.TestCase):
  def test_portable_inference_resume_and_input_identity(self):
    with tempfile.TemporaryDirectory() as directory:
      base=Path(directory);policy=base/'policy.fpol';cases=base/'cases.txt';state=base/'session'
      cases.write_text('0 0 0 12345 99 .5 0 .65 .2 .65 0\n1 1 0 12346 100 .4 0 .55 .2 .55 0\n')
      self.run_cli('--scenario','2v1','--hidden',3,'--updates',0,'--eval-episodes',0,'--export-policy',policy)
      def infer(*extra, success=True):
        result=subprocess.run([os.environ['GFOOTBALL_NATIVE_PPO_TRAIN'],'--inference-mode','balanced',
            '--policy',str(policy),'--inference-cases',str(cases),*map(str,extra)],capture_output=True,timeout=120)
        if success:
          self.assertEqual(result.returncode,0,result.stderr.decode())
          return [json.loads(line) for line in result.stdout.splitlines()]
        self.assertNotEqual(result.returncode,0)
        return result
      full=infer();prefix=infer('--inference-decisions',8,'--inference-state-out',state)
      self.assertFalse(prefix[-1]['complete']);saved=state.read_bytes()
      resumed=infer('--inference-state-in',state)
      self.assertEqual(prefix[:-1]+resumed[:-1],full[:-1])
      # A restored policy/case/mode mismatch must fail before output or overwrite.
      original=cases.read_text();cases.write_text(original.replace('12345','12347'))
      invalid=infer('--inference-state-in',state,success=False);self.assertEqual(invalid.stdout,b'')
      cases.write_text(original);self.assertEqual(state.read_bytes(),saved)
      corrupt=bytearray(saved);corrupt[-1]^=1;state.write_bytes(corrupt)
      invalid=infer('--inference-state-in',state,success=False);self.assertEqual(invalid.stdout,b'')
      state.write_bytes(saved.replace(b'FIFS1',b'FIFS9',1))
      infer('--inference-state-in',state,success=False)
      state.write_bytes(saved)
      self.run_cli('--inference-mode','argmax','--policy',policy,'--inference-cases',cases,
                   '--inference-state-in',state,success=False)
      policy.write_bytes(policy.read_bytes()+b'garbage')
      infer(success=False)

  def test_inference_rejects_training_and_bad_options(self):
    for args in (('--inference-mode','missing'),('--inference-mode','balanced','--updates',1),
                 ('--inference-mode','balanced','--inference-decisions',0),
                 ('--export-policy','unused'),('--scenario','2v1','--stacked','--export-policy','unused')):
      self.run_cli(*args,success=False)

  def run_cli(self, *arguments, success=True):
    result = subprocess.run([os.environ['GFOOTBALL_NATIVE_PPO_TRAIN'], *map(str, arguments)],
                            capture_output=True, timeout=120)
    if success:
      self.assertEqual(result.returncode, 0, result.stderr.decode())
      return json.loads(result.stdout)
    self.assertNotEqual(result.returncode, 0)
    return result

  def test_invalid_options_fail_before_training(self):
    for args in (('--unknown', '1'), ('--updates', '-1'), ('--updates', '2049'), ('--rollout', '257'),
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

  def test_variable_starts_have_disjoint_frozen_partitions(self):
    points=[]
    for partition in ('train','validation','test','confirmation'):
      data=self.run_cli('--scenario','varied_empty_goal','--updates',0,'--no-initial-eval',
                        '--eval-partition',partition,'--eval-episodes',8,'--eval-steps',2,'--hidden',3)
      self.assertTrue(data['evaluation']['isolated'])
      rows=data['evaluation']['strategies']
      matched=[[(e['engine_seed'],e['start_index'],e['start_x'],e['start_y']) for e in row['episodes']] for row in rows]
      self.assertTrue(all(row==matched[0] for row in matched))
      points.append({(e['start_x'],e['start_y']) for e in rows[0]['episodes']})
    self.assertTrue(all(points[i].isdisjoint(points[j]) for i in range(4) for j in range(i+1,4)))
    self.run_cli('--eval-partition','unknown',success=False)
    self.run_cli('--scenario','varied_keeper','--right',success=False)

  def test_variable_scenarios_resume_across_episode_boundaries(self):
    for scenario in ('varied_empty_goal','varied_keeper','2v1'):
      common=('--scenario',scenario,'--seed',19,'--hidden',3,'--epochs',1,'--minibatch',4,
              '--rollout',4,'--episode-limit',3,'--cadence',2,'--eval-episodes',1,'--eval-steps',2,
              '--eval-partition','test')
      with tempfile.TemporaryDirectory() as directory:
        full,prefix,resumed=[Path(directory)/name for name in ('full','prefix','resumed')]
        a=self.run_cli(*common,'--updates',2,'--save',full)
        self.run_cli(*common,'--updates',1,'--save',prefix)
        b=self.run_cli(*common,'--updates',1,'--load',prefix,'--save',resumed)
        self.assertEqual(full.read_bytes(),resumed.read_bytes())
        self.assertEqual(a['iterations'][1:],b['iterations'])
        self.assertEqual(a['evaluation'],b['evaluation'])
        other='varied_keeper' if scenario=='varied_empty_goal' else 'varied_empty_goal'
        self.run_cli('--scenario',other,'--seed',19,'--hidden',3,'--epochs',1,'--minibatch',4,
                     '--episode-limit',3,'--cadence',2,'--updates',0,'--load',full,success=False)

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

  def test_two_on_one_frozen_geometry_and_diagnostics(self):
    starts=[]
    for partition in ('train','validation','test','confirmation','replication','prospective','holdout'):
      report=self.run_cli('--scenario','2v1','--updates',0,'--hidden',3,'--no-initial-eval',
                          '--eval-partition',partition,'--eval-episodes',4,'--eval-steps',4)
      self.assertEqual(report['players'],1)
      self.assertEqual(report['native_agents'],2)
      self.assertTrue(report['fixed_teammate_builtin_ai'])
      self.assertTrue(report['evaluation']['isolated'])
      strategies=report['evaluation']['strategies']
      identities=[]
      for strategy in strategies:
        identities.append([(e['engine_seed'],e['start_index'],e['start_x'],e['start_y']) for e in strategy['episodes']])
        for e in strategy['episodes']:
          self.assertLessEqual(e['completed_passes'],e['pass_requests'])
          self.assertLessEqual(e['pass_requests'],e['steps'])
          self.assertGreaterEqual(e['turnovers'],0)
      self.assertTrue(all(rows==identities[0] for rows in identities))
      starts.append({(x,y) for _,_,x,y in identities[0]})
    self.assertTrue(all(starts[i].isdisjoint(starts[j]) for i in range(len(starts)) for j in range(i+1,len(starts))))
    self.run_cli('--scenario','2v1','--right',success=False)
    self.run_cli('--scenario','2v1','--players',2,success=False)
    self.run_cli('--scenario','2v1','--v2',success=False)


if __name__ == '__main__': unittest.main()
