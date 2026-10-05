#!/usr/bin/env python3
"""Exercise the real menu, native match, recovery, replay, and UDP host journey."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / '.project/checks/requirements.txt'
BENCHMARKS = ROOT / '.project/optimization/benchmarks'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, help='Preinstalled acceptance Python')
    parser.add_argument('--binding-build', type=Path, help='Reusable native CMake build')
    args = parser.parse_args()
    output = BENCHMARKS / f'product-journey-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {'passed': False, 'assertions': 0, 'skipped': 0,
                    'commands': [], 'artifact': str(output / 'report.json')}

    def require(condition: bool, message: str) -> None:
        report['assertions'] += 1
        if not condition:
            raise RuntimeError(message)

    def run(label: str, argv: list[str | Path], *, env: dict | None = None,
            input_text: str | None = None, timeout: int = 300) -> str:
        command = list(map(str, argv))
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, input=input_text,
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f'{label} timed out after {timeout}s') from error
        log = output / f'{label}.log'
        log.write_text(result.stdout + result.stderr)
        report['commands'].append({'label': label, 'argv': command,
                                   'returncode': result.returncode,
                                   'log_sha256': sha(log)})
        require(result.returncode == 0, f'{label} failed; see {log}')
        return result.stdout

    try:
        require(platform.system() == 'Linux' and sys.flags.optimize == 0,
                'Native Linux with Python assertions is required')
        identity = hashlib.sha256(REQUIREMENTS.read_bytes() +
                                  sys.implementation.cache_tag.encode()).hexdigest()[:16]
        environment = Path(tempfile.gettempdir()) / f'football-framework-python-{identity}'
        # Keep the venv's bin/python symlink: resolve() would select the base
        # interpreter and silently drop all installed runtime dependencies.
        python = (args.python.absolute() if args.python else environment / 'bin/python')
        if not python.is_file():
            require(args.python is None, 'Requested acceptance Python is missing')
            run('create-venv', [sys.executable, '-m', 'venv', environment], timeout=180)
        require(python.is_file(), 'Acceptance Python is missing')
        if args.python is None:
            run('install-requirements', [python, '-m', 'pip', 'install',
                                         '--disable-pip-version-check', '-r', REQUIREMENTS],
                timeout=900)
        run('check-requirements', [python, '-m', 'pip', 'check'])
        pybind11_dir = run('pybind11-dir', [python, '-m', 'pybind11', '--cmakedir']).strip()
        require(Path(pybind11_dir).is_dir(), 'pybind11 CMake directory is missing')

        build = (args.binding_build or output / 'build').resolve()
        package = build / 'package/gfootball_engine'
        package.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'engine/__init__.py', package / '__init__.py')
        for name in ('data', 'fonts'):
            link = package / name
            target = ROOT / 'engine' / name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(target, target_is_directory=True)
            require(link.resolve() == target.resolve(),
                    f'Native package {name} points to unexpected resources')
        run('configure-binding', ['cmake', '-S', ROOT / 'engine', '-B', build,
                                  '-DCMAKE_BUILD_TYPE=Release',
                                  '-DBUILD_PYTHON_BINDINGS=ON',
                                  f'-DPython_EXECUTABLE={python}',
                                  f'-Dpybind11_DIR={pybind11_dir}',
                                  f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={package}'], timeout=180)
        run('build-binding', ['cmake', '--build', build, '-j', '2', '--target', 'game'],
            timeout=2100)
        core = package / 'libfootball_engine.so'
        game = package / 'libgame.so'
        require(core.is_file() and game.is_file(), 'Current native binding is missing')
        binding = package / '_gameplayfootball.so'
        if binding.is_symlink():
            binding.unlink()
        shutil.copy2(game, binding)
        report['binaries'] = {'engine_sha256': sha(core),
                              'binding_sha256': sha(binding)}
        native_env = dict(os.environ)
        native_env.update({
            'PYTHONPATH': os.pathsep.join((str(build / 'package'), str(ROOT),
                                           native_env.get('PYTHONPATH', ''))),
            'LD_LIBRARY_PATH': os.pathsep.join((str(package),
                                                native_env.get('LD_LIBRARY_PATH', ''))),
            'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
        })
        run('import-binding', [python, '-c',
                              'import gfootball_engine; from gfootball_engine import _gameplayfootball'],
            env=native_env)

        runtime = output / 'runtime'
        runtime.mkdir()
        settings = runtime / 'preferences.json'
        missing = runtime / 'missing.save'
        replay = runtime / 'match.replay'
        save = runtime / 'match.save'
        require(not any(path.exists() for path in (settings, missing, replay, save)),
                'Journey did not start from clean user data')
        answers = [
            '6', str(missing), '-', '3',           # Missing checkpoint, return to menu.
            '1', '', '1', '0', '42', str(replay), str(save), '3',
            '6', str(save), '-', '2',             # Resume the saved native match.
            '7', str(replay),                     # Verify the recorded match.
            '2', '', '1', '0', '43', '0', '-', '-', '3',
            '5',                                  # Leave the menu after a UDP host match.
        ]
        stdout = run('interactive-journey',
                     [python, '-m', 'gfootball.frame_sync.main_menu',
                      '--transport', 'udp', '--settings-file', settings],
                     env=native_env, input_text='\n'.join(answers) + '\n', timeout=180)
        failure = 'Could not complete this action: Match checkpoint does not exist'
        require(stdout.count(failure) == 1, 'Missing checkpoint recovery was not isolated')
        require(stdout.count('[1] Local play') >= 6, 'Journey did not return to the menu')
        require(stdout.count('Score (') >= 5, 'Native match did not advance after recovery')
        require(all(f'Replayed frame {frame}' in stdout for frame in range(3)) and
                "'verified': True" in stdout,
                'Recorded native match did not replay with a verified digest')
        host = re.search(r'Hosting UDP on port (\d+) - waiting for 1 players', stdout)
        require(host is not None and int(host.group(1)) > 0,
                'Production UDP host did not enter a real lobby')
        require('Match ended after 3 frames.' in stdout,
                'Production UDP host did not end its match')
        require(stdout.rstrip().endswith('Select:'),
                'Process did not exit from the final menu selection')
        require(replay.is_file() and replay.stat().st_size > 0 and
                save.is_file() and save.stat().st_size > 0,
                'Match replay or checkpoint was not written')
        require(sha(core) == report['binaries']['engine_sha256'] and
                sha(binding) == report['binaries']['binding_sha256'],
                'Native binary changed while executing the journey')
        report['journey'] = {'transport': 'udp', 'recovery': 'missing checkpoint',
                             'local_frames': 3, 'resumed_frames': 2,
                             'replayed_frames': 3, 'host_frames': 3,
                             'host_port': int(host.group(1)),
                             'replay_sha256': sha(replay), 'checkpoint_sha256': sha(save)}
        require(report['assertions'] >= 20, 'Insufficient product journey assertions')
        report['passed'] = True
    except BaseException as error:
        report['error'] = str(error)
    finally:
        artifact = output / 'report.json'
        artifact.write_text(json.dumps(report, indent=2) + '\n')
        report['artifact_sha256'] = sha(artifact)
        print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
