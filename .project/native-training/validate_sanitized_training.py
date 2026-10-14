#!/usr/bin/env python3
"""Build and run the complete native engine under ASan/UBSan (Linux, serial)."""
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
  if build == ROOT or ROOT in build.parents:
    parser.error('Use an isolated build outside the repository')
  output.mkdir(parents=True, exist_ok=False)
  env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),
             ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:quarantine_size_mb=16:thread_local_quarantine_size_kb=256',
             UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
  report = {'passed': False, 'commands': [], 'source_before': source_fingerprint(),
            'sanitizer_options': {key: env[key] for key in ('ASAN_OPTIONS', 'UBSAN_OPTIONS')}}
  report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

  def run(name, command):
    print(name, flush=True)
    start = time.monotonic()
    log = output / (name + '.log')
    with log.open('wb') as stream:
      result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report['commands'].append({'name': name, 'command': command, 'exit_code': result.returncode,
                               'seconds': time.monotonic() - start, 'log': log.name,
                               'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if result.returncode:
      raise RuntimeError(f'{name} failed; see {log}')

  try:
    run('compiler', ['c++', '--version'])
    run('configure', ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build),
                     '-DCMAKE_BUILD_TYPE=Debug', '-DCMAKE_CXX_FLAGS_DEBUG=-O1 -g1',
                     '-DCMAKE_CXX_STANDARD=23', '-DBUILD_PYTHON_BINDINGS=OFF',
                     '-DFOOTBALL_ENABLE_SANITIZERS=ON',
                     f'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / "bin"}'])
    targets = ['engine_native_training_contract', 'engine_training_snapshot_contract',
               'engine_training_restore_contract', 'engine_training_soak_contract']
    run('build', ['cmake', '--build', str(build), '--target', *targets, '--parallel', '1'])
    # Compiler flags and dependency records prove core instrumentation, not only test instrumentation.
    flags = list(build.glob('CMakeFiles/*/flags.make'))
    report['instrumented_targets'] = []
    for path in flags:
      if path.parent.name in ('football_engine.dir', 'gamelib.dir', 'blunted2.dir', 'baselib.dir'):
        text = path.read_text()
        if '-fsanitize=address,undefined' not in text:
          raise RuntimeError(f'Uninstrumented core target: {path.parent.name}')
        report['instrumented_targets'].append(path.parent.name)
    if len(report['instrumented_targets']) != 4:
      raise RuntimeError('Missing core instrumentation evidence')
    run('linkage', ['ldd', str(build / 'bin/engine_training_restore_contract')])
    linkage = (output / 'linkage.log').read_text()
    if 'libasan' not in linkage or 'libubsan' not in linkage or 'not found' in linkage or 'libpython' in linkage:
      raise RuntimeError('Sanitizer/native linkage mismatch')
    for target in targets:
      run(target, [str(build / 'bin' / target)])
    report['passed'] = True
    report['error'] = None
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_after'] != report['source_before']:
      report.update(passed=False, error='Source changed during sanitizer verification')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
