#!/usr/bin/env python3
"""Isolated format contract, with exact logs, fingerprints and sanitizer run."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    build = args.build_root.resolve()
    report = {'passed': False, 'commands': [], 'source_sha256': {}}
    paths = ['engine/src/training/training_snapshot.hpp',
             'engine/src/training/observation_buffer.hpp',
             'engine/src/base/snapshot_envelope.hpp',
             'engine/tests/engine_training_snapshot_contract.cpp',
             'engine/CMakeLists.txt', 'engine/sources.cmake',
             '.project/native-training/validate_snapshot_format.py']

    def fingerprint():
        return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}

    def run(name, command):
        start = time.monotonic()
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / (name + '.log')).write_bytes(result.stdout)
        report['commands'].append({'name': name, 'command': list(map(str, command)),
                                   'exit_code': result.returncode, 'seconds': time.monotonic() - start,
                                   'sha256': hashlib.sha256(result.stdout).hexdigest()})
        print(f'{name}: {result.returncode}', flush=True)
        if result.returncode:
            raise RuntimeError(f'{name} failed; see {output / (name + ".log")}')

    try:
        report['source_sha256'] = fingerprint()
        run('compiler', ['c++', '--version'])
        run('configure', ['cmake', '-S', str(root / 'engine'), '-B', str(build),
                          '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=23',
                          '-DBUILD_PYTHON_BINDINGS=OFF',
                          f'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / "bin"}'])
        run('build', ['cmake', '--build', str(build), '--target',
                      'engine_training_snapshot_contract', '--parallel', '1'])
        executable = build / 'bin/engine_training_snapshot_contract'
        run('format-contract', [str(executable)])
        run('linkage', ['ldd', str(executable)])
        linkage = (output / 'linkage.log').read_text()
        if any(value in linkage for value in ('libpython', 'libfootball', 'not found')):
            raise RuntimeError('Format contract must run independently of engine/Python')
        sanitized = build / 'bin/engine_training_snapshot_sanitized'
        run('sanitizer-build', ['c++', '-std=c++23', '-g', '-O1', '-fno-omit-frame-pointer',
                               '-fsanitize=address,undefined', '-I', str(root / 'engine/src'),
                               str(root / 'engine/tests/engine_training_snapshot_contract.cpp'),
                               '-o', str(sanitized)])
        run('sanitizer-contract', [str(sanitized)])
        report['source_sha256_after'] = fingerprint()
        if report['source_sha256_after'] != report['source_sha256']:
            raise RuntimeError('Source changed during validation')
        report['artifact_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        report['passed'] = True
        report['error'] = None
    except Exception as error:
        report['error'] = str(error)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
