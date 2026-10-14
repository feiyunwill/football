#!/usr/bin/env python3
"""Native training acceptance entry; independent of existing milestone gates.

run always executes the full isolated validator. verify rejects stale source,
changed runner, failed/missing checks, altered logs, or skipped Python tests.
Evidence is local acceptance, not a signed attestation or a remote CI result.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import validate

REQUIRED = frozenset('''python-environment cmake-version compiler-version
configure-python build-python staged-module python-integration configure-native
build-native native-contract snapshot-format-contract training-restore-contract
training-soak-contract categorical-policy-contract native-policy-contract
ppo-math-contract ppo-checkpoint-contract native-policy-rollout native-ppo-train
native-ppo-linkage native-policy-linkage native-linkage'''.split())


def verify(path, python=sys.executable):
  path = Path(path).resolve()
  report = json.loads(path.read_text())
  if report.get('passed') is not True or report.get('acceptance_schema') != 2:
    raise ValueError('No passing current-schema acceptance')
  if report.get('runner_sha256') != validate.sha(Path(validate.__file__)):
    raise ValueError('Acceptance runner changed')
  if report.get('acceptance_inputs') != {name: validate.sha(validate.ROOT / name)
                                        for name in validate.ACCEPTANCE_FILES}:
    raise ValueError('Acceptance infrastructure changed')
  environment = validate.runtime_identity(python)
  if report.get('environment_before') != environment or report.get('environment_after') != environment:
    raise ValueError('Acceptance environment changed; use the validated --python or rerun')
  current = validate.source_fingerprint()
  if report.get('source_before') != current or report.get('source_after') != current:
    raise ValueError('Source evidence is stale')
  commands = report['commands']
  names = [c['name'] for c in commands]
  if len(names) != len(set(names)) or set(names) != REQUIRED:
    raise ValueError('Missing, duplicate or unknown acceptance commands')
  for command in commands:
    log = Path(command['log'])
    if log.is_absolute() or len(log.parts) != 1:
      raise ValueError('Log path must be a local filename')
    if command['exit_code'] != 0 or validate.sha(path.parent / log) != command['sha256']:
      raise ValueError('Failed command or altered log: ' + command['name'])
  integration = (path.parent / 'python-integration.log').read_text()
  match = re.search(r'^Ran (\d+) tests in ', integration, re.MULTILINE)
  if not match or int(match[1]) < 72 or 'skipped' in integration or '\nOK\n' not in integration:
    raise ValueError('Required integration suite missing, skipped or failed')
  return dict(passed=True, report=str(path), source_sha256=current['sha256'])


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('action', choices=('run', 'verify'))
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--build-root', type=Path)
  parser.add_argument('--python', default=sys.executable)
  args = parser.parse_args()
  try:
    if args.action == 'run':
      if args.build_root is None:
        parser.error('run requires --build-root outside the repository')
      subprocess.run([args.python, str(Path(validate.__file__)), '--python', args.python,
                      '--build-root', str(args.build_root), '--output', str(args.output)], check=True)
    print(json.dumps(verify(args.output / 'report.json', args.python), indent=2))
  except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
    print('native-training quality: ' + str(error), file=sys.stderr)
    return 1
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
