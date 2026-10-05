#!/usr/bin/env python3
"""Fail-closed 108k-frame, three-seed Release and ASan/UBSan product soak."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import match_benchmark

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / '.project/optimization/benchmarks'
SEEDS = (42, 43, 44)
WARMUP = 1000
FRAMES = 36000
RSS_GROWTH_BYTES = 4 * 1024 * 1024
RSS_PLATEAU_BYTES = 256 * 1024
SANITIZER_RSS_GROWTH_BYTES = 256 * 1024 * 1024
TRAJECTORY = ('input_hash', 'warm_hash', 'final_hash',
              'state_checkpoints', 'active_flags')
SOURCES = ('engine/CMakeLists.txt', 'engine/sources.cmake',
           'engine/src/**/*.cpp', 'engine/src/**/*.hpp', 'engine/src/**/*.h',
           'engine/tests/engine_soak_benchmark.cpp', 'engine/data/**/*',
           '.project/checks/product_soak.py', '.project/checks/match_benchmark.py',
           '.project/checks/native_boundary.py')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = {path for pattern in SOURCES for path in ROOT.glob(pattern)
             if path.is_file()}
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def memory_result(row: dict, *, instrumented: bool) -> tuple[dict, dict]:
    observations = row['rss_checkpoints_bytes']
    quarter = len(observations) // 4
    window_medians = [statistics.median(observations[start:start + 60])
                      for start in range(1, len(observations), 60)]
    first = statistics.median(observations[:quarter])
    last = statistics.median(observations[-quarter:])
    summary = {'warm_bytes': row['warm_rss_bytes'],
               'observed_max_bytes': max(observations),
               'first_quarter_median_bytes': first,
               'last_quarter_median_bytes': last,
               'last_three_window_medians_bytes': window_medians[-3:],
               'closed_bytes': row['closed_rss_bytes'],
               'peak_including_replay_bytes': row['peak_rss_bytes']}
    if instrumented:
        # ASan's allocation quarantine deliberately retains freed blocks.
        # Bound that diagnostic footprint separately; product RSS uses the
        # stricter Release growth and plateau requirements below.
        checks = {'instrumented_rss_bound': summary['observed_max_bytes'] <=
                  summary['warm_bytes'] + SANITIZER_RSS_GROWTH_BYTES}
    else:
        checks = {
            'bounded_growth': summary['observed_max_bytes'] <=
                              summary['warm_bytes'] + RSS_GROWTH_BYTES,
            'quarter_plateau': last <= first + RSS_PLATEAU_BYTES,
            'late_window_plateau': max(window_medians[-3:]) -
                                   min(window_medians[-3:]) <= RSS_PLATEAU_BYTES,
        }
    return summary, checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-build', type=Path,
                        default=Path('/tmp/football-optimization-native'))
    parser.add_argument('--sanitized-build', type=Path,
                        default=Path('/tmp/football-optimization-sanitized'))
    parser.add_argument('--cpu', type=int)
    args = parser.parse_args()
    output = BENCHMARKS / f'product-soak-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {'passed': False, 'assertions': 0, 'skipped': 0,
                    'scope': '108000 measured 11v11 logical frames per build, '
                             'three seeds, Release and ASan/UBSan; full trajectory replay, '
                             'strict Release RSS plateau and separate instrumented RSS bound; '
                             'excluding rendering and WAN',
                    'seeds': SEEDS, 'warmup_frames': WARMUP,
                    'frames_per_seed': FRAMES, 'commands': [], 'runs': [],
                    'artifact': str(output / 'report.json')}

    def require(condition: bool, message: str) -> None:
        report['assertions'] += 1
        if not condition:
            raise RuntimeError(message)

    def run(label: str, argv: list[str | Path | int], *, env: dict | None = None,
            timeout: int = 1800) -> str:
        print(label, file=sys.stderr, flush=True)
        command = list(map(str, argv))
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                    text=True, timeout=timeout)
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
                'Native Linux and enabled Python assertions are required')
        allowed = os.sched_getaffinity(0)
        cpu = min(allowed) if args.cpu is None else args.cpu
        require(cpu in allowed, 'Requested soak CPU is unavailable')
        report['cpu'] = cpu
        original = source_manifest()
        report['source_manifest_sha256'] = hashlib.sha256(
            json.dumps(original, sort_keys=True).encode()).hexdigest()
        builds = {'release': args.release_build.resolve(),
                  'sanitized': args.sanitized_build.resolve()}
        binaries: dict[str, dict] = {}
        for label, build in builds.items():
            run(f'{label}-configure', ['cmake', '-S', ROOT / 'engine', '-B', build,
                                      '-DCMAKE_BUILD_TYPE=Release',
                                      '-DBUILD_PYTHON_BINDINGS=OFF',
                                      '-DBUILD_RL_TRAINING=OFF',
                                      '-DFOOTBALL_ENABLE_SANITIZERS=' +
                                      ('ON' if label == 'sanitized' else 'OFF'),
                                      f'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / "bin"}'],
                timeout=180)
            run(f'{label}-build', ['cmake', '--build', build, '-j', '2',
                                  '--target', 'engine_soak_benchmark'], timeout=2100)
            binary = build / 'bin/engine_soak_benchmark'
            core = build / 'libfootball_engine.so'
            require(binary.is_file() and core.is_file(),
                    f'{label} native soak binary is missing')
            linkage = run(f'{label}-linkage', ['ldd', binary])
            linked = re.search(r'libfootball_engine\.so => (\S+)', linkage)
            require(linked is not None and Path(linked.group(1)).resolve() == core,
                    f'{label} linked a different engine')
            has_asan = 'libasan.so' in linkage
            has_ubsan = 'libubsan.so' in linkage
            require((has_asan and has_ubsan) if label == 'sanitized' else
                    not (has_asan or has_ubsan),
                    f'{label} sanitizer configuration is wrong')
            binaries[label] = {'benchmark': str(binary),
                               'benchmark_sha256': sha(binary),
                               'engine': str(core), 'engine_sha256': sha(core),
                               'asan': has_asan, 'ubsan': has_ubsan}
        report['binaries'] = binaries

        by_seed: dict[int, dict[str, dict]] = {seed: {} for seed in SEEDS}
        for seed in SEEDS:
            for label, build in builds.items():
                env = dict(os.environ)
                for key in ('LD_PRELOAD', 'GFOOTBALL_USE_PBR',
                            'GFOOTBALL_PBR_BLOOM', 'GFOOTBALL_PBR_FXAA',
                            'GFOOTBALL_PBR_AUTO_EXPOSURE'):
                    env.pop(key, None)
                env['LD_LIBRARY_PATH'] = str(build)
                env['GFOOTBALL_DATA_DIR'] = str(ROOT / 'engine/data')
                if label == 'sanitized':
                    env['ASAN_OPTIONS'] = 'detect_leaks=1:halt_on_error=1:abort_on_error=1'
                    env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
                value = run(f'{label}-{seed}',
                            [build / 'bin/engine_soak_benchmark', seed, cpu],
                            env=env, timeout=1800)
                lines = [line for line in value.splitlines() if line.startswith('{')]
                require(len(lines) == 1, f'{label} seed {seed} omitted native result')
                row = json.loads(lines[0])
                require(row.get('measurement_storage_prefaulted') is True and
                        row.get('workload') == 'headless-11v11-long-v1',
                        'Soak fixture did not pre-touch measurement storage')
                report['assertions'] += match_benchmark.validate_run(
                    row, seed, WARMUP, FRAMES, cpu) + row['assertions']
                memory, checks = memory_result(row, instrumented=label == 'sanitized')
                report['assertions'] += len(checks)
                require(all(checks.values()),
                        f'{label} seed {seed} exceeded memory bounds: {checks}')
                require(row['steady']['p99_ns'] < 50_000_000 if label == 'release' else True,
                        f'{label} seed {seed} exceeded logical-frame p99 budget')
                by_seed[seed][label] = row
                report['runs'].append({'seed': seed, 'build': label,
                                       'measured_frames': row['measured_frames'],
                                       'active_frames': sum(row['active_flags']),
                                       'final_hash': row['final_hash'],
                                       'steady_p99_ns': row['steady']['p99_ns'],
                                       'memory': memory, 'memory_checks': checks,
                                       'log_sha256': sha(output / f'{label}-{seed}.log')})
            for field in TRAJECTORY:
                require(by_seed[seed]['release'][field] ==
                        by_seed[seed]['sanitized'][field],
                        f'Seed {seed} diverged across Release and ASan/UBSan: {field}')
        totals = {label: sum(row['measured_frames'] for seed in SEEDS
                             for row in (by_seed[seed][label],))
                  for label in builds}
        require(all(total >= 100000 for total in totals.values()),
                'Soak did not cover 100000 logical frames in each build')
        report['measured_frames_by_build'] = totals
        require(source_manifest() == original, 'Soak sources changed during acceptance')
        for row in binaries.values():
            require(sha(Path(row['benchmark'])) == row['benchmark_sha256'] and
                    sha(Path(row['engine'])) == row['engine_sha256'],
                    'Measured native binary changed during acceptance')
        require(report['assertions'] >= 300, 'Insufficient product soak assertions')
        report['passed'] = True
    except BaseException as error:
        report['error'] = str(error)
    finally:
        artifact = output / 'report.json'
        artifact.write_text(json.dumps(report, indent=2) + '\n')
        report['artifact_sha256'] = sha(artifact)
        print(json.dumps({key: report.get(key) for key in (
            'passed', 'assertions', 'skipped', 'error', 'artifact',
            'measured_frames_by_build')} | {'artifact_sha256': report['artifact_sha256']}),
            flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
