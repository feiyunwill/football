#!/usr/bin/env python3
"""Snapshot exact current worktree, install its wheel and relocate native PPO on Linux."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

import validate

ROOT = validate.ROOT


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--work-root', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--reuse-wheel-report', type=Path,
                      help='Reuse an audited clean wheel build after a later runtime validation failure')
  args = parser.parse_args()
  work, output = args.work_root.resolve(), args.output.resolve()
  if platform.system() != 'Linux' or work == ROOT or ROOT in work.parents:
    parser.error('Use a new Linux work directory outside the repository')
  if (work.exists() and not args.reuse_wheel_report) or output.exists():
    parser.error('Work/output must be new directories; existing evidence is preserved')
  work.mkdir(parents=True, exist_ok=bool(args.reuse_wheel_report)); output.mkdir(parents=True)
  suffix = '-' + output.name if args.reuse_wheel_report else ''
  source, wheelhouse, venv, bundle = [work / name for name in ('source', 'wheels', 'installed-env' + suffix, 'native-package' + suffix)]
  if not args.reuse_wheel_report:
    source.mkdir(); wheelhouse.mkdir()
  if venv.exists() or bundle.exists():
    parser.error('Runtime destinations already exist')
  env = {key: value for key, value in os.environ.items()
         if key not in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT')
         and not key.startswith('GFOOTBALL_')}
  env['LIBGL_ALWAYS_SOFTWARE'] = '1'
  report = dict(passed=False, platform=platform.platform(), commands=[], source_before=validate.source_fingerprint(),
                git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                validator_sha256=validate.sha(Path(__file__)))

  def run(name, command, cwd=work, environment=None):
    print(name, flush=True)
    log = output / (name + '.log'); start = time.monotonic()
    with log.open('wb') as stream:
      result = subprocess.run(list(map(str, command)), cwd=cwd, env=env if environment is None else environment,
                              stdout=stream, stderr=subprocess.STDOUT, check=False)
    report['commands'].append(dict(name=name, argv=list(map(str, command)), exit_code=result.returncode,
                                   seconds=time.monotonic()-start, log=log.name, sha256=validate.sha(log)))
    if result.returncode:
      raise RuntimeError(name + ' failed; see ' + str(log))
    return log

  try:
    prior = None
    if args.reuse_wheel_report:
      prior_path = args.reuse_wheel_report.resolve()
      prior = json.loads(prior_path.read_text())
      if prior['source_before'] != report['source_before'] or prior['source_after'] != report['source_before']:
        raise RuntimeError('Wheel build evidence has stale production source')
      required_build = {'export-source', 'snapshot-inputs-match', 'build-wheel'}
      audited = set()
      for command in prior['commands']:
        if command['name'] in required_build:
          if command['exit_code'] != 0 or validate.sha(prior_path.parent / command['log']) != command['sha256']:
            raise RuntimeError('Invalid clean wheel build evidence')
          audited.add(command['name'])
      if audited != required_build:
        raise RuntimeError('Missing clean wheel build evidence')
      report['reused_build_evidence'] = dict(report=str(prior_path), sha256=validate.sha(prior_path),
                                           checks=sorted(audited))
    # Exact worktree tar: no Git commit/index mutation and no historical HEAD substitution.
    archive = work / 'source.tar'
    snapshot_inputs=work/'source-inputs.json'
    snapshot_tool=Path(__file__).with_name('snapshot_current.py')
    report['snapshot_tool_sha256']=validate.sha(snapshot_tool)
    report['source_kind']='exact_current_worktree_not_committed_HEAD'
    if not prior:
      run('export-source',[sys.executable,snapshot_tool,'create',ROOT,archive,snapshot_inputs],cwd=ROOT)
    report['snapshot_inputs_sha256']=validate.sha(snapshot_inputs)
    report['source_archive_sha256'] = validate.sha(archive)
    if prior:
      if report['source_archive_sha256'] != prior['source_archive_sha256']:
        raise RuntimeError('Reused source archive changed')
    else:
      with tarfile.open(archive) as stream:
        stream.extractall(source, filter='data')
    run('snapshot-inputs-match',[sys.executable,snapshot_tool,'verify',ROOT,source,snapshot_inputs],cwd=ROOT)
    exported, normalized = {}, []
    for name, expected in report['source_before']['manifest'].items():
      exported[name] = validate.sha(source / name)
      if exported[name] != expected:
        original, archived = ROOT / name, source / name
        text = original.suffix in {'.cpp', '.hpp', '.h', '.py', '.cmake', '.toml'} or original.name == 'CMakeLists.txt'
        if not text or original.read_bytes().replace(b'\r\n', b'\n') != archived.read_bytes().replace(b'\r\n', b'\n'):
          raise RuntimeError('Current snapshot differs from working source: ' + name)
        normalized.append(name)
    report['exported_manifest'] = exported
    report['git_newline_normalized_paths'] = normalized
    if not prior:
      run('build-wheel', [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--wheel-dir', wheelhouse, source])
    wheels = list(wheelhouse.glob('gfootball-*.whl'))
    if len(wheels) != 1:
      raise RuntimeError('Expected one real gfootball wheel')
    wheel = wheels[0]
    if prior and validate.sha(wheel) != prior['wheel']['sha256']:
      raise RuntimeError('Reused wheel bytes changed')
    with zipfile.ZipFile(wheel) as stream:
      names = stream.namelist()
      metadata_name = next(name for name in names if name.endswith('.dist-info/WHEEL'))
      report['wheel'] = dict(name=wheel.name, sha256=validate.sha(wheel),
                            metadata=stream.read(metadata_name).decode(), files=len(names))
      for required in ('gfootball_engine/libfootball_engine.so',
                       'gfootball_engine/fonts/AlegreyaSansSC-ExtraBold.ttf'):
        if required not in names:
          raise RuntimeError('Missing wheel runtime: ' + required)
      if not any(name.startswith('gfootball_engine/_gameplayfootball.') and name.endswith('.so') for name in names):
        raise RuntimeError('Wheel is missing the actual ABI-tagged extension')
      if not any(name.startswith('gfootball_engine/data/') for name in names):
        raise RuntimeError('Wheel is missing simulation resources')
    run('create-clean-venv', [sys.executable, '-m', 'venv', venv])
    installed_python = venv / 'bin/python'
    run('install-wheel', [installed_python, '-m', 'pip', 'install', wheel])
    run('installed-dependencies', [installed_python, '-m', 'pip', 'check'])
    run('installed-probe', [installed_python, '-I', Path(__file__).with_name('installed_probe.py')])
    # Reuse only objects from this freshly compiled source export, never repository artifacts.
    builds = list((source / 'build').glob('temp.*/cmake'))
    if len(builds) != 1:
      raise RuntimeError('Expected the wheel isolated CMake build')
    build = builds[0]
    run('package-native', [sys.executable, Path(__file__).with_name('package_native.py'),
                          '--source', source, '--build-root', build, '--output', bundle])
    run('build-native-contracts', ['cmake', '--build', build, '--parallel', '1', '--target',
                                 'categorical_policy_contract', 'ppo_math_contract',
                                 'engine_native_training_contract', 'engine_training_snapshot_contract',
                                 'engine_training_restore_contract', 'engine_training_soak_contract',
                                 'engine_native_policy_contract', 'engine_ppo_checkpoint_contract', 'engine_spatial_invalidation_contract'])
    # Move the complete runtime bundle; its ELF RUNPATH must resolve relative to the new location.
    relocated = work / ('relocated-native' + suffix)
    bundle.rename(relocated)
    binary = relocated / 'bin/native_ppo_train'
    linkage = run('relocated-native-linkage', ['ldd', binary]).read_text()
    if any(token in linkage for token in ('not found', 'libpython', 'libgame.so', '_gameplayfootball')):
      raise RuntimeError('Native runtime has missing or Python dependencies')
    core_line = next((line for line in linkage.splitlines()
                      if line.strip().startswith('libfootball_engine.so =>')), '')
    core_path = core_line.split('=>', 1)[-1].strip().split(' (', 1)[0]
    if not core_path or Path(core_path).resolve() != (relocated / 'libfootball_engine.so').resolve() or str(source) in linkage:
      raise RuntimeError('Native runtime did not resolve the relocated bundled core')
    dynamic = run('relocated-native-elf', ['readelf', '-d', binary]).read_text()
    if '$ORIGIN' not in dynamic or str(build) in dynamic:
      raise RuntimeError('Native runtime contains build-directory RUNPATH')
    common = ['--seed', '42', '--hidden', '8', '--epochs', '2', '--minibatch', '4',
              '--rollout', '8', '--eval-episodes', '1', '--eval-steps', '16']
    full, prefix, resumed = [work / (name + suffix + '.fppo') for name in ('full', 'prefix', 'resumed')]
    records = []
    for name, options in [('full', ['--updates', '2', '--save', full]),
                          ('prefix', ['--updates', '1', '--save', prefix]),
                          ('resume', ['--updates', '1', '--load', prefix, '--save', resumed]),
                          ('frozen', ['--updates', '0', '--load', full])]:
      records.append(json.loads(run('relocated-native-' + name, [relocated / 'native_ppo_train', *common, *options]).read_text()))
    if full.read_bytes() != resumed.read_bytes() or records[0]['iterations'][1:] != records[2]['iterations']:
      raise RuntimeError('Relocated native full/resumed training differs')
    if records[0]['evaluation'] != records[3]['evaluation'] or records[0]['state_sha256'] != records[3]['state_sha256']:
      raise RuntimeError('Relocated native frozen evaluation differs')
    if not all(record['evaluation']['isolated'] for record in records):
      raise RuntimeError('Relocated native evaluation changed training state')
    tests_env = dict(env, GFOOTBALL_CATEGORICAL_CONTRACT=str(build / 'bin/categorical_policy_contract'),
                     GFOOTBALL_PPO_MATH_CONTRACT=str(build / 'bin/ppo_math_contract'),
                     GFOOTBALL_NATIVE_PPO_TRAIN=str(binary),
                     # Raw executable (unlike launcher) receives resources from the installed wheel.
                     GFOOTBALL_DATA_DIR=json.loads((output / 'installed-probe.log').read_text())['data'],
                     GFOOTBALL_FONT=json.loads((output / 'installed-probe.log').read_text())['font'])
    test_log = run('installed-integration', [installed_python, '-I', '-m', 'unittest',
        'gfootball.test_native_training', 'gfootball.test_gymnasium_native', 'gfootball.test_training_snapshot',
        'gfootball.test_training_resources', 'gfootball.test_training_workers', 'gfootball.test_training_sampler',
        'gfootball.test_categorical_policy', 'gfootball.test_ppo_math', 'gfootball.test_native_ppo_cli', '-v'],
        environment=tests_env).read_text()
    if 'skipped' in test_log or '\nOK\n' not in test_log:
      raise RuntimeError('Installed integration did not execute all required tests')
    manifest = json.loads((relocated / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
      if validate.sha(relocated / name) != expected:
        raise RuntimeError('Relocated package manifest mismatch: ' + name)
    report['native_package'] = dict(path=str(relocated), manifest=manifest,
                                   checkpoint_sha256=validate.sha(full), resumed_sha256=validate.sha(resumed))
    report['installed'] = json.loads((output / 'installed-probe.log').read_text())
    run('snapshot-inputs-after',[sys.executable,snapshot_tool,'verify',ROOT,source,snapshot_inputs],cwd=ROOT)
    report['passed'] = True
  except Exception as error:
    report['error'] = str(error)
  finally:
    report['source_after'] = validate.source_fingerprint()
    if report.get('snapshot_tool_sha256') != validate.sha(Path(__file__).with_name('snapshot_current.py')) or report['validator_sha256'] != validate.sha(Path(__file__)):
      report.update(passed=False,error='Delivery tooling changed during validation')
    if report['source_before'] != report['source_after']:
      report.update(passed=False, error='Working source changed during delivery validation')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(dict(passed=report['passed'], error=report.get('error'), report=str(output / 'report.json')), indent=2))
  return 0 if report['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
