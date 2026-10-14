#!/usr/bin/env python3
"""Run freshly exported native contracts with relocated package resources."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import validate


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--package', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  build, package, output = args.build_root.resolve(), args.package.resolve(), args.output.resolve()
  if output.exists():
    parser.error('Use new evidence output')
  output.mkdir(parents=True)
  report = dict(passed=False, source_before=validate.source_fingerprint(), commands=[],
                validator_sha256=validate.sha(Path(__file__)))
  env = {name: value for name, value in os.environ.items()
         if name not in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH') and not name.startswith('GFOOTBALL_')}
  env.update(GFOOTBALL_DATA_DIR=str(package / 'data'),
             GFOOTBALL_FONT=str(package / 'fonts/AlegreyaSansSC-ExtraBold.ttf'))
  try:
    report['core_sha256'] = validate.sha(build / 'libfootball_engine.so')
    if report['core_sha256'] != validate.sha(package / 'libfootball_engine.so'):
      raise RuntimeError('Contract build core differs from delivered native package')
    for name in ('engine_native_training_contract', 'engine_training_snapshot_contract',
                 'engine_training_restore_contract', 'engine_training_soak_contract',
                 'categorical_policy_contract', 'engine_native_policy_contract',
                 'ppo_math_contract', 'engine_ppo_checkpoint_contract'):
      print(name, flush=True)
      binary = build / 'bin' / name
      log = output / (name + '.log'); start = time.monotonic()
      with log.open('wb') as stream:
        process = subprocess.run([binary], cwd=package.parent, env=env, stdout=stream,
                                 stderr=subprocess.STDOUT, check=False)
      report['commands'].append(dict(name=name, argv=[str(binary)], exit_code=process.returncode,
                                     seconds=time.monotonic()-start, log=log.name,
                                     sha256=validate.sha(log), binary_sha256=validate.sha(binary)))
      if process.returncode:
        raise RuntimeError(name + ' failed')
    report['passed'] = True
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = validate.source_fingerprint()
    if report['source_after'] != report['source_before']:
      report.update(passed=False, error='Sources changed during native delivery contracts')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(dict(passed=report['passed'], error=report.get('error'))))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
