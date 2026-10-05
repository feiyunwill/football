#!/usr/bin/env python3
"""Run a fixed 11v11 AI cohort against a sealed, independent match baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / '.project/optimization/baselines/ai_match_reference_20261005.json'
BASELINE_SHA256 = 'baef37cdfbf9873f7dd92db076e6053cc6871aea60be2ed0162f5e20ce2fa152'
SEEDS = tuple(range(42, 66))
FRAMES = 6000
PAIR_FIELDS = ('score', 'pass_attempts', 'kicked_passes', 'shot_attempts',
               'kicked_shots', 'fouls', 'invalid_intents')
SOURCE_GLOBS = ('engine/CMakeLists.txt', 'engine/sources.cmake',
                'engine/src/**/*.cpp', 'engine/src/**/*.hpp', 'engine/src/**/*.h',
                'engine/data/**/*',
                'engine/tests/engine_ai_match_metrics.cpp',
                '.project/checks/ai_regression.py',
                '.project/optimization/baselines/ai_match_reference_20261005.json')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = {path for pattern in SOURCE_GLOBS for path in ROOT.glob(pattern)
             if path.is_file()}
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def interval(values: list[float], fraction: float = .95) -> list[float]:
    values.sort()
    tail = (1 - fraction) / 2
    return [values[int(tail * len(values))],
            values[min(len(values) - 1, int((1 - tail) * len(values)))]]


def bootstrap(values: list[float], *, seed: int) -> list[float]:
    rng = random.Random(seed)
    size = len(values)
    means = [sum(values[rng.randrange(size)] for _ in range(size)) / size
             for _ in range(10000)]
    return interval(means)


def side_points(row: dict) -> float:
    left, right = row['score']
    return 1.0 if left > right else 0.0 if left < right else .5


def total(row: dict, field: str) -> int:
    return sum(row[field])


def invalid_rate(row: dict) -> float:
    attempts = total(row, 'pass_attempts') + total(row, 'shot_attempts')
    return total(row, 'invalid_intents') / attempts if attempts else 0.0


def assess(reference: list[dict], candidate: list[dict]) -> tuple[dict, list[str]]:
    """Paired seed bootstrap retains match-level correlation and fixed fixture size."""
    errors: list[str] = []
    points = [side_points(row) for row in candidate]
    point_rate = sum(points) / len(points)
    point_ci = bootstrap(points, seed=20261005)
    point_delta = bootstrap([side_points(new) - side_points(old)
                             for old, new in zip(reference, candidate)], seed=20261006)
    decisive = sum(row['score'][0] != row['score'][1] for row in candidate)
    if not .4 <= point_rate <= .6 or not point_ci[0] <= .5 <= point_ci[1]:
        errors.append('Left/right match points are imbalanced')
    if point_delta[0] < -.10:
        errors.append('Paired match points fell by more than 0.10')
    if decisive < 6:
        errors.append('Too few decisive matches to exercise scoring')
    action_report = {}
    for field, floor in (('kicked_passes', 60), ('kicked_shots', 50)):
        current = [total(row, field) for row in candidate]
        previous = [total(row, field) for row in reference]
        # Paired difference is well-defined even if a seed has no action.
        difference_ci = bootstrap([new - old for old, new in zip(previous, current)],
                                  seed=20261007 if field == 'kicked_passes' else 20261008)
        baseline_mean = sum(previous) / len(previous)
        ratio_lower = (baseline_mean + difference_ci[0]) / baseline_mean
        sides = [sum(row[field][side] for row in candidate) for side in (0, 1)]
        action_report[field] = {'candidate_sides': sides,
                                'baseline_total': sum(previous),
                                'candidate_total': sum(current),
                                'paired_difference_ci95': difference_ci,
                                'paired_ratio_lower95': ratio_lower}
        if min(sides) < floor or ratio_lower < .80:
            errors.append(f'{field} activity or paired noninferiority failed')
    foul_delta = bootstrap([total(new, 'fouls') - total(old, 'fouls')
                            for old, new in zip(reference, candidate)], seed=20261009)
    invalid_delta = bootstrap([invalid_rate(new) - invalid_rate(old)
                               for old, new in zip(reference, candidate)], seed=20261010)
    attempted = sum(total(row, 'pass_attempts') + total(row, 'shot_attempts')
                    for row in candidate)
    invalid = sum(total(row, 'invalid_intents') for row in candidate)
    aggregate_invalid_rate = invalid / attempted
    if foul_delta[1] > .5:
        errors.append('Fouls rose by more than 0.5 per match')
    if aggregate_invalid_rate > .30 or invalid_delta[1] > .05:
        errors.append('Unexecuted pass/shot intent rate regressed')
    return ({'left_match_points_rate': point_rate,
             'left_match_points_ci95': point_ci,
             'paired_match_points_delta_ci95': point_delta,
             'decisive_matches': decisive,
             'actions': action_report,
             'fouls_per_match': sum(total(row, 'fouls') for row in candidate) / len(candidate),
             'paired_fouls_delta_ci95': foul_delta,
             'invalid_intent_rate': aggregate_invalid_rate,
             'paired_invalid_rate_delta_ci95': invalid_delta,
             'left_wins': sum(row['score'][0] > row['score'][1] for row in candidate),
             'right_wins': sum(row['score'][0] < row['score'][1] for row in candidate),
             'draws': len(candidate) - decisive}, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-build', type=Path)
    parser.add_argument('--sanitized-build', type=Path)
    args = parser.parse_args()
    output = ROOT / '.project/optimization/benchmarks' / f'ai-regression-{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {'schema': 'ai-regression-v1', 'passed': False,
                    'skipped': 0, 'assertions': 0, 'artifact': str(output / 'report.json'),
                    'baseline_sha256': BASELINE_SHA256, 'commands': [],
                    'fixture': {'seeds': SEEDS, 'frames': FRAMES,
                                'sanitizer_probe_frames': 3000}}

    def require(condition: bool, message: str) -> None:
        report['assertions'] += 1
        if not condition:
            raise RuntimeError(message)

    def run(label: str, argv: list[str | Path], timeout: int = 1800,
            env: dict | None = None) -> str:
        print(label, file=sys.stderr, flush=True)
        result = subprocess.run([str(arg) for arg in argv], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=timeout)
        log = output / f'{label}.log'
        log.write_text(result.stdout + result.stderr)
        report['commands'].append({'label': label, 'argv': list(map(str, argv)),
                                   'returncode': result.returncode,
                                   'log_sha256': sha(log)})
        require(result.returncode == 0, f'{label} failed; see {log}')
        return result.stdout

    def check_row(row: dict, seed: int, frames: int) -> None:
        require(isinstance(row, dict) and row.get('schema') == 'ai-match-metrics-v1',
                f'Bad metrics schema for {seed}')
        require(row.get('seed') == seed and row.get('frames') == frames,
                f'Wrong fixture for {seed}')
        require(isinstance(row.get('match_time_ms'), int) and
                row['match_time_ms'] > 4000 * frames // 3,
                f'Match clock did not advance for {seed}')
        require(isinstance(row.get('final_hash'), str) and
                re.fullmatch(r'[0-9a-f]{16}', row['final_hash']) is not None,
                f'Bad final state hash for {seed}')
        for field in PAIR_FIELDS:
            values = row.get(field)
            require(isinstance(values, list) and len(values) == 2 and
                    all(type(value) is int and value >= 0 for value in values),
                    f'Invalid {field} for {seed}')
        require(type(row.get('unattributed_fouls')) is int and
                row['unattributed_fouls'] == 0,
                f'Unattributed foul for {seed}')
        for side in (0, 1):
            require(row['kicked_passes'][side] <= row['pass_attempts'][side] and
                    row['kicked_shots'][side] <= row['shot_attempts'][side],
                    f'Kicks exceed intents for {seed}, side {side}')
            require(row['invalid_intents'][side] <=
                    row['pass_attempts'][side] + row['shot_attempts'][side],
                    f'Invalid intents exceed attempts for {seed}, side {side}')

    try:
        require(platform.system() == 'Linux' and sys.flags.optimize == 0,
                'Native Linux with assertions is required')
        require(sha(BASELINE) == BASELINE_SHA256, 'Sealed baseline checksum changed')
        reference = json.loads(BASELINE.read_text())
        require(reference.get('schema') == 'ai-match-reference-v1' and
                reference.get('source_commit') ==
                '2a4be4e33f4bb29f96334de46f9dffaeb5eff723',
                'Baseline provenance changed')
        require(reference.get('evaluator_sha256') ==
                sha(ROOT / 'engine/tests/engine_ai_match_metrics.cpp'),
                'Evaluator semantics changed since baseline')
        fixture = reference.get('fixture', {})
        require(fixture.get('frames') == FRAMES and
                fixture.get('seeds') == list(SEEDS) and
                fixture.get('teams') == '11v11 AI vs AI' and
                fixture.get('left_team_difficulty') ==
                fixture.get('right_team_difficulty') == 1.0,
                'Baseline fixture changed')
        previous = reference.get('rows')
        require(isinstance(previous, list) and len(previous) == len(SEEDS),
                'Baseline cohort incomplete')
        for seed, row in zip(SEEDS, previous):
            check_row(row, seed, FRAMES)
        repeat_reference = reference.get('repeat_rows')
        require(isinstance(repeat_reference, list) and len(repeat_reference) == 2,
                'Baseline repeat checks absent')
        for seed, row in zip((SEEDS[0], SEEDS[-1]), repeat_reference):
            check_row(row, seed, FRAMES)
            require(row == previous[seed - SEEDS[0]],
                    f'Baseline seed {seed} is nondeterministic')
        sources = source_manifest()
        report['inputs'] = {
            'file_count': len(sources),
            'data_file_count': sum(path.startswith('engine/data/') for path in sources),
            'manifest_sha256': hashlib.sha256(json.dumps(
                sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        }
        builds = {'release': (args.release_build or output / 'release-build').resolve(),
                  'sanitized': (args.sanitized_build or output / 'sanitized-build').resolve()}
        binaries = {}
        for label, build in builds.items():
            run(f'{label}-configure',
                ['cmake', '-S', ROOT / 'engine', '-B', build,
                 '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_PYTHON_BINDINGS=OFF',
                 '-DBUILD_RL_TRAINING=OFF',
                 '-DFOOTBALL_ENABLE_SANITIZERS=' + ('ON' if label == 'sanitized' else 'OFF'),
                 '-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=' + str(build / 'bin')], timeout=180)
            run(f'{label}-build', ['cmake', '--build', build, '-j', '2', '--target',
                                   'engine_ai_match_metrics'], timeout=2100)
            binary = build / 'bin/engine_ai_match_metrics'
            core = build / 'libfootball_engine.so'
            require(binary.is_file() and core.is_file(), f'{label} binary missing')
            binaries[label] = {'binary': str(binary), 'binary_sha256': sha(binary),
                               'engine_sha256': sha(core)}
            linked = run(f'{label}-links', ['ldd', binary])
            match = re.search(r'libfootball_engine\.so => (\S+)', linked)
            require(match is not None and Path(match.group(1)).resolve() == core,
                    f'{label} linked a different engine')
        report['binaries'] = binaries
        def play(label: str, seed: int, frames: int, suffix: str = '') -> dict:
            build = builds[label]
            env = dict(os.environ, LD_LIBRARY_PATH=str(build))
            env['GFOOTBALL_DATA_DIR'] = str(ROOT / 'engine/data')
            value = run(f'{label}-{seed}-{frames}{suffix}',
                        [build / 'bin/engine_ai_match_metrics', seed, frames],
                        timeout=600 if label == 'sanitized' else 90, env=env)
            row = json.loads(value.strip().splitlines()[-1])
            check_row(row, seed, frames)
            return row
        current = [play('release', seed, FRAMES) for seed in SEEDS]
        for seed in (SEEDS[0], SEEDS[-1]):
            require(play('release', seed, FRAMES, '-repeat') == current[seed - SEEDS[0]],
                    f'Candidate seed {seed} is nondeterministic')
        release_probe = play('release', SEEDS[0], 3000, '-sanitizer-probe')
        sanitized_probe = play('sanitized', SEEDS[0], 3000, '-sanitizer-probe')
        require(release_probe == sanitized_probe,
                'Release and ASan/UBSan match metrics or final state hash differ')
        statistics, failures = assess(previous, current)
        report.update(statistics=statistics, baseline_rows=previous, candidate_rows=current,
                      sanitizer_probe={'release': release_probe, 'sanitized': sanitized_probe},
                      failures=failures)
        require(not failures, '; '.join(failures))
        require(source_manifest() == sources, 'Source changed during AI acceptance')
        for label, build in builds.items():
            require(sha(build / 'bin/engine_ai_match_metrics') ==
                    binaries[label]['binary_sha256'] and
                    sha(build / 'libfootball_engine.so') ==
                    binaries[label]['engine_sha256'],
                    f'{label} binaries changed during AI acceptance')
        require(report['assertions'] >= 400, 'Insufficient AI assertions')
        report['passed'] = True
    except BaseException as error:
        report['error'] = str(error)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        report['artifact_sha256'] = sha(output / 'report.json')
        print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
