#!/usr/bin/env python3
"""Install a real wheel in a new venv and run native APIs outside the checkout."""
import argparse
from email import message_from_bytes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--venv', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux':
        raise RuntimeError('This actual native package probe targets Linux')
    wheel, venv, output = args.wheel.resolve(), args.venv.resolve(), args.output.resolve()
    if venv.exists():
        raise RuntimeError('Use a new venv path; existing environments are not changed')
    output.mkdir(parents=True, exist_ok=False)
    python = venv / 'bin/python'
    verified = {}
    with zipfile.ZipFile(wheel) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Wheel integrity failure')
        members = set(archive.namelist())
        required = ['gfootball_engine/__init__.py', 'gfootball_engine/libfootball_engine.so',
                    'gfootball_engine/fonts/AlegreyaSansSC-ExtraBold.ttf',
                    'gfootball_engine/fonts/LICENSE', 'gfootball/gymnasium.py',
                    'gfootball/env/legacy_api.py']
        if not all(name in members for name in required):
            raise RuntimeError('Wheel is missing required runtime files')
        extensions = [name for name in members if name.startswith(
            'gfootball_engine/_gameplayfootball') and name.endswith('.so')]
        if len(extensions) != 1 or any('brainball_cpp_engine' in name for name in members):
            raise RuntimeError('Wheel must contain exactly one real binding and no empty extension')
        if any(name.startswith(('engine/', 'gfootball_engine/src/')) for name in members):
            raise RuntimeError('Wheel contains native source/build paths')
        for path in (ROOT / 'engine/data').rglob('*'):
            if not path.is_file():
                continue
            name = 'gfootball_engine/' + path.relative_to(ROOT / 'engine').as_posix()
            if name not in members or hashlib.sha256(archive.read(name)).hexdigest() != sha(path):
                raise RuntimeError('Packaged resource differs from checkout: ' + name)
            verified[path.relative_to(ROOT).as_posix()] = sha(path)
        for name in members:
            if name.startswith('gfootball/') and name.endswith('.py'):
                path = ROOT / name
                if not path.is_file() or hashlib.sha256(archive.read(name)).hexdigest() != sha(path):
                    raise RuntimeError('Packaged Python source differs from checkout: ' + name)
                verified[name] = sha(path)
        metadata_names = [n for n in members if n.endswith('.dist-info/METADATA')]
        if len(metadata_names) != 1:
            raise RuntimeError('Wheel metadata is missing or ambiguous')
        metadata = message_from_bytes(archive.read(metadata_names[0]))
        packaged_binaries = {name: hashlib.sha256(archive.read(name)).hexdigest()
                             for name in extensions + ['gfootball_engine/libfootball_engine.so']}
        engine_init = ROOT / 'engine/__init__.py'
        if hashlib.sha256(archive.read('gfootball_engine/__init__.py')).hexdigest() != sha(engine_init):
            raise RuntimeError('Packaged native module loader differs from the checkout')
        verified['engine/__init__.py'] = sha(engine_init)
    tools = [Path(__file__), ROOT / '.project/checks/gym_registration_probe.py',
             ROOT / 'setup.py', ROOT / 'pyproject.toml', ROOT / 'requirements.txt']
    sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in tools}
    environment = dict(os.environ)
    for name in ('PYTHONPATH', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT', 'DISPLAY'):
        environment.pop(name, None)
    environment['FOOTBALL_GYMNASIUM_EVIDENCE_DIR'] = str(output)
    commands = {}

    def run(name, argv, timeout=180, env=None):
        commands[name] = [str(arg) for arg in argv]
        with (output / (name + '.log')).open('xb') as stream:
            result = subprocess.run(commands[name], cwd=output, env=env or environment,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}; see {output / (name + ".log")}')

    run('venv', [sys.executable, '-m', 'venv', venv])
    run('install', [python, '-m', 'pip', 'install', wheel])
    run('pip-check', [python, '-m', 'pip', 'check'])
    run('pip-freeze', [python, '-m', 'pip', 'freeze'])
    run('registration', [python, ROOT / '.project/checks/gym_registration_probe.py',
                         '--output', output / 'registration'])
    loader = r'''
import importlib, importlib.metadata, json, pickle, sys
from pathlib import Path
order = sys.argv[1]
before = list(sys.path)
if order == 'legacy_first':
    directory = importlib.metadata.distribution('gfootball').locate_file('gfootball_engine')
    sys.path.insert(0, str(directory))
    importlib.import_module('_gameplayfootball')
    sys.path.pop(0)
import gfootball_engine
native = importlib.import_module('gfootball_engine._gameplayfootball')
assert sys.path == before
assert sys.modules['_gameplayfootball'] is native
assert gfootball_engine.GameEnv is native.GameEnv
role = native.e_PlayerRole.e_PlayerRole_GK
assert pickle.loads(pickle.dumps(role)) == role
print(json.dumps(dict(passed=True, assertions=4, order=order, module=native.__name__)))
'''
    for order in ('package_first', 'legacy_first'):
        run('loader-' + order, [python, '-I', '-c', loader, order])
    runner = r'''
import faulthandler, gc, hashlib, importlib.util, json, os, platform, sys, threading, unittest
from pathlib import Path
faulthandler.enable()
faulthandler.dump_traceback_later(170, exit=True)
assert importlib.util.find_spec('gym') is None
import gfootball, gfootball_engine, gfootball_engine._gameplayfootball as native
assert 'site-packages' in Path(gfootball.__file__).parts
assert 'site-packages' in Path(native.__file__).parts
groups = ('gfootball.env.gym_test', 'gfootball.env.wrappers_test', 'gfootball.test_gymnasium_native')
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in groups)
assert suite.countTestCases() == 15
result = unittest.TextTestRunner(verbosity=2).run(suite)
gc.collect()
from gfootball.env import football_env_core
football_env_core.ENGINE_POOL.close()
pool = football_env_core.ENGINE_POOL.stats()
remaining = [t.name for t in threading.enumerate() if t.name.startswith('football-')]
passed = result.wasSuccessful() and not result.skipped and not remaining and pool['live'] == 0
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
report = dict(passed=passed, tests=result.testsRun, skipped=len(result.skipped),
              failures=[str(t) for t,_ in result.failures], errors=[str(t) for t,_ in result.errors],
              engine_pool_final=pool, remaining_owned_threads=remaining,
              python=sys.version, executable=sys.executable, platform=platform.platform(),
              package=gfootball.__file__, binding=native.__file__, binding_sha256=sha(native.__file__),
              engine_sha256=sha(Path(gfootball_engine.__file__).parent/'libfootball_engine.so'),
              actual_native_GameEnv=True, actual_EGL=True, checkout_on_import_path=False)
Path('native-tests.json').write_text(json.dumps(report,indent=2)+'\n')
faulthandler.cancel_dump_traceback_later()
raise SystemExit(0 if passed else 1)
'''
    run('native-tests', [python, '-I', '-c', runner], timeout=190)
    native_report = json.loads((output / 'native-tests.json').read_text())
    if native_report['binding_sha256'] != packaged_binaries[extensions[0]] or (
            native_report['engine_sha256'] != packaged_binaries['gfootball_engine/libfootball_engine.so']):
        raise RuntimeError('Installed native binaries differ from the wheel')
    human = r'''
import json, os
import gymnasium as gym
env = gym.make('gfootball.gymnasium:GFootball-11_vs_11_easy_stochastic-SMM-v0',
               render_mode='human', other_config_options=dict(
                   render_resolution_x=160, render_resolution_y=90,
                   physics_steps_per_frame=5, display_game_stats=False))
try:
    env.reset(seed=7)
    assert env.render() is None
    env.step(0)
    assert env.render() is None
    assert env.metadata['render_fps'] == 20
finally:
    env.close()
from gfootball.env import football_env_core
football_env_core.ENGINE_POOL.close()
assert football_env_core.ENGINE_POOL.stats()['live'] == 0
print(json.dumps(dict(passed=True, assertions=4, actual_SDL=bool(os.environ.get('DISPLAY')))))
'''
    human_environment = dict(environment)
    if os.environ.get('DISPLAY'):
        human_environment['DISPLAY'] = os.environ['DISPLAY']
    run('human-render', [python, '-I', '-c', human], env=human_environment)
    human_report = json.loads((output / 'human-render.log').read_text().splitlines()[-1])
    image = output / 'terminal-rgb.png'
    if not image.is_file() or image.stat().st_size < 100:
        raise RuntimeError('Native terminal image was not archived')
    for name, digest in dict(verified, **sources).items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('Sources or resources changed during package validation: ' + name)
    text = (output / 'native-tests.log').read_text()
    markers = [m for m in ('ResourceWarning:', 'Exception ignored in:', 'Exception in thread',
                           'Task was destroyed but it is pending') if m in text]
    if markers:
        raise RuntimeError('Native package tests emitted lifecycle failures: ' + str(markers))
    report = dict(passed=True, wheel=str(wheel), wheel_sha256=sha(wheel),
                  venv=str(venv), commands=commands, sources=sources,
                  packaged_sources_and_resources=verified, packaged_binaries=packaged_binaries,
                  package_version=metadata['Version'], requires=metadata.get_all('Requires-Dist'),
                  python_requires=metadata['Requires-Python'], native=native_report,
                  registration=json.loads((output / 'registration/report.json').read_text()),
                  loader_order_assertions=8, human_render=human_report,
                  images={image.name: sha(image)},
                  logs={p.name: sha(p) for p in output.glob('*.log')},
                  old_Gym_installed=False, installed_from_wheel=True,
                  linux_local_wheel_accepted=True, cross_platform_matrix_accepted=False,
                  formal_product_acceptance=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, tests=native_report['tests'],
                         registration_assertions=report['registration']['assertions'],
                         wheel_sha256=report['wheel_sha256'], report=str(output/'report.json'))))


if __name__ == '__main__':
    main()
