#!/usr/bin/env python3
"""Record bounded rotating profiles against the actual isolated staged extension."""
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
  parser.add_argument('--python', required=True)
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--steps', type=int, default=256)
  parser.add_argument('--repeats', type=int, default=6)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  stage = args.build_root.resolve() / 'validation-stage'
  env = dict(os.environ, PYTHONPATH=str(stage) + os.pathsep + str(ROOT),
             GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  before = source_fingerprint()
  report = {'passed':False, 'source_before':before}
  command = [args.python, '-m', 'gfootball.profile_native_training', '--steps', str(args.steps),
             '--repeats', str(args.repeats), '--output', str(output / 'profiles.json')]
  try:
    for name in ('_gameplayfootball.so', 'libfootball_engine.so'):
      path = stage / 'gfootball_engine' / name
      if not path.is_file(): raise RuntimeError(f'Missing staged artifact: {path}')
      report.setdefault('artifacts', {})[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    start = time.monotonic()
    log = output / 'profile.log'
    with log.open('wb') as stream:
      result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report['command'] = {'argv':command, 'exit_code':result.returncode, 'seconds':time.monotonic() - start,
                         'sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    if result.returncode: raise RuntimeError(f'Profile failed; see {log}')
    workloads = json.loads((output / 'profiles.json').read_text())['workloads']
    for players in (1, 11):
      for cadence in (2, 10):
        pair = [w for w in workloads if w['players'] == players and w['cadence'] == cadence]
        if len(pair) != 2 or pair[0]['digests'] != pair[1]['digests']:
          raise RuntimeError('Instrumentation changed workload state')
    report['passed'] = True
    report['error'] = None
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_after'] != before:
      report.update(passed=False, error='Source changed while profiling')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed':report['passed'], 'error':report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
