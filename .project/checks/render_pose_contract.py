#!/usr/bin/env python3
"""Build and archive actual native card/skin attachment acceptance on Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def sources():
    paths = {ROOT / name for name in (
        '.project/checks/render_pose_contract.py', 'engine/CMakeLists.txt',
        'engine/sources.cmake', 'engine/tests/engine_render_pose_contract.cpp')}
    paths.update(p for p in (ROOT / 'engine/src').rglob('*')
                 if p.is_file() and p.suffix in ('.cpp', '.hpp', '.h'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}


def resources():
    return {p.relative_to(ROOT).as_posix(): sha(p)
            for p in sorted((ROOT / 'engine/data').rglob('*')) if p.is_file()}


def run(argv, log, environment=None, timeout=1800):
    print('Running: ' + ' '.join(map(str, argv)), flush=True)
    with log.open('xb') as stream:
        result = subprocess.run(list(map(str, argv)), cwd=ROOT, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'Native command exited {result.returncode}; see {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux':
        raise RuntimeError('Actual native render acceptance requires the Linux target')
    build, output = args.build.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = sources()
    resource_fingerprints = resources()
    run(['cmake', '-S', ROOT / 'engine', '-B', build, '-DCMAKE_BUILD_TYPE=Release',
         '-DBUILD_PYTHON_BINDINGS=OFF', '-DCMAKE_CXX_STANDARD=23',
         f'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / "bin"}'], output / 'configure.log')
    run(['cmake', '--build', build, '-j', '1', '--target', 'engine_render_pose_contract'],
        output / 'build.log')
    environment = dict(os.environ)
    environment.pop('DISPLAY', None)  # Actual EGL/OpenGL; no replacement renderer.
    binary = build / 'bin/engine_render_pose_contract'
    log = output / 'contract.log'
    run([binary, output / 'images'], log, environment=environment, timeout=240)
    with log.open('rb') as stream:
        stream.seek(max(0, log.stat().st_size - 65536))
        result = json.loads(stream.read().decode('utf-8').strip().splitlines()[-1])
    if not (result.get('passed') is True and result.get('actual_GameEnv') is True
            and result.get('assertions', 0) >= 200 and result.get('card_cases') == 8
            and result.get('images') == 6 and result.get('skipped') == 0):
        raise RuntimeError('Native card contract coverage is incomplete')
    artifacts = {}
    header = b'P6\n320 180\n255\n'
    expected = {f'{side}_red_{alpha}.ppm' for side in ('normal', 'reverse') for alpha in range(3)}
    files = list((output / 'images').iterdir())
    if {p.name for p in files} != expected:
        raise RuntimeError('Expected all six actual native intermediate images')
    for path in sorted(files):
        if not path.is_file() or path.stat().st_size != len(header) + 320 * 180 * 3:
            raise RuntimeError(f'Invalid image size: {path}')
        with path.open('rb') as stream:
            if stream.read(len(header)) != header:
                raise RuntimeError(f'Invalid native image header: {path}')
        artifacts[path.name] = dict(bytes=path.stat().st_size, sha256=sha(path))
    for side in ('normal', 'reverse'):
        if len({artifacts[f'{side}_red_{alpha}.ppm']['sha256'] for alpha in range(3)}) != 3:
            raise RuntimeError(f'Actual {side} intermediate renders did not change pixels')
    if sources() != before:
        raise RuntimeError('Native source changed during build or execution')
    if resources() != resource_fingerprints:
        raise RuntimeError('Native resource data changed during execution')
    report = dict(scope='Actual native display attachment geometry and intermediate images',
                  # 2026-09-10: archive actual animation/mesh/texture resource fingerprints too.
                  # passed=True, contract=result, sources=before, images=artifacts,
                  passed=True, contract=result, sources=before,
                  resources=resource_fingerprints, images=artifacts,
                  logs={p.name: sha(p) for p in (output / 'configure.log', output / 'build.log', log)},
                  binary_sha256=sha(binary), engine_sha256=sha(build / 'libfootball_engine.so'),
                  platform=platform.platform(), native_code_compiled=True,
                  native_GameEnv_executed=True, formal_product_acceptance=False,
                  pause_resume_covered=False, device_input_covered=False,
                  long_run_performance_covered=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # 2026-09-10: keep the console compact; full resource fingerprints remain archived.
    # print(json.dumps({k: v for k, v in report.items() if k != 'sources'}, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('sources', 'resources')}, indent=2))


if __name__ == '__main__':
    main()
