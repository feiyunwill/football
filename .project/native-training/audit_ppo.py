#!/usr/bin/env python3
"""Archive exact active PPO sources and validate existing CPU build/GAE behavior."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from validate import ROOT, source_fingerprint

SOURCES = [
    'engine/CMakeLists.txt',
    'engine/src/frame_sync/rl_training/training.cpp',
    'engine/src/frame_sync/rl_training/game_env_wrapper.hpp',
    'engine/src/frame_sync/rl_training/checkpoint.hpp',
    'third_party/rl-tools/include/rl_tools/rl/algorithms/ppo/ppo.h',
    'third_party/rl-tools/include/rl_tools/rl/algorithms/ppo/operations_generic.h',
    'third_party/rl-tools/include/rl_tools/rl/algorithms/ppo/loop/core/config.h',
    'third_party/rl-tools/include/rl_tools/rl/algorithms/ppo/loop/core/operations_generic.h',
    'third_party/rl-tools/include/rl_tools/rl/algorithms/ppo/loop/core/persist.h',
    'third_party/rl-tools/include/rl_tools/rl/components/on_policy_runner/on_policy_runner.h',
    'third_party/rl-tools/include/rl_tools/rl/components/on_policy_runner/operations_generic.h',
    'third_party/rl-tools/include/rl_tools/rl/components/on_policy_runner/operations_generic_per_env.h',
    'third_party/rl-tools/include/rl_tools/rl/components/on_policy_runner/persist.h',
]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  build, output = args.build_root.resolve(), args.output.resolve()
  if build == ROOT or ROOT in build.parents: parser.error('Use an isolated build outside the repository')
  build.mkdir(parents=True, exist_ok=True)
  output.mkdir(parents=True, exist_ok=False)
  report = {'passed': False, 'source_before': source_fingerprint(), 'commands': [], 'audited_sources': {}}
  report['auditor_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  for name in SOURCES:
    data = (ROOT / name).read_bytes()
    destination = output / 'sources' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    report['audited_sources'][name] = hashlib.sha256(data).hexdigest()
  probe = ROOT / '.project/native-training/rltools_ppo_probe.cpp'
  shutil.copy2(probe, output / probe.name)
  report['probe_sha256'] = hashlib.sha256(probe.read_bytes()).hexdigest()

  def run(name, command):
    print(name, flush=True)
    start = time.monotonic()
    log = output / (name + '.log')
    with log.open('wb') as stream:
      result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    report['commands'].append({'name': name, 'argv': command, 'exit_code': result.returncode,
                               'seconds': time.monotonic() - start,
                               'sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if result.returncode: raise RuntimeError(name + ' failed')

  try:
    run('compiler', ['c++', '--version'])
    run('compile-probe', ['c++', '-std=c++23', '-O2', '-I' + str(ROOT / 'third_party/rl-tools/include'),
                           str(probe), '-o', str(build / 'rltools_ppo_probe')])
    run('runtime-probe', [str(build / 'rltools_ppo_probe')])
    report['probe'] = json.loads((output / 'runtime-probe.log').read_text())
    if not report['probe']['passed']: raise RuntimeError('Vendored Gaussian/GAE probe failed')
    run('configure-legacy', ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build),
                              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=23',
                              '-DBUILD_PYTHON_BINDINGS=OFF', '-DBUILD_RL_TRAINING=ON',
                              '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')])
    run('build-legacy', ['cmake', '--build', str(build), '--target', 'rl_football_training', '--parallel', '1'])
    # This legacy target does not set FOOTBALL_RUNTIME_OUTPUT_DIRECTORY.
    run('legacy-linkage', ['ldd', str(build / 'rl_football_training')])
    linkage = (output / 'legacy-linkage.log').read_text()
    if 'libpython' in linkage or 'not found' in linkage: raise RuntimeError('Legacy native linkage failed')
    report.update(passed=True, error=None)
  except Exception as error:
    report['error'] = str(error)
  finally:
    # Do not leave the optional legacy target enabled in the shared validation build.
    try:
      run('restore-build-options', ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build), '-DBUILD_RL_TRAINING=OFF'])
    except Exception as error:
      report.update(passed=False, error=str(error))
    report['source_after'] = source_fingerprint()
    if report['source_before'] != report['source_after']:
      report.update(passed=False, error='Source changed during PPO audit')
    for name, digest in report['audited_sources'].items():
      if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
        report.update(passed=False, error='Vendored audit source changed')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps({'passed': report['passed'], 'error': report.get('error')}, indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
