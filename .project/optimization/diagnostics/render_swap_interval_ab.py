#!/usr/bin/env python3
"""Compare real 1080p SDL presentation modes without changing the engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name('sdl_swap_interval_probe.c')
OUTPUTS = ROOT / '.project/optimization/diagnostics'
MODES = ((0, -1, 1), (1, -1, 0), (-1, 0, 1), (1, 0, -1))
PROBE = re.compile(r'swap_interval_probe requested=(-?\d+) result=(-?\d+) actual=(-?\d+)')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def competing_benchmarks() -> list[int]:
    active = []
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            command = (process / 'cmdline').read_bytes().replace(b'\0', b' ')
        except (OSError, PermissionError):
            continue
        if any(name in command for name in
               (b'engine_soak_benchmark', b'product_soak.py',
                b'engine_render_budget_benchmark')):
            active.append(int(process.name))
    return active


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--gpu-driver-root', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--cpu-set')
    args = parser.parse_args()
    require(1 <= args.repeats <= 4, 'Diagnostic repetitions must be 1–4')
    require(not competing_benchmarks(),
            'Another soak or render benchmark is active; interval A/B requires isolation')
    build = args.build.resolve()
    driver = args.gpu_driver_root.resolve() / 'lib'
    binary = build / 'bin/engine_render_budget_benchmark'
    core = build / 'libfootball_engine.so'
    gallium = driver / 'libgallium-26.2.2.so'
    require(all(path.is_file() for path in (binary, core, gallium, SOURCE)),
            'Render benchmark, engine, private GPU driver, or probe source is missing')

    output = OUTPUTS / f'render-swap-interval-ab-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    probe = output / 'sdl_swap_interval_probe.so'
    compilation = subprocess.run(
        ['cc', '-shared', '-fPIC', '-O2', str(SOURCE), '-o', str(probe), '-ldl'],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    (output / 'compile.log').write_text(compilation.stdout + compilation.stderr)
    require(compilation.returncode == 0 and probe.is_file(),
            f'SDL diagnostic probe failed to compile: {compilation.stderr[-500:]}')

    base = dict(os.environ)
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LD_PRELOAD', 'GFOOTBALL_RENDER_SKIP_SWAP',
                'GFOOTBALL_RENDER_PHASE_PROFILE', 'GFOOTBALL_RENDER_GPU_PHASE_PROFILE'):
        base.pop(key, None)
    base.update({'SDL_VIDEODRIVER': 'wayland',
                 'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
                 'GFOOTBALL_USE_PBR': '1', 'GFOOTBALL_PBR_BLOOM': '1',
                 'GFOOTBALL_PBR_FXAA': '1',
                 'GFOOTBALL_PBR_AUTO_EXPOSURE': '1',
                 'LD_LIBRARY_PATH': str(build) + ':' + str(driver),
                 'LIBGL_DRIVERS_PATH': str(driver / 'dri'),
                 'GALLIUM_DRIVER': 'd3d12',
                 'MESA_LOADER_DRIVER_OVERRIDE': 'd3d12',
                 'LD_PRELOAD': str(probe)})
    report = {'schema': 'football-render-swap-interval-ab-v1',
              'product_acceptance': False,
              'scope': 'diagnostic only; full 1080p rendered frames with real SDL swap',
              'quality': 'pbr+bloom+fxaa+auto_exposure',
              'seeds': [42, 43], 'repeats': args.repeats,
              'binary_sha256': sha(binary), 'engine_sha256': sha(core),
              'gallium_sha256': sha(gallium), 'probe_source_sha256': sha(SOURCE),
              'probe_sha256': sha(probe), 'runs': [], 'failures': []}
    for repetition in range(args.repeats):
        for seed in (42, 43):
            modes = MODES[(repetition * 2 + (seed == 43)) % len(MODES)]
            for mode in modes:
                label = f'seed{seed}-repeat{repetition}-mode{mode}'
                env = dict(base, FOOTBALL_DIAGNOSTIC_SWAP_INTERVAL=str(mode))
                command = (["taskset", "-c", args.cpu_set] if args.cpu_set else []) + [
                    str(binary), str(seed)]
                try:
                    completed = subprocess.run(command, cwd=ROOT, env=env,
                                               capture_output=True, text=True,
                                               timeout=240)
                    log = output / f'{label}.log'
                    log.write_text(completed.stdout + completed.stderr)
                    lines = [line for line in completed.stdout.splitlines()
                             if line.startswith('{')]
                    require(completed.returncode == 0 and len(lines) == 1,
                            f'{label} failed; see {log}')
                    row = json.loads(lines[0])
                    matches = PROBE.findall(completed.stderr)
                    require(len(matches) == 1 and
                            tuple(map(int, matches[0])) == (mode, 0, mode),
                            f'{label} driver did not accept the requested interval')
                    samples = row['samples_ms']
                    submit = row['submit_samples_ms']
                    finish = row['finish_samples_ms']
                    require(row['seed'] == seed and row['swap_interval'] == mode and
                            row['swap_enabled'] is True and
                            (row['width'], row['height']) == (1920, 1080) and
                            row['quality'] == report['quality'] and
                            row['measured_frames'] == 120 and
                            len(samples) == len(submit) == len(finish) == 120 and
                            'D3D12' in row['renderer'] and
                            Path(row['gallium_path']).resolve() == gallium,
                            f'{label} did not measure the required GPU workload')
                    require(all(math.isfinite(x) and x > 0 for values in
                                (samples, submit, finish) for x in values) and
                            all(abs(total - sent - completed) < .01 for
                                total, sent, completed in zip(samples, submit, finish)) and
                            abs(sorted(samples)[math.ceil(.95 * len(samples)) - 1] -
                                row['p95_ms']) < .001,
                            f'{label} frame phases or p95 do not match raw samples')
                    report['runs'].append({'label': label, 'seed': seed,
                                           'repetition': repetition, 'mode': mode,
                                           'command': command, 'log_sha256': sha(log),
                                           'renderer': row['renderer'],
                                           'p50_ms': row['p50_ms'],
                                           'p95_ms': row['p95_ms'],
                                           'p99_ms': row['p99_ms'],
                                           'submit_p95_ms': row['submit_p95_ms'],
                                           'finish_p95_ms': row['finish_p95_ms'],
                                           'samples_ms': samples,
                                           'submit_samples_ms': submit,
                                           'finish_samples_ms': finish})
                    print(label, row['p95_ms'], flush=True)
                except Exception as error:
                    report['failures'].append(str(error))
                    break
            if report['failures']:
                break
        if report['failures']:
            break
    report['diagnostic_complete'] = (
        not report['failures'] and len(report['runs']) == args.repeats * 2 * 3)
    artifact = output / 'report.json'
    artifact.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'diagnostic_complete': report['diagnostic_complete'],
                      'runs': len(report['runs']), 'failures': report['failures'],
                      'artifact': str(artifact), 'artifact_sha256': sha(artifact)}))
    return 0 if report['diagnostic_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
