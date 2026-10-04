#!/usr/bin/env python3
"""Fail-closed 1080p product render budget on an identified OpenGL device."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / '.project/optimization/benchmarks'
SAMPLES = 120
MAX_P95_MS = 16.67
SOFTWARE = re.compile(r'llvmpipe|softpipe|swrast|software|lavapipe|gdi generic|basic render driver', re.I)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[math.ceil(fraction * len(values)) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path)
    parser.add_argument('--gpu-driver-root', type=Path, default=Path(
        os.environ['FOOTBALL_RENDER_GPU_DRIVER_ROOT']) if
        os.environ.get('FOOTBALL_RENDER_GPU_DRIVER_ROOT') else None)
    args = parser.parse_args()
    if platform.system() != 'Linux' or sys.flags.optimize != 0:
        raise RuntimeError('Native render budget requires Linux and enabled assertions')
    output = BENCHMARKS / f'render-regression-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    build = (args.build or output / 'build').resolve()
    commands: list[dict] = []
    assertions = 0

    def require(condition: bool, message: str) -> None:
        nonlocal assertions
        assertions += 1
        if not condition:
            raise RuntimeError(message)

    def run(label: str, argv: list[str], *, env: dict | None = None,
            timeout: int = 300) -> str:
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=timeout)
        (output / f'{label}.log').write_text(result.stdout + result.stderr)
        commands.append({'label': label, 'argv': argv,
                         'returncode': result.returncode,
                         'log_sha256': sha(output / f'{label}.log')})
        require(result.returncode == 0, f'{label} failed; see {output / (label + ".log")}')
        return result.stdout

    try:
        run('configure', ['cmake', '-S', str(ROOT / 'engine'), '-B', str(build),
                          '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_PYTHON_BINDINGS=OFF',
                          '-DBUILD_RL_TRAINING=OFF', '-DFOOTBALL_ENABLE_SANITIZERS=OFF',
                          '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                          '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')],
            timeout=180)
        run('build', ['cmake', '--build', str(build), '-j', '2', '--target',
                      'engine_render_budget_benchmark'], timeout=1500)
        binary = build / 'bin/engine_render_budget_benchmark'
        core = build / 'libfootball_engine.so'
        require(binary.is_file() and core.is_file(), 'Render benchmark binaries missing')
        driver_root = args.gpu_driver_root.resolve() if args.gpu_driver_root else None
        driver_lib = driver_root / 'lib' if driver_root else None
        gallium = driver_lib / 'libgallium-26.2.2.so' if driver_lib else None
        if driver_lib:
            require(gallium.is_file() and (driver_lib / 'dri/d3d12_dri.so').is_file(),
                    'Requested private D3D12 driver is missing')
        base_env = dict(os.environ)
        for key in ('LIBGL_ALWAYS_SOFTWARE', 'MESA_LOADER_DRIVER_OVERRIDE',
                    'LD_PRELOAD', 'GFOOTBALL_USE_PBR', 'GFOOTBALL_PBR_BLOOM',
                    'GFOOTBALL_PBR_FXAA', 'GFOOTBALL_PBR_AUTO_EXPOSURE',
                    'GFOOTBALL_PBR_EXPOSURE', 'GFOOTBALL_RENDER_PHASE_PROFILE',
                    'GFOOTBALL_RENDER_GPU_PHASE_PROFILE',
                    'GFOOTBALL_RENDER_SKIP_SWAP'):
            base_env.pop(key, None)
        base_env.update({
            'GFOOTBALL_DATA_DIR': str(ROOT / 'engine/data'),
            'GFOOTBALL_USE_PBR': '1',
            'GFOOTBALL_PBR_BLOOM': '1',
            'GFOOTBALL_PBR_FXAA': '1',
            'GFOOTBALL_PBR_AUTO_EXPOSURE': '1',
            'LD_LIBRARY_PATH': str(build),
        })
        if driver_lib:
            base_env.update({
                'LD_LIBRARY_PATH': str(build) + ':' + str(driver_lib),
                'LIBGL_DRIVERS_PATH': str(driver_lib / 'dri'),
                'GALLIUM_DRIVER': 'd3d12',
                'MESA_LOADER_DRIVER_OVERRIDE': 'd3d12',
            })
        measurements = []
        failures = []
        for seed in (42, 43):
            text = run(f'seed-{seed}', [str(binary), str(seed)], env=base_env,
                       timeout=300)
            row = json.loads(text.splitlines()[-1])
            require(row['seed'] == seed and
                    (row['width'], row['height']) == (1920, 1080),
                    'Benchmark used the wrong match or resolution')
            require(row['quality'] == 'pbr+bloom+fxaa+auto_exposure' and
                    row['swap_enabled'] is True and
                    row['warmup_frames'] == 30 and
                    row['measured_frames'] == SAMPLES and
                    row['in_play_frames'] > 0,
                    'Benchmark did not render the required live quality profile')
            values = row['samples_ms']
            require(len(values) == SAMPLES, 'Measured frame sample count changed')
            submit = row['submit_samples_ms']
            finish = row['finish_samples_ms']
            require(len(submit) == SAMPLES and len(finish) == SAMPLES,
                    'Render submit/finish sample count changed')
            for total, submitted, completed in zip(values, submit, finish):
                require(all(math.isfinite(value) and value > 0 for value in
                            (total, submitted, completed)) and
                        abs(total - submitted - completed) < .01,
                        'Render phase samples do not reconcile')
            for value in values:
                require(isinstance(value, (int, float)) and math.isfinite(value)
                        and value > 0, 'Invalid measured render frame time')
            require(abs(percentile(values, .95) - row['p95_ms']) < .001,
                    'Reported p95 does not match raw frame times')
            require(bool(row['renderer']) and bool(row['vendor']) and
                    bool(row['gl_version']), 'OpenGL device identity missing')
            if gallium:
                require(Path(row['gallium_path']).resolve() == gallium.resolve(),
                        'Benchmark did not load the requested Gallium driver')
                require('D3D12' in row['renderer'],
                        'Requested D3D12 renderer was not selected')
            if SOFTWARE.search(row['renderer']):
                failures.append(f'seed {seed}: software renderer {row["renderer"]}')
            if row['p95_ms'] > MAX_P95_MS:
                failures.append(f'seed {seed}: 1080p render p95 '
                                f'{row["p95_ms"]:.3f} ms exceeds {MAX_P95_MS:.2f} ms')
            measurements.append(row)
        require(measurements[0]['renderer'] == measurements[1]['renderer'] and
                measurements[0]['vendor'] == measurements[1]['vendor'],
                'Renderer identity changed between match seeds')
        report = {
            'passed': not failures, 'assertions': assertions,
            'skipped': 0, 'failures': failures,
            'metric': 'GameEnv.render plus glFinish wall duration',
            'resolution': [1920, 1080],
            'quality': 'pbr+bloom+fxaa+auto_exposure',
            'p95_budget_ms': MAX_P95_MS,
            'product_acceptance': not failures,
            'binaries': {'engine_sha256': sha(core),
                         'benchmark_sha256': sha(binary),
                         'gallium_sha256': sha(gallium) if gallium else None},
            'gpu_driver_root': str(driver_root) if driver_root else None,
            'measurements': measurements, 'commands': commands,
        }
        artifact = output / 'report.json'
        artifact.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: report[key] for key in (
            'passed', 'assertions', 'skipped', 'failures', 'metric', 'resolution',
            'quality', 'p95_budget_ms', 'product_acceptance')}
            | {'artifact': str(artifact.relative_to(ROOT)),
               'artifact_sha256': sha(artifact)}))
        return 0 if report['passed'] else 1
    except Exception as error:
        failure = {'passed': False, 'assertions': assertions, 'skipped': 0,
                   'failures': [str(error)], 'product_acceptance': False,
                   'commands': commands}
        (output / 'failure.json').write_text(json.dumps(failure, indent=2) + '\n')
        print(json.dumps(failure))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
