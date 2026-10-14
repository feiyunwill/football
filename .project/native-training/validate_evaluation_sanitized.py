#!/usr/bin/env python3
"""Incrementally verify the newly added training/evaluation executable under sanitizers."""
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
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  build, output = args.build_root.resolve(), args.output.resolve()
  if build == ROOT or ROOT in build.parents: parser.error('Use an isolated build')
  output.mkdir(parents=True, exist_ok=False)
  report = {'passed': False, 'source_before': source_fingerprint(), 'commands': []}
  report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),
             ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:quarantine_size_mb=16',
             UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
  def run(name, command):
    print(name, flush=True)
    log = output / (name + '.log'); start = time.monotonic()
    with log.open('wb') as stream:
      result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report['commands'].append({'name': name, 'argv': command, 'exit_code': result.returncode,
                               'seconds': time.monotonic() - start,
                               'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if result.returncode: raise RuntimeError(name + ' failed')
  try:
    run('configure', ['cmake','-S',str(ROOT / 'engine'),'-B',str(build),'-DCMAKE_BUILD_TYPE=Debug',
                     '-DCMAKE_CXX_STANDARD=23','-DCMAKE_CXX_FLAGS_DEBUG=-O1 -g1',
                     '-DBUILD_PYTHON_BINDINGS=OFF','-DFOOTBALL_ENABLE_SANITIZERS=ON',
                     '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')])
    run('build',['cmake','--build',str(build),'--target','native_ppo_train','--parallel','1'])
    for target in ('football_engine','football_ppo_evaluation','football_ppo_learner','football_ppo_math'):
      if '-fsanitize=address,undefined' not in (build / f'CMakeFiles/{target}.dir/flags.make').read_text():
        raise RuntimeError('Uninstrumented target: ' + target)
    binary = str(build / 'bin/native_ppo_train')
    run('training-evaluation',[binary,'--updates','2','--rollout','8','--hidden','8','--epochs','2',
                               '--minibatch','4','--eval-episodes','1','--eval-steps','16'])
    data=json.loads((output / 'training-evaluation.log').read_text())
    if not data['evaluation']['isolated'] or data['version'] != 2 or not all(row['parameter_delta'] > 0 for row in data['iterations']):
      raise RuntimeError('Missing update/evaluation isolation')
    run('linkage',['ldd',binary])
    linkage=(output / 'linkage.log').read_text()
    if 'libasan' not in linkage or 'libubsan' not in linkage or 'libpython' in linkage or 'not found' in linkage:
      raise RuntimeError('Sanitizer/native linkage mismatch')
    report.update(passed=True,error=None)
  except Exception as error:
    report['error']=str(error)
  finally:
    report['source_after']=source_fingerprint()
    if report['source_before'] != report['source_after']: report.update(passed=False,error='Source changed during sanitizer check')
    (output / 'report.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps({'passed':report['passed'],'error':report.get('error')},indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
