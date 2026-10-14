#!/usr/bin/env python3
"""Bounded multi-seed real updates, baselines, frozen evaluation and process resume."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from validate import ROOT, source_fingerprint


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--work-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  build, work, output = args.build_root.resolve(), args.work_root.resolve(), args.output.resolve()
  if work == ROOT or ROOT in work.parents: parser.error('Binary checkpoint work-root must be outside the repository')
  work.mkdir(parents=True, exist_ok=False); output.mkdir(parents=True, exist_ok=False)
  binary = build / 'bin/native_ppo_train'
  env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  report = {'passed': False, 'source_before': source_fingerprint(), 'commands': [], 'experiments': []}
  report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  report['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
  def run(name, command):
    print(name, flush=True)
    start = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=180)
    log = result.stdout + result.stderr; (output / (name + '.log')).write_bytes(log)
    report['commands'].append({'name': name, 'argv': command, 'exit_code': result.returncode,
                               'seconds': time.monotonic() - start, 'sha256': hashlib.sha256(log).hexdigest()})
    if result.returncode: raise RuntimeError('Native experiment failed: ' + name)
    data = json.loads(result.stdout)
    (output / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')
    if not data['evaluation']['isolated'] or data['state_before_evaluation_sha256'] != data['state_sha256']:
      raise RuntimeError('Evaluation mutated training state')
    return data
  try:
    for scenario in ('empty_goal', '11v11'):
      for seed in (7, 42, 123):
        name = f'{scenario}-seed{seed}'
        common = [str(binary), '--scenario', scenario, '--seed', str(seed), '--hidden', '16',
                  '--epochs', '4', '--minibatch', '32', '--rollout', '128', '--episode-limit', '128',
                  '--eval-seed', '12345', '--eval-episodes', '3', '--eval-steps', '96']
        full_file, prefix_file, resumed_file = [work / (name + suffix) for suffix in ('-full.bin','-prefix.bin','-resumed.bin')]
        full = run(name + '-full', common + ['--updates','6','--save',str(full_file)])
        # Avoid duplicate options: construct the no-evaluation prefix explicitly.
        prefix_common = common.copy(); prefix_common[prefix_common.index('--eval-episodes') + 1] = '0'
        prefix = run(name + '-prefix', prefix_common + ['--updates','3','--save',str(prefix_file)])
        resumed = run(name + '-resumed', common + ['--updates','3','--load',str(prefix_file),
                                                 '--save',str(resumed_file),'--no-initial-eval'])
        frozen = run(name + '-frozen', common + ['--updates','0','--load',str(full_file),'--no-initial-eval'])
        if (full['iterations'][:3] != prefix['iterations'] or full['iterations'][3:] != resumed['iterations']
            or full['state_sha256'] != resumed['state_sha256'] or full_file.read_bytes() != resumed_file.read_bytes()
            or full['evaluation'] != resumed['evaluation'] or full['evaluation'] != frozen['evaluation']
            or frozen['state_sha256'] != full['state_sha256']):
          raise RuntimeError('New-process training/evaluation replay diverged: ' + name)
        if any(not row['parameter_delta'] > 0 for row in full['iterations']):
          raise RuntimeError('Missing real parameter update')
        for evaluation in (full['initial_evaluation'], full['evaluation']):
          strategies = evaluation['strategies']
          if not evaluation['isolated'] or len(strategies) != 4: raise RuntimeError('Missing baseline evaluation')
          seeds = [tuple(row['engine_seed'] for row in strategy['episodes']) for strategy in strategies]
          if any(row != seeds[0] for row in seeds) or len(seeds[0]) != 3:
            raise RuntimeError('Strategies did not use matched engine episodes')
        report['experiments'].append({'scenario': scenario, 'seed': seed,
                                     'updates': full['iterations'], 'initial': full['initial_evaluation'],
                                     'final': full['evaluation'], 'state_sha256': full['state_sha256'],
                                     'checkpoint_bytes': full['checkpoint_bytes'],
                                     'checkpoint_sha256': hashlib.sha256(full_file.read_bytes()).hexdigest()})
    report.update(passed=True, error=None)
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_before'] != report['source_after']:
      report.update(passed=False, error='Source changed during native PPO experiments')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
