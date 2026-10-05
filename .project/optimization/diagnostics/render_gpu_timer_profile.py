#!/usr/bin/env python3
"""Measure full-match GPU stages with timestamp queries and baseline controls."""
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
PATCH = Path(__file__).with_name('render_gpu_timer.patch')


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[math.ceil(fraction * len(values)) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-build', type=Path, required=True)
    parser.add_argument('--profile-build', type=Path, required=True)
    parser.add_argument('--gpu-driver-root', type=Path, required=True)
    parser.add_argument('--cpu-set')
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    require(1 <= args.repeats <= 4, 'Diagnostic repetitions must be 1-4')
    require(not competing_benchmarks(), 'GPU timer profile requires an isolated benchmark window')
    builds = {'baseline': args.baseline_build.resolve(),
              'profile': args.profile_build.resolve()}
    driver = args.gpu_driver_root.resolve() / 'lib'
    gallium = driver / 'libgallium-26.2.2.so'
    require(PATCH.is_file() and gallium.is_file() and all(
        (build / 'bin/engine_render_budget_benchmark').is_file() and
        (build / 'libfootball_engine.so').is_file() for build in builds.values()),
        'Profiling patch, benchmark builds, or GPU driver are missing')
    output = OUTPUTS / f'render-gpu-timer-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'football-render-gpu-timer-v1',
              'product_acceptance': False, 'scope': 'diagnostic GPU timestamps',
              'patch_sha256': sha(PATCH), 'gallium_sha256': sha(gallium),
              'builds': {name: {
                  'benchmark_sha256': sha(build / 'bin/engine_render_budget_benchmark'),
                  'engine_sha256': sha(build / 'libfootball_engine.so')}
                  for name, build in builds.items()},
              'seeds': [42, 43], 'repeats': args.repeats,
              'runs': [], 'failures': []}
    base = dict(os.environ)
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LD_PRELOAD', 'SDL_VIDEODRIVER',
                'GFOOTBALL_RENDER_SKIP_SWAP', 'GFOOTBALL_RENDER_PHASE_PROFILE',
                'GFOOTBALL_RENDER_GPU_PHASE_PROFILE', 'GFOOTBALL_GPU_TIMER_PROFILE'):
        base.pop(key, None)
    base.update({'SDL_VIDEODRIVER': 'wayland',
                 'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
                 'GFOOTBALL_USE_PBR': '1', 'GFOOTBALL_PBR_BLOOM': '1',
                 'GFOOTBALL_PBR_FXAA': '1', 'GFOOTBALL_PBR_AUTO_EXPOSURE': '1',
                 'LIBGL_DRIVERS_PATH': str(driver / 'dri'),
                 'GALLIUM_DRIVER': 'd3d12', 'MESA_LOADER_DRIVER_OVERRIDE': 'd3d12'})
    for repetition in range(args.repeats):
        for seed in (42, 43):
            modes = (('baseline_full', 'profile_no_swap', 'profile_full')
                     if (repetition + seed) % 2 == 0 else
                     ('profile_full', 'profile_no_swap', 'baseline_full'))
            for mode in modes:
                label = f'seed{seed}-repeat{repetition}-{mode}'
                build = builds['baseline' if mode == 'baseline_full' else 'profile']
                command = (['taskset', '-c', args.cpu_set] if args.cpu_set else []) + [
                    str(build / 'bin/engine_render_budget_benchmark'), str(seed)]
                env = dict(base, LD_LIBRARY_PATH=str(build) + ':' + str(driver))
                if mode != 'baseline_full':
                    env['GFOOTBALL_GPU_TIMER_PROFILE'] = '1'
                if mode == 'profile_no_swap':
                    env['GFOOTBALL_RENDER_SKIP_SWAP'] = '1'
                    command.append('--diagnostic')
                log = output / f'{label}.log'
                try:
                    completed = subprocess.run(command, cwd=ROOT, env=env,
                                               capture_output=True, text=True, timeout=240)
                    log.write_text(completed.stdout + completed.stderr)
                    require(completed.returncode == 0, f'{label} failed; see {log}')
                    lines = [line for line in completed.stdout.splitlines()
                             if line.startswith('{')]
                    require(len(lines) == 1, f'{label} benchmark JSON is incomplete')
                    row = json.loads(lines[0])
                    samples = row['samples_ms']
                    require(row['seed'] == seed and row['swap_enabled'] is
                            (mode != 'profile_no_swap') and row['swap_interval'] == 0 and
                            (row['width'], row['height']) == (1920, 1080) and
                            row['quality'] == 'pbr+bloom+fxaa+auto_exposure' and
                            row['measured_frames'] == 120 and len(samples) == 120 and
                            'D3D12' in row['renderer'] and
                            Path(row['gallium_path']).resolve() == gallium and
                            abs(percentile(samples, .95) - row['p95_ms']) < .001,
                            f'{label} measured a different render workload')
                    result = {'label': label, 'seed': seed, 'repetition': repetition,
                              'mode': mode, 'command': command, 'log_sha256': sha(log),
                              'renderer': row['renderer'], 'p95_ms': row['p95_ms'],
                              'samples_ms': samples}
                    raw = [line.split() for line in completed.stderr.splitlines()
                           if line.startswith('GPU_TIMER_SAMPLE ')]
                    if mode == 'baseline_full':
                        require(not raw, f'{label} unexpectedly enabled GPU profiling')
                    else:
                        require(len(raw) == 120 and
                                all(len(values) == 6 and int(values[1]) == index
                                    for index, values in enumerate(raw)),
                                f'{label} GPU timer output is incomplete')
                        phases = {'geometry_ms': [], 'lighting_ms': [],
                                  'post_ms': [], 'total_ms': []}
                        for values in raw:
                            times = [int(value) for value in values[2:]]
                            require(all(value > 0 for value in times) and
                                    sum(times[:3]) == times[3],
                                    f'{label} GPU timestamp phases do not reconcile')
                            for key, value in zip(phases, times):
                                phases[key].append(value / 1_000_000)
                        result['gpu_p95_ms'] = {key: percentile(values, .95)
                                                 for key, values in phases.items()}
                        result['gpu_samples_ms'] = phases
                    report['runs'].append(result)
                    print(label, 'wall_p95', row['p95_ms'],
                          'gpu_p95', result.get('gpu_p95_ms'), flush=True)
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
