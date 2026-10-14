#!/usr/bin/env python3
"""Reconcile the S4 final acceptance logs and source manifest on Linux."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('native_validation', Path(__file__).with_name('validate.py'))
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def main():
  current = validation.source_fingerprint()
  results = []
  for name in ('nt-4.4-integration-20261015-a', 'nt-4.4-experiments-20261015-b',
               'nt-4.4-evaluation-sanitized-20261015-a'):
    directory = ROOT / '.project/native-training/evidence' / name
    report = json.loads((directory / 'report.json').read_text())
    if report.get('passed') is not True:
      raise RuntimeError(f'{name}: acceptance failed')
    if report['source_before'] != current or report['source_after'] != current:
      raise RuntimeError(f'{name}: source manifest differs')
    for command in report['commands']:
      log = command.get('log', command['name'] + '.log')
      if command['exit_code'] != 0 or validation.sha(directory / log) != command['sha256']:
        raise RuntimeError(f'{name}: invalid command evidence {command["name"]}')
    results.append(dict(report=name, commands=len(report['commands'])))
  print(json.dumps(dict(passed=True, source_sha256=current['sha256'],
                       files=current['files'], reports=results), indent=2))


if __name__ == '__main__':
  main()
