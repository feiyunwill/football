#!/usr/bin/env python3
"""Build and exercise the Linux product wheel from an isolated install."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / '.project/optimization/benchmarks'
REQUIREMENTS = ROOT / '.project/checks/requirements.txt'
SOURCES = ('setup.py', 'pyproject.toml', 'requirements.txt',
           '.project/checks/requirements.txt',
           '.project/checks/gymnasium_package_probe.py',
           '.project/checks/gym_registration_probe.py',
           '.project/checks/product_package.py',
           'engine/CMakeLists.txt', 'engine/sources.cmake',
           'engine/src/**/*.cpp', 'engine/src/**/*.hpp', 'engine/src/**/*.h',
           'engine/__init__.py', 'engine/data/**/*', 'engine/fonts/**/*',
           'gfootball/**/*.py')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = {path for pattern in SOURCES for path in ROOT.glob(pattern)
             if path.is_file()}
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-python', type=Path,
                        help='Acceptance Python with pip and declared requirements')
    args = parser.parse_args()
    output = BENCHMARKS / f'product-package-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {'passed': False, 'assertions': 0, 'skipped': 0,
                    'target_platform': 'Linux x86_64', 'commands': [],
                    'artifact': str(output / 'report.json')}

    def require(condition: bool, message: str) -> None:
        report['assertions'] += 1
        if not condition:
            raise RuntimeError(message)

    def run(label: str, argv: list[str | Path], *, cwd: Path = ROOT,
            env: dict | None = None, input_text: str | None = None,
            expected_returncode: int = 0, timeout: int = 1800) -> str:
        command = list(map(str, argv))
        try:
            result = subprocess.run(command, cwd=cwd, env=env, input=input_text,
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f'{label} timed out after {timeout}s') from error
        log = output / f'{label}.log'
        log.write_text(result.stdout + result.stderr)
        report['commands'].append({'label': label, 'argv': command,
                                   'returncode': result.returncode,
                                   'log_sha256': sha(log)})
        require(result.returncode == expected_returncode,
                f'{label} exited {result.returncode}; see {log}')
        return result.stdout

    try:
        require(platform.system() == 'Linux' and platform.machine() == 'x86_64' and
                sys.flags.optimize == 0, 'Product wheel requires Linux x86_64 with assertions')
        original = source_manifest()
        report['source_manifest_sha256'] = hashlib.sha256(
            json.dumps(original, sort_keys=True).encode()).hexdigest()
        identity = hashlib.sha256(REQUIREMENTS.read_bytes() +
                                  sys.implementation.cache_tag.encode()).hexdigest()[:16]
        environment = Path(tempfile.gettempdir()) / f'football-framework-python-{identity}'
        python = (args.build_python.absolute() if args.build_python else
                  environment / 'bin/python')
        if not python.is_file():
            require(args.build_python is None, 'Requested build Python is missing')
            run('create-build-venv', [sys.executable, '-m', 'venv', environment],
                timeout=180)
        require(python.is_file(), 'Wheel build Python is missing')
        if args.build_python is None:
            run('install-build-requirements', [python, '-m', 'pip', 'install',
                                               '--disable-pip-version-check',
                                               '-r', REQUIREMENTS], timeout=900)
        run('check-build-requirements', [python, '-m', 'pip', 'check'])

        wheel_dir = output / 'wheel'
        wheel_dir.mkdir()
        run('build-wheel', [python, '-m', 'pip', 'wheel', '--no-deps',
                            '--wheel-dir', wheel_dir, ROOT], timeout=2700)
        wheels = list(wheel_dir.glob('gfootball-*.whl'))
        require(len(wheels) == 1, 'Wheel build produced no unique gfootball artifact')
        wheel = wheels[0]
        report['wheel'] = {'path': str(wheel), 'sha256': sha(wheel),
                           'bytes': wheel.stat().st_size}

        probe_output = output / 'installed-probe'
        installed_venv = output / 'clean-venv'
        run('clean-install-probe', [python, ROOT / '.project/checks/gymnasium_package_probe.py',
                                    '--wheel', wheel, '--venv', installed_venv,
                                    '--output', probe_output], timeout=2700)
        probe = json.loads((probe_output / 'report.json').read_text())
        require(probe.get('passed') is True and probe.get('installed_from_wheel') is True and
                probe.get('linux_local_wheel_accepted') is True and
                probe.get('wheel_sha256') == sha(wheel),
                'Fresh wheel installation did not pass the native package probe')
        clean_python = installed_venv / 'bin/python'
        require(clean_python.is_file(), 'Installed acceptance interpreter is missing')
        runtime = output / 'clean-runtime'
        runtime.mkdir()
        clean_env = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'LD_LIBRARY_PATH',
                    'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT'):
            clean_env.pop(key, None)

        metadata_code = '''
import hashlib, importlib.metadata, json
from pathlib import Path
import gfootball, gfootball_engine
from gfootball.frame_sync import protocol, match_bootstrap
package = Path(gfootball_engine.__file__).parent
binding = next(package.glob('_gameplayfootball*.so'))
print(json.dumps({'version': importlib.metadata.version('gfootball'),
                  'python_package': gfootball.__file__,
                  'native_package': gfootball_engine.__file__,
                  'binding_sha256': hashlib.sha256(binding.read_bytes()).hexdigest(),
                  'engine_sha256': hashlib.sha256((package/'libfootball_engine.so').read_bytes()).hexdigest(),
                  'protocol_version': protocol.PROTOCOL_VERSION,
                  'protocol_min_version': protocol.PROTOCOL_MIN_VERSION,
                  'match_version': match_bootstrap.MATCH_VERSION,
                  'data_exists': (package/'data/media/shaders/pbr.frag').is_file(),
                  'font_exists': (package/'fonts/AlegreyaSansSC-ExtraBold.ttf').is_file()}))
'''
        installed = json.loads(run('installed-identity',
                                   [clean_python, '-I', '-c', metadata_code],
                                   cwd=runtime, env=clean_env).strip().splitlines()[-1])
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        require(installed['version'] == project['version'] == probe['package_version'],
                'Installed package version differs from the build metadata')
        require('site-packages' in Path(installed['python_package']).parts and
                'site-packages' in Path(installed['native_package']).parts and
                Path(installed['python_package']).is_relative_to(installed_venv) and
                Path(installed['native_package']).is_relative_to(installed_venv),
                'Installed runtime imported the checkout instead of the wheel')
        expected_binary_hashes = probe['packaged_binaries']
        require(installed['engine_sha256'] ==
                expected_binary_hashes['gfootball_engine/libfootball_engine.so'] and
                installed['binding_sha256'] in expected_binary_hashes.values(),
                'Installed binaries differ from the wheel')
        require(installed['data_exists'] and installed['font_exists'],
                'Installed runtime cannot locate packaged resources')
        header = (ROOT / 'engine/src/frame_sync/protocol.hpp').read_text()
        native_protocol = re.search(r'PROTOCOL_VERSION\s*=\s*(\d+)', header)
        native_minimum = re.search(r'PROTOCOL_MIN_VERSION\s*=\s*(\d+)', header)
        require(native_protocol is not None and native_minimum is not None and
                installed['protocol_version'] == int(native_protocol.group(1)) and
                installed['protocol_min_version'] == int(native_minimum.group(1)) and
                installed['match_version'] > 0,
                'Installed protocol metadata differs from native source')

        settings = runtime / 'preferences.json'
        missing = runtime / 'missing.save'
        error = run('missing-checkpoint-diagnostic',
                    [clean_python, '-I', '-m', 'gfootball.frame_sync.main_menu',
                     '--mode', 'resume', '--settings-file', settings],
                    cwd=runtime, env=clean_env,
                    input_text=f'{missing}\n-\n3\n', expected_returncode=1,
                    timeout=120)
        require(error.count('Could not complete this action: Match checkpoint does not exist')
                == 1, 'Installed CLI did not diagnose a missing checkpoint')
        local = run('installed-local-match',
                    [clean_python, '-I', '-m', 'gfootball.frame_sync.main_menu',
                     '--mode', 'local', '--settings-file', settings],
                    cwd=runtime, env=clean_env,
                    input_text='\n1\n0\n42\n-\n-\n3\n', timeout=120)
        require(local.count('Score (') == 3 and
                'Could not complete this action:' not in local,
                'Installed CLI did not complete a native match from clean cwd')
        compiler = run('compiler', ['c++', '--version']).splitlines()[0]
        commit = run('source-commit', ['git', 'rev-parse', 'HEAD']).strip()
        require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None,
                'Build source revision is missing')
        require(source_manifest() == original,
                'Package sources changed during acceptance')
        report.update({'version': installed['version'],
                       'protocol': {'frame_sync': installed['protocol_version'],
                                    'minimum': installed['protocol_min_version'],
                                    'match': installed['match_version']},
                       'build': {'source_commit': commit, 'compiler': compiler,
                                 'python': sys.version, 'wheel_sha256': sha(wheel),
                                 'source_manifest_sha256': report['source_manifest_sha256']},
                       'installed': installed,
                       'probe_report_sha256': sha(probe_output / 'report.json'),
                       'fresh_install': True,
                       'clean_directory_match': True,
                       'error_diagnostic': True,
                       'product_acceptance': True})
        require(report['assertions'] >= 20, 'Insufficient package assertions')
        report['passed'] = True
    except BaseException as error:
        report['error'] = str(error)
        report['product_acceptance'] = False
    finally:
        artifact = output / 'report.json'
        artifact.write_text(json.dumps(report, indent=2) + '\n')
        report['artifact_sha256'] = sha(artifact)
        print(json.dumps({key: report.get(key) for key in (
            'passed', 'assertions', 'skipped', 'error', 'product_acceptance',
            'artifact', 'version', 'protocol', 'build')}
            | {'artifact_sha256': report['artifact_sha256']}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
