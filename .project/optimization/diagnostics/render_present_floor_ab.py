#!/usr/bin/env python3
"""Compare minimal presentation, GPU completion, and full 1080p match."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

from render_backend_ab import competing_benchmarks, require, sha

ROOT = Path(__file__).resolve().parents[3]
OUTPUTS = ROOT / '.project/optimization/diagnostics'
SOURCE = Path(__file__).with_name('sdl_present_floor.c')


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[math.ceil(fraction * len(values)) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--gpu-driver-root', type=Path, required=True)
    parser.add_argument('--cpu-set')
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    require(1 <= args.repeats <= 4, 'Diagnostic repetitions must be 1-4')
    require(not competing_benchmarks(), 'Present-floor A/B requires an isolated benchmark window')
    build = args.build.resolve()
    driver = args.gpu_driver_root.resolve() / 'lib'
    engine = build / 'bin/engine_render_budget_benchmark'
    core = build / 'libfootball_engine.so'
    gallium = driver / 'libgallium-26.2.2.so'
    require(all(path.is_file() for path in (SOURCE, engine, core, gallium)),
            'Probe source, benchmark, engine, or private GPU driver is missing')
    output = OUTPUTS / f'render-present-floor-ab-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    probe = output / 'sdl_present_floor'
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'sdl2', 'gl'],
                                    text=True).split()
    compile_command = ['cc', '-O2', '-std=c11', str(SOURCE), '-o', str(probe), *flags]
    compiled = subprocess.run(compile_command, cwd=ROOT, capture_output=True, text=True,
                              timeout=120)
    compile_log = output / 'compile.log'
    compile_log.write_text(compiled.stdout + compiled.stderr)
    require(compiled.returncode == 0 and probe.is_file(), 'Probe compilation failed')
    base = dict(os.environ)
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LD_PRELOAD', 'SDL_VIDEODRIVER',
                'GFOOTBALL_RENDER_SKIP_SWAP', 'GFOOTBALL_RENDER_PHASE_PROFILE',
                'GFOOTBALL_RENDER_GPU_PHASE_PROFILE'):
        base.pop(key, None)
    base.update({'SDL_VIDEODRIVER': 'wayland',
                 'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
                 'GFOOTBALL_USE_PBR': '1', 'GFOOTBALL_PBR_BLOOM': '1',
                 'GFOOTBALL_PBR_FXAA': '1', 'GFOOTBALL_PBR_AUTO_EXPOSURE': '1',
                 'LD_LIBRARY_PATH': str(build) + ':' + str(driver),
                 'LIBGL_DRIVERS_PATH': str(driver / 'dri'),
                 'GALLIUM_DRIVER': 'd3d12', 'MESA_LOADER_DRIVER_OVERRIDE': 'd3d12'})
    report = {'schema': 'football-render-present-floor-ab-v2',
              'product_acceptance': False, 'backend': 'wayland',
              'scope': 'diagnostic only; minimal clear/swap, full PBR without swap, full PBR with swap',
              'seeds': [42, 43], 'repeats': args.repeats,
              'source_sha256': sha(SOURCE), 'probe_sha256': sha(probe),
              'benchmark_sha256': sha(engine), 'engine_sha256': sha(core),
              'gallium_sha256': sha(gallium),
              'compile_command': compile_command, 'compile_log_sha256': sha(compile_log),
              'runs': [], 'failures': []}
    for repetition in range(args.repeats):
        for seed in (42, 43):
            modes = (('minimal', 'no_swap', 'full') if (repetition + seed) % 2 == 0
                     else ('full', 'no_swap', 'minimal'))
            for mode in modes:
                label = f'seed{seed}-repeat{repetition}-{mode}'
                command = (['taskset', '-c', args.cpu_set] if args.cpu_set else []) + [
                    str(probe) if mode == 'minimal' else str(engine)]
                if mode != 'minimal':
                    command.append(str(seed))
                if mode == 'no_swap':
                    command.append('--diagnostic')
                log = output / f'{label}.log'
                try:
                    env = dict(base)
                    if mode == 'no_swap':
                        env['GFOOTBALL_RENDER_SKIP_SWAP'] = '1'
                    completed = subprocess.run(command, cwd=ROOT, env=env,
                                               capture_output=True, text=True, timeout=240)
                    log.write_text(completed.stdout + completed.stderr)
                    require(completed.returncode == 0, f'{label} failed; see {log}')
                    if mode == 'minimal':
                        identity = [line.split('\t') for line in completed.stdout.splitlines()
                                    if line.startswith('IDENTITY\t')]
                        frames = [line.split('\t') for line in completed.stdout.splitlines()
                                  if line.startswith('FRAME\t')]
                        require(len(identity) == 1 and len(identity[0]) == 8 and
                                len(frames) == 120 and all(len(row) == 4 for row in frames),
                                f'{label} output is incomplete')
                        _, vendor, renderer, version, path, swap, width, height = identity[0]
                        totals = [float(row[1]) for row in frames]
                        submits = [float(row[2]) for row in frames]
                        finishes = [float(row[3]) for row in frames]
                        quality = 'minimal_clear'
                    else:
                        lines = [line for line in completed.stdout.splitlines()
                                 if line.startswith('{')]
                        require(len(lines) == 1, f'{label} output is incomplete')
                        row = json.loads(lines[0])
                        vendor, renderer, version, path = (row['vendor'], row['renderer'],
                                                           row['gl_version'], row['gallium_path'])
                        swap, width, height = (row['swap_interval'], row['width'], row['height'])
                        totals, submits, finishes = (row['samples_ms'],
                                                     row['submit_samples_ms'],
                                                     row['finish_samples_ms'])
                        quality = row['quality']
                        require(row['seed'] == seed and
                                row['swap_enabled'] is (mode == 'full') and
                                row['measured_frames'] == 120 and
                                quality == 'pbr+bloom+fxaa+auto_exposure',
                                f'{label} did not use the full match workload')
                    require('D3D12' in renderer and Path(path).resolve() == gallium and
                            int(swap) == 0 and (int(width), int(height)) == (1920, 1080) and
                            len(totals) == len(submits) == len(finishes) == 120 and
                            all(math.isfinite(v) and v > 0 for values in
                                (totals, submits, finishes) for v in values) and
                            all(abs(total - submit - finish) < .01 for total, submit, finish
                                in zip(totals, submits, finishes)),
                            f'{label} GPU identity, swap, resolution, or phases differ')
                    row = {'label': label, 'mode': mode, 'seed': seed,
                           'repetition': repetition, 'command': command,
                           'log_sha256': sha(log), 'vendor': vendor, 'renderer': renderer,
                           'gl_version': version, 'gallium_path': path,
                           'swap_interval': int(swap), 'resolution': [int(width), int(height)],
                           'quality': quality, 'p50_ms': percentile(totals, .5),
                           'p95_ms': percentile(totals, .95),
                           'submit_p95_ms': percentile(submits, .95),
                           'finish_p95_ms': percentile(finishes, .95),
                           'samples_ms': totals, 'submit_samples_ms': submits,
                           'finish_samples_ms': finishes}
                    report['runs'].append(row)
                    print(label, row['p95_ms'], flush=True)
                except Exception as error:
                    report['failures'].append(str(error))
                    print(label, 'FAILED', str(error), flush=True)
    report['diagnostic_complete'] = (not report['failures'] and
                                     len(report['runs']) == args.repeats * 2 * 3)
    artifact = output / 'report.json'
    artifact.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'diagnostic_complete': report['diagnostic_complete'],
                      'runs': len(report['runs']), 'failures': report['failures'],
                      'artifact': str(artifact), 'artifact_sha256': sha(artifact)}))
    return 0 if report['diagnostic_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
