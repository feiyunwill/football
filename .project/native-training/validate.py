#!/usr/bin/env python3
"""Build/stage actual native artifacts and record S0 integration evidence.

Linux only. Requires CMake/compiler/system engine dependencies and a Python
interpreter with this project's runtime dependencies plus pybind11 installed.
Uses one isolated incremental build directory, configuring bindings ON then OFF.
No repository binaries or installed Python packages are overwritten.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
  with path.open('rb') as stream:
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_fingerprint():
  names = subprocess.check_output(
      ['git', 'ls-files', '-co', '--exclude-standard', '--', 'engine', 'gfootball',
       'setup.py', 'pyproject.toml'], cwd=ROOT).decode().splitlines()
  suffixes = {'.cpp', '.hpp', '.h', '.py', '.cmake', '.toml'}
  manifest = {}
  for name in sorted(set(names)):
    path = ROOT / name
    if path.is_file() and (path.suffix in suffixes or path.name == 'CMakeLists.txt' or
                           name.startswith(('engine/data/', 'engine/fonts/'))):
      manifest[name] = sha(path)
  digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
  return dict(sha256=digest, files=len(manifest), manifest=manifest)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--python', default=sys.executable)
  parser.add_argument('--build-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  if platform.system() != 'Linux':
    parser.error('Run this Linux acceptance entry point inside Linux/WSL')
  build, output = args.build_root.resolve(), args.output.resolve()
  if build == ROOT or ROOT in build.parents:
    parser.error('build-root must be outside the repository')
  if output.exists():
    parser.error('Use a new output directory; previous evidence is preserved')
  output.mkdir(parents=True)
  build.mkdir(parents=True, exist_ok=True)
  stage = build / 'validation-stage' / 'gfootball_engine'
  stage.mkdir(parents=True, exist_ok=True)
  env = dict(os.environ)
  env.update(PYTHONPATH=str(stage.parent) + os.pathsep + str(ROOT),
             GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
             GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  env['GFOOTBALL_CATEGORICAL_CONTRACT'] = str(build / 'bin/categorical_policy_contract')
  env['GFOOTBALL_PPO_MATH_CONTRACT'] = str(build / 'bin/ppo_math_contract')
  env['GFOOTBALL_NATIVE_PPO_TRAIN'] = str(build / 'bin/native_ppo_train')
  report = dict(passed=False, platform=platform.platform(), commands=[],
                git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip())
  before = source_fingerprint()
  report['source_before'] = before

  def run(name, command):
    print(name, flush=True)
    log = output / (name + '.log')
    start = time.monotonic()
    with log.open('w') as stream:
      result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                              stderr=subprocess.STDOUT, check=False)
    report['commands'].append(dict(name=name, command=command, exit_code=result.returncode,
                                   seconds=time.monotonic() - start, log=log.name, sha256=sha(log)))
    if result.returncode:
      raise RuntimeError(name + ' failed; see ' + str(log))

  try:
    package_probe = (
        'import json,sys,importlib.metadata as m; '
        'print(json.dumps(dict(python=sys.version,packages={n:m.version(n) for n in '
        "('numpy','gymnasium','pybind11','opencv-python','absl-py','six','pygame-ce')})))")
    run('python-environment', [args.python, '-c', package_probe])
    report['python'] = json.loads((output / 'python-environment.log').read_text())
    pybind_dir = subprocess.check_output([args.python, '-m', 'pybind11', '--cmakedir']).decode().strip()
    run('cmake-version', ['cmake', '--version'])
    run('compiler-version', ['c++', '--version'])
    configure = ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build),
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=23',
                 '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')]
    run('configure-python', configure + ['-DBUILD_PYTHON_BINDINGS=ON',
        '-DPython_EXECUTABLE=' + args.python, '-Dpybind11_DIR=' + pybind_dir])
    run('build-python', ['cmake', '--build', str(build), '--target', 'game',
                         'categorical_policy_contract', 'ppo_math_contract', 'native_policy_rollout',
                         'native_ppo_train', '--parallel', '1'])
    shutil.copy2(ROOT / 'engine/__init__.py', stage / '__init__.py')
    for name, destination in [('libgame.so', '_gameplayfootball.so'),
                              ('libfootball_engine.so', 'libfootball_engine.so')]:
      shutil.copy2(build / name, stage / destination)
    for name in ('data', 'fonts'):
      target = stage / name
      if target.is_symlink():
        if target.resolve() != (ROOT / 'engine' / name).resolve():
          raise RuntimeError('Unexpected existing stage resource link: ' + str(target))
      elif target.exists():
        raise RuntimeError('Unexpected existing stage resource directory: ' + str(target))
      else:
        target.symlink_to(ROOT / 'engine' / name, target_is_directory=True)
    module_probe = (
        'import sys; from pathlib import Path; import gfootball_engine as e; '
        'assert Path(e._gameplayfootball.__file__).resolve()==Path(sys.argv[1]).resolve(); '
        'assert hasattr(e.NativeTrainingEnv, "step_many"); print(e._gameplayfootball.__file__)')
    run('staged-module', [args.python, '-c', module_probe, str(stage / '_gameplayfootball.so')])
    report['artifacts'] = {name: sha(stage / name) for name in ('_gameplayfootball.so', 'libfootball_engine.so')}
    run('python-integration', [args.python, '-m', 'unittest', 'gfootball.test_native_training',
                               'gfootball.test_gymnasium_native', 'gfootball.test_training_snapshot',
                               'gfootball.test_training_resources', 'gfootball.test_training_workers',
                               'gfootball.test_training_sampler', 'gfootball.test_categorical_policy',
                               'gfootball.test_ppo_math', 'gfootball.test_native_ppo_cli', '-v'])
    run('configure-native', configure + ['-DBUILD_PYTHON_BINDINGS=OFF'])
    run('build-native', ['cmake', '--build', str(build), '--target',
                         'engine_native_training_contract', 'engine_training_snapshot_contract',
                         'engine_training_restore_contract', 'engine_training_soak_contract',
                         'engine_native_policy_contract', 'engine_ppo_checkpoint_contract', '--parallel', '1'])
    contract = build / 'bin/engine_native_training_contract'
    run('native-contract', [str(contract)])
    run('snapshot-format-contract', [str(build / 'bin/engine_training_snapshot_contract')])
    run('training-restore-contract', [str(build / 'bin/engine_training_restore_contract')])
    run('training-soak-contract', [str(build / 'bin/engine_training_soak_contract')])
    run('categorical-policy-contract', [str(build / 'bin/categorical_policy_contract')])
    run('native-policy-contract', [str(build / 'bin/engine_native_policy_contract')])
    run('ppo-math-contract', [str(build / 'bin/ppo_math_contract')])
    run('ppo-checkpoint-contract', [str(build / 'bin/engine_ppo_checkpoint_contract')])
    run('native-policy-rollout', [str(build / 'bin/native_policy_rollout'), '42', '11', '32'])
    run('native-ppo-train', [str(build / 'bin/native_ppo_train'), '--updates', '1', '--rollout', '8',
                           '--hidden', '8', '--epochs', '2', '--minibatch', '4', '--eval-episodes', '1', '--eval-steps', '16'])
    run('native-ppo-linkage', ['ldd', str(build / 'bin/native_ppo_train')])
    ppo_linkage = (output / 'native-ppo-linkage.log').read_text()
    if any(token in ppo_linkage for token in ('libpython', 'libgame.so', '_gameplayfootball', 'not found')):
      raise RuntimeError('Native PPO executable has missing or Python adapter dependencies')
    run('native-policy-linkage', ['ldd', str(build / 'bin/native_policy_rollout')])
    policy_linkage = (output / 'native-policy-linkage.log').read_text()
    if any(token in policy_linkage for token in ('libpython', 'libgame.so', '_gameplayfootball', 'not found')):
      raise RuntimeError('Policy rollout has missing or Python adapter dependencies')
    run('native-linkage', ['ldd', str(contract)])
    linkage = (output / 'native-linkage.log').read_text()
    if any(token in linkage for token in ('libpython', 'libgame.so', '_gameplayfootball', 'not found')):
      raise RuntimeError('Native contract has missing or Python adapter dependencies')
    report['native_contract_sha256'] = sha(contract)
    report['native_core_sha256'] = sha(build / 'libfootball_engine.so')
    if report['native_core_sha256'] != report['artifacts']['libfootball_engine.so']:
      raise RuntimeError('Python and native acceptance used different core artifacts')
    report['passed'] = True
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = source_fingerprint()
    if report['source_after'] != before:
      report.update(passed=False, error='Source changed during validation; rerun against stable sources')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(dict(passed=report['passed'], report=str(output / 'report.json'),
                        error=report.get('error')), indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
