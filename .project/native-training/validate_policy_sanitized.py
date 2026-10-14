#!/usr/bin/env python3
"""ASan/UBSan/LSan for the standalone policy math; engine coverage is separate."""
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
  env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
             UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
  def run(name, command):
    print(name, flush=True)
    log = output / (name + '.log')
    start = time.monotonic()
    with log.open('wb') as stream:
      result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report['commands'].append({'name': name, 'argv': command, 'exit_code': result.returncode,
                               'seconds': time.monotonic() - start,
                               'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if result.returncode: raise RuntimeError(name + ' failed')
  try:
    run('configure', ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build),
                     '-DCMAKE_BUILD_TYPE=Debug', '-DCMAKE_CXX_STANDARD=23',
                     '-DCMAKE_CXX_FLAGS_DEBUG=-O1 -g1', '-DBUILD_PYTHON_BINDINGS=OFF',
                     '-DFOOTBALL_ENABLE_SANITIZERS=ON',
                     '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')])
    run('build', ['cmake', '--build', str(build), '--target', 'categorical_policy_contract', '--parallel', '1'])
    flags = (build / 'CMakeFiles/football_categorical_policy.dir/flags.make').read_text()
    if '-fsanitize=address,undefined' not in flags: raise RuntimeError('Policy library not instrumented')
    run('policy-contract', [str(build / 'bin/categorical_policy_contract')])
    run('linkage', ['ldd', str(build / 'bin/categorical_policy_contract')])
    linkage = (output / 'linkage.log').read_text()
    if 'libasan' not in linkage or 'libubsan' not in linkage or 'libpython' in linkage or 'not found' in linkage:
      raise RuntimeError('Policy sanitizer linkage mismatch')
    report.update(passed=True, error=None)
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_after'] != report['source_before']:
      report.update(passed=False, error='Source changed during policy sanitizer verification')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
