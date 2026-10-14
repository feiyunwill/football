#!/usr/bin/env python3
"""Archive rotating real-process replay, resource and throughput evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import time
from validate import ROOT, source_fingerprint


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--python', required=True)
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--steps', type=int, default=128)
  parser.add_argument('--repeats', type=int, default=3)
  args = parser.parse_args()
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  stage = args.build_root.resolve() / 'validation-stage'
  env = dict(os.environ, PYTHONPATH=str(stage) + os.pathsep + str(ROOT),
             GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  report = {'passed': False, 'source_before': source_fingerprint(),
            'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
  command = [args.python, '-m', 'gfootball.benchmark_training_workers', '--steps', str(args.steps),
             '--repeats', str(args.repeats), '--output', str(output / 'workers.json')]
  try:
    report['artifacts'] = {name: hashlib.sha256((stage / 'gfootball_engine' / name).read_bytes()).hexdigest()
                           for name in ('_gameplayfootball.so', 'libfootball_engine.so')}
    start = time.monotonic()
    log = output / 'workers.log'
    with log.open('wb') as stream:
      process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                 stderr=subprocess.STDOUT, start_new_session=True)
      try:
        exit_code = process.wait(timeout=900)
      except subprocess.TimeoutExpired:
        # Kill this benchmark session, including workers/resource tracker, not only its parent.
        try:
          os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
          pass
        process.wait(timeout=5)
        raise
    report['command'] = {'argv': command, 'exit_code': exit_code,
                         'seconds': time.monotonic() - start, 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    if exit_code: raise RuntimeError(f'Worker benchmark failed; see {log}')
    data = json.loads((output / 'workers.json').read_text())
    if Path(data['loaded_module']) != (stage / 'gfootball_engine/_gameplayfootball.so').resolve():
      raise RuntimeError('Wrong staged extension loaded')
    if len(data['workloads']) != 12: raise RuntimeError('Missing worker workload')
    report.update(passed=True, error=None)
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_after'] != report['source_before']:
      report.update(passed=False, error='Source changed during worker measurement')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
