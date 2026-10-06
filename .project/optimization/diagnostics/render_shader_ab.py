#!/usr/bin/env python3
"""Fail-closed image preflight and paired real-window A/B for one GLSL shader."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tarfile
import time

from render_backend_ab import competing_benchmarks, require, sha

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'engine/data'
SHADERS = DATA / 'media/shaders'
GOLDEN = ROOT / '.project/checks/golden/render_images_llvmpipe_bilinear_20261004.json'
OUTPUTS = ROOT / '.project/optimization/diagnostics'
CASES = ('legacy', 'baseline', 'bloom', 'fxaa', 'auto', 'auto_combined')


def candidate_data(output: Path, name: str, candidate: bytes) -> Path:
    """Overlay one shader while every other resource resolves to current source."""
    data = output / 'candidate-data'
    data.mkdir()
    for top in DATA.iterdir():
        target = data / top.name
        if top.name != 'media':
            target.symlink_to(top)
            continue
        target.mkdir()
        for item in top.iterdir():
            media_target = target / item.name
            if item.name != 'shaders':
                media_target.symlink_to(item)
                continue
            media_target.mkdir()
            for shader in item.iterdir():
                shader_target = media_target / shader.name
                if shader.name == name:
                    shader_target.write_bytes(candidate)
                else:
                    shader_target.symlink_to(shader)
    return data


def capture_environment(data: Path, build: Path, case: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in ('LD_PRELOAD', 'DISPLAY', 'SDL_VIDEODRIVER',
                'GFOOTBALL_USE_PBR', 'GFOOTBALL_PBR_BLOOM',
                'GFOOTBALL_PBR_FXAA', 'GFOOTBALL_PBR_EXPOSURE',
                'GFOOTBALL_PBR_AUTO_EXPOSURE'):
        env.pop(key, None)
    env.update({'GFOOTBALL_DATA_DIR': str(data), 'LIBGL_ALWAYS_SOFTWARE': '1',
                'LD_LIBRARY_PATH': str(build)})
    if case != 'legacy':
        env['GFOOTBALL_USE_PBR'] = '1'
    if case in ('bloom', 'auto_combined'):
        env['GFOOTBALL_PBR_BLOOM'] = '1'
    if case in ('fxaa', 'auto_combined'):
        env['GFOOTBALL_PBR_FXAA'] = '1'
    if case in ('auto', 'auto_combined'):
        env['GFOOTBALL_PBR_AUTO_EXPOSURE'] = '1'
    return env


def benchmark_environment(data: Path, build: Path, driver: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in ('LD_PRELOAD', 'LIBGL_ALWAYS_SOFTWARE', 'GFOOTBALL_RENDER_SKIP_SWAP',
                'GFOOTBALL_RENDER_PHASE_PROFILE',
                'GFOOTBALL_RENDER_GPU_PHASE_PROFILE', 'GFOOTBALL_PBR_EXPOSURE'):
        env.pop(key, None)
    env.update({'SDL_VIDEODRIVER': 'wayland', 'GFOOTBALL_DATA_DIR': str(data),
                'GFOOTBALL_USE_PBR': '1', 'GFOOTBALL_PBR_BLOOM': '1',
                'GFOOTBALL_PBR_FXAA': '1', 'GFOOTBALL_PBR_AUTO_EXPOSURE': '1',
                'LD_LIBRARY_PATH': str(build) + ':' + str(driver),
                'LIBGL_DRIVERS_PATH': str(driver / 'dri'),
                'GALLIUM_DRIVER': 'd3d12',
                'MESA_LOADER_DRIVER_OVERRIDE': 'd3d12'})
    return env


def data_manifest() -> dict[str, str]:
    return {str(path.relative_to(DATA)): sha(path)
            for path in sorted(DATA.rglob('*')) if path.is_file()}


def archive(output: Path) -> str:
    entries = {str(path.relative_to(output)): path.read_bytes()
               for path in output.rglob('*')
               if path.is_file() and not path.is_symlink() and
               path.name != 'evidence.tar.gz'}
    manifest = {'schema': 'football-render-shader-ab-evidence-v1',
                'members': {name: hashlib.sha256(data).hexdigest()
                            for name, data in sorted(entries.items())}}
    entries['manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as tar:
            for name, data in sorted(entries.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
    artifact = output / 'evidence.tar.gz'
    artifact.write_bytes(stream.getvalue())
    return sha(artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shader', required=True,
                        help='Filename in engine/data/media/shaders')
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--capture-build', required=True, type=Path)
    parser.add_argument('--benchmark-build', type=Path)
    parser.add_argument('--gpu-driver-root', type=Path)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--image-only', action='store_true')
    args = parser.parse_args()
    require(Path(args.shader).name == args.shader and
            (SHADERS / args.shader).is_file(), 'Shader must be a source filename')
    require(1 <= args.repeats <= 4, 'Diagnostic repetitions must be 1-4')
    require(args.image_only or (args.benchmark_build and args.gpu_driver_root),
            'GPU benchmark build and driver are required for real-window A/B')
    require(args.image_only or not competing_benchmarks(),
            'Shader A/B requires an isolated benchmark window')
    capture_build = args.capture_build.resolve()
    capture_binary = capture_build / 'bin/engine_frame_capture_contract'
    capture_core = capture_build / 'libfootball_engine.so'
    require(capture_binary.is_file() and capture_core.is_file(),
            'Image fixture or engine build is missing')
    source_shader = SHADERS / args.shader
    candidate = args.candidate.read_bytes()
    golden = json.loads(GOLDEN.read_text())
    require(golden['size'] == [321, 181] and golden['frames'] == [0, 40, 80, 120, 160] and
            set(golden['cases']) == set(CASES), 'Unexpected image oracle scope')
    output = OUTPUTS / f'render-shader-ab-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    overlay = candidate_data(output, args.shader, candidate)
    source_files = data_manifest()
    manifest_file = output / 'source-manifest.json'
    manifest_file.write_text(json.dumps(source_files, sort_keys=True, indent=2) + '\n')
    source_commit = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = {'schema': 'football-render-shader-ab-v1', 'product_acceptance': False,
              'runner_sha256': sha(Path(__file__)),
              'shader': args.shader, 'source_shader_sha256': sha(source_shader),
              'candidate_shader_sha256': sha(overlay / 'media/shaders' / args.shader),
              'source_commit': source_commit,
              'source_manifest_sha256': sha(manifest_file),
              'source_file_count': len(source_files),
              'capture_build': str(capture_build),
              'benchmark_build': (str(args.benchmark_build.resolve())
                                  if args.benchmark_build else None),
              'gpu_driver_root': (str(args.gpu_driver_root.resolve())
                                  if args.gpu_driver_root else None),
              'capture_binary_sha256': sha(capture_binary),
              'capture_engine_sha256': sha(capture_core),
              'golden_sha256': sha(GOLDEN), 'image_only': args.image_only,
              'quality': 'pbr+bloom+fxaa+auto_exposure', 'resolution': [1920, 1080],
              'frame_budget_p95_ms': 16.67, 'seeds': [42, 43],
              'repeats': args.repeats, 'captures': [], 'runs': [], 'failures': []}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    image_equal = True
    for case in CASES:
        for mode, data in (('baseline', DATA), ('candidate', overlay)):
            target = output / 'captures' / mode / case
            target.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run([str(capture_binary), str(target)], cwd=ROOT,
                                       env=capture_environment(data, capture_build, case),
                                       capture_output=True, timeout=300)
            log = output / f'capture-{mode}-{case}.log'
            log.write_bytes(completed.stdout + completed.stderr)
            require(completed.returncode == 0, f'{case}/{mode} capture failed: {log}')
            identity = json.loads((target / 'identity.json').read_text())
            require(identity == golden['identity'], f'{case}/{mode} renderer differs')
            result = {'case': case, 'mode': mode, 'log_sha256': sha(log), 'frames': {}}
            for frame in golden['frames']:
                name = f'frame-{frame}'
                rgb = (target / f'{name}.rgb').read_bytes()
                state = (target / f'{name}.state').read_bytes()
                require(len(rgb) == 321 * 181 * 3,
                        f'{case}/{mode}/{name} has wrong dimensions')
                value = {'rgb_sha256': hashlib.sha256(rgb).hexdigest(),
                         'state_sha256': hashlib.sha256(state).hexdigest()}
                require(value['state_sha256'] == golden['states'][str(frame)],
                        f'{case}/{mode}/{name} simulation changed')
                if mode == 'baseline':
                    require(value['rgb_sha256'] == golden['cases'][case][str(frame)],
                            f'{case}/{name} current image differs from oracle')
                else:
                    previous = (output / 'captures/baseline' / case /
                                f'{name}.rgb').read_bytes()
                    value['changed_pixels'] = sum(
                        previous[i:i + 3] != rgb[i:i + 3]
                        for i in range(0, len(rgb), 3))
                    value['max_channel_delta'] = max(
                        abs(a - b) for a, b in zip(previous, rgb))
                    image_equal &= value['changed_pixels'] == 0
                result['frames'][str(frame)] = value
            report['captures'].append(result)
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print('capture', case, mode, 'ok', flush=True)
            if not image_equal:
                break
        if not image_equal:
            break
    report['image_equal'] = image_equal
    if not image_equal:
        report['failures'].append('Candidate image differs; GPU benchmark skipped')

    if image_equal and not args.image_only:
        benchmark_build = args.benchmark_build.resolve()
        driver = args.gpu_driver_root.resolve() / 'lib'
        binary = benchmark_build / 'bin/engine_render_budget_benchmark'
        core = benchmark_build / 'libfootball_engine.so'
        gallium = driver / 'libgallium-26.2.2.so'
        require(all(path.is_file() for path in (binary, core, gallium)),
                'Benchmark, engine, or private D3D12 driver is missing')
        report.update({'benchmark_binary_sha256': sha(binary),
                       'benchmark_engine_sha256': sha(core),
                       'gallium_sha256': sha(gallium)})
        for repetition in range(args.repeats):
            for seed in (42, 43):
                order = ('baseline', 'candidate') if (seed + repetition) % 2 == 0 \
                    else ('candidate', 'baseline')
                for mode in order:
                    label = f'seed{seed}-repeat{repetition}-{mode}'
                    log = output / f'{label}.log'
                    data = DATA if mode == 'baseline' else overlay
                    completed = subprocess.run([str(binary), str(seed)], cwd=ROOT,
                                               env=benchmark_environment(data, benchmark_build,
                                                                         driver),
                                               capture_output=True, timeout=240)
                    log.write_bytes(completed.stdout + completed.stderr)
                    require(completed.returncode == 0, f'{label} failed: {log}')
                    lines = [line for line in completed.stdout.splitlines()
                             if line.startswith(b'{')]
                    require(len(lines) == 1, f'{label} JSON missing')
                    row = json.loads(lines[0])
                    samples = row['samples_ms']
                    submit = row['submit_samples_ms']
                    finish = row['finish_samples_ms']
                    require(row['seed'] == seed and row['quality'] == report['quality'] and
                            (row['width'], row['height']) == (1920, 1080) and
                            row['measured_frames'] == 120 and
                            len(samples) == len(submit) == len(finish) == 120 and
                            row['swap_enabled'] is True and row['swap_interval'] == 0 and
                            'D3D12' in row['renderer'] and
                            Path(row['gallium_path']).resolve() == gallium and
                            abs(sorted(samples)[math.ceil(.95 * 120) - 1] -
                                row['p95_ms']) < .001,
                            f'{label} measured another GPU workload')
                    require(all(math.isfinite(value) and value > 0 for values in
                                (samples, submit, finish) for value in values) and
                            all(abs(total - sent - done) < .01
                                for total, sent, done in zip(samples, submit, finish)),
                            f'{label} raw frame phases do not reconcile')
                    result = {'label': label, 'seed': seed, 'repetition': repetition,
                              'mode': mode, 'renderer': row['renderer'],
                              'p50_ms': row['p50_ms'], 'p95_ms': row['p95_ms'],
                              'p99_ms': row['p99_ms'],
                              'submit_p95_ms': row['submit_p95_ms'],
                              'finish_p95_ms': row['finish_p95_ms'],
                              'samples_ms': samples, 'submit_samples_ms': submit,
                              'finish_samples_ms': finish, 'log_sha256': sha(log)}
                    report['runs'].append(result)
                    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                    print(label, row['p95_ms'], flush=True)
        require(sha(binary) == report['benchmark_binary_sha256'] and
                sha(core) == report['benchmark_engine_sha256'] and
                sha(gallium) == report['gallium_sha256'],
                'Benchmark binary, engine, or driver changed during A/B')
    require(data_manifest() == source_files and
            sha(Path(__file__)) == report['runner_sha256'] and
            sha(source_shader) == report['source_shader_sha256'] and
            sha(capture_binary) == report['capture_binary_sha256'] and
            sha(capture_core) == report['capture_engine_sha256'],
            'Source resource or capture binary changed during diagnostic')
    report['diagnostic_complete'] = (
        image_equal and not report['failures'] and
        (args.image_only or len(report['runs']) == args.repeats * 4))
    report['budget_met'] = (not args.image_only and report['diagnostic_complete'] and
                            all(row['p95_ms'] <= 16.67 for row in report['runs']))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    artifact_sha = archive(output)
    print(json.dumps({'diagnostic_complete': report['diagnostic_complete'],
                      'image_equal': image_equal, 'budget_met': report['budget_met'],
                      'output': str(output), 'archive_sha256': artifact_sha}), flush=True)
    return 0 if report['diagnostic_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
