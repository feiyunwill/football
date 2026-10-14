#!/usr/bin/env python3
"""Reconcile current goal artifacts and acceptance evidence; not a substitute for review."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import quality
import validate

ROOT = validate.ROOT
BASE = ROOT / '.project/native-training'


def load_report(relative, require_pass=True):
  path = BASE / relative
  report = json.loads(path.read_text())
  if require_pass and report.get('passed') is not True:
    raise RuntimeError('Nonpassing report: ' + relative)
  for command in report.get('commands', []):
    # Delivery B is retained for its successful build prerequisites, not its failed packager.
    if command['exit_code'] != 0:
      if require_pass: raise RuntimeError('Failed command: ' + command['name'])
      continue
    log = command.get('log', command['name'] + '.log')
    if validate.sha(path.parent / log) != command['sha256']:
      raise RuntimeError('Log mismatch: ' + str(path.parent / log))
    if 'stderr' in command and validate.sha(path.parent / command['stderr']) != command['stderr_sha256']:
      raise RuntimeError('Stderr mismatch: ' + command['name'])
  return report


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--require-final-ledger', action='store_true')
  args = parser.parse_args()
  args.output.mkdir(parents=True, exist_ok=False)
  result = dict(passed=False, checks=[], source=validate.source_fingerprint(),
                auditor_sha256=validate.sha(Path(__file__)))
  try:
    state = json.loads((BASE / 'state.json').read_text())
    for stage in state['stages']:
      for task in stage['tasks']:
        if task['status'] != 'complete' or not task.get('commit'):
          raise RuntimeError('Incomplete/uncommitted task: ' + task['id'])
        subprocess.run(['git', 'cat-file', '-e', task['commit'] + '^{commit}'], cwd=ROOT, check=True)
      if stage['id'] != 'S5' or args.require_final_ledger:
        if stage['status'] != 'complete' or stage['review'] != 'passed':
          raise RuntimeError('Stage review incomplete: ' + stage['id'])
        review = BASE / stage['review_report']
        if not review.is_file(): raise RuntimeError('Missing stage review')
        result['checks'].append(dict(review=stage['id'], sha256=validate.sha(review)))
    result['checks'].append(dict(committed_tasks=sum(len(s['tasks']) for s in state['stages'])))
    integration = BASE / 'evidence/s5-review-integration-20261015-b/report.json'
    result['checks'].append(quality.verify(integration, sys.executable))
    negative = subprocess.run(['/tmp/football-native-quality-empty-env-20261015/bin/python',
                               str(BASE / 'quality.py'), 'verify', '--output', str(integration.parent)],
                              capture_output=True, text=True)
    if negative.returncode == 0 or 'Acceptance environment changed' not in negative.stderr:
      raise RuntimeError('Environment freshness negative case did not reject as expected')
    result['checks'].append(dict(empty_environment_rejected=True, exit_code=negative.returncode,
                                diagnostic=negative.stderr.strip()))
    for relative in ('evidence/nt-4.4-integration-20261015-a/report.json',
                     'evidence/nt-4.4-experiments-20261015-b/report.json',
                     'evidence/nt-4.4-evaluation-sanitized-20261015-a/report.json',
                     'evidence/nt-5.2-delivery-20261015-d/report.json',
                     'evidence/nt-5.2-native-contracts-20261015-a/report.json'):
      report = load_report(relative)
      if report['source_before'] != result['source'] or report['source_after'] != result['source']:
        raise RuntimeError('Production manifest differs: ' + relative)
      result['checks'].append(dict(report=relative, commands=len(report['commands'])))
    delivery = load_report('evidence/nt-5.2-delivery-20261015-d/report.json')
    parent = Path(delivery['reused_build_evidence']['report'])
    if validate.sha(parent) != delivery['reused_build_evidence']['sha256']:
      raise RuntimeError('Reused build report changed')
    load_report(str(parent.relative_to(BASE)), require_pass=False)
    package = Path(delivery['native_package']['path'])
    wheel = package.parent / 'wheels' / delivery['wheel']['name']
    if validate.sha(wheel) != delivery['wheel']['sha256']:
      raise RuntimeError('Delivered wheel changed')
    for name, expected in delivery['native_package']['manifest']['files'].items():
      if validate.sha(package / name) != expected:
        raise RuntimeError('Delivered native file changed: ' + name)
    contracts = load_report('evidence/nt-5.2-native-contracts-20261015-a/report.json')
    if contracts['core_sha256'] != validate.sha(package / 'libfootball_engine.so'):
      raise RuntimeError('Delivered core differs from tested core')
    for command in contracts['commands']:
      if validate.sha(Path(command['argv'][0])) != command['binary_sha256']:
        raise RuntimeError('Native contract binary changed')
    result['checks'].append(dict(wheel_sha256=delivery['wheel']['sha256'],
                                native_files=len(delivery['native_package']['manifest']['files']),
                                fresh_native_contracts=len(contracts['commands'])))
    reproduction = load_report('evidence/nt-5.3-reproduction-20261015-a/report.json')
    if reproduction['script_sha256'] != validate.sha(BASE / 'reproduce_training.py'):
      raise RuntimeError('Reproduction script changed')
    checkpoint_folder = Path('/tmp/football-native-reproduction-20261015-a-checkpoints')
    if validate.sha(checkpoint_folder / 'full.fppo') != reproduction['checkpoint_sha256'] or \
       (checkpoint_folder / 'full.fppo').read_bytes() != (checkpoint_folder / 'resumed.fppo').read_bytes():
      raise RuntimeError('Reproduction checkpoint changed')
    result['checks'].append(dict(reproduction=True, transitions=reproduction['transitions']))
    for name in ('ROADMAP.md', 'COMPATIBILITY.md', 'SNAPSHOT.md', 'PPO_DECISION.md',
                 'PPO_CHECKPOINT.md', 'TRAINING_EXPERIMENTS.md', 'QUALITY.md', 'DELIVERY.md',
                 'PLATFORMS.md', 'MIGRATION.md'):
      path = BASE / name
      if not path.is_file() or not path.stat().st_size:
        raise RuntimeError('Missing required document: ' + name)
    result['passed'] = True
  except Exception as error:
    result['error'] = str(error)
  (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
  print(json.dumps(dict(passed=result['passed'], error=result.get('error')), indent=2))
  return 0 if result['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
