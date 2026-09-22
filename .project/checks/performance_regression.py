#!/usr/bin/env python3
"""Verify native long-match trajectories, step budgets and stable process RSS."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time

import match_benchmark as benchmark
from native_boundary import ROOT, require
from soak_analysis import assess

REFERENCE = 'native-soak-20260910-a/evidence/report.json'
REFERENCE_SHA = '0c49ddcb78c44208a2d5ea488d2fea7deee920ea890509706cd847b899f56f90'
SEEDS = (42, 43)
COMMAND_LAUNCHER = Path('/usr/bin/env')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def source_manifest(program):
    """Pin this gate's full declared input scope, including its own contract."""
    paths = set()
    for pattern in program.checks['performance_regression']['sources']:
        matches = [path for path in ROOT.glob(pattern) if path.is_file()]
        require(matches, f'Empty long-match source scope: {pattern}')
        paths.update(matches)
    result = {}
    for path in sorted(paths):
        require(path.resolve().is_relative_to(ROOT), 'Long-match source escaped checkout')
        result[path.relative_to(ROOT).as_posix()] = benchmark.file_hash(path)
    return result


def reference_runs():
    """Use prior successful native trajectories, retaining their RSS failures."""
    path = ROOT / '.project/optimization/benchmarks' / REFERENCE
    require(benchmark.file_hash(path) == REFERENCE_SHA, 'Long-match reference changed')
    report = json.loads(path.read_text())
    runs, files = {}, {str(path): REFERENCE_SHA}
    for row in report['runs']:
        seed = row['seed']
        require(seed in SEEDS and seed not in runs and row['returncode'] == 0,
                'Missing, repeated or failed reference process')
        log = path.parent / row['log']
        require(log.resolve().is_relative_to(path.parent), 'Reference log escaped its directory')
        require(benchmark.file_hash(log) == row['log_sha256'], 'Reference raw samples changed')
        values = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
        require(len(values) == 1, 'Ambiguous reference native report')
        benchmark.validate_run(values[0], seed, 1000, 36000, values[0]['cpu'])
        runs[seed] = values[0]
        files[str(log)] = row['log_sha256']
    require(set(runs) == set(SEEDS), 'Incomplete reference seed coverage')
    return runs, files


def interrupt_command(signum, _frame):
    """Unwind the active command so its owned process group is reaped."""
    raise SystemExit(128 + signum)


def run_command(argv, label, *, output, commands, environment, timeout=180):
    """Retain every command outcome, including launch failure and interruption."""
    argv = list(map(str, argv))
    log = output / (label + '.log')
    require(not log.exists(), 'Existing command log must be preserved')
    row = dict(argv=argv, log=log.name, started=time.time(), state='running', timed_out=False)
    commands.append(row)
    write_json(output / 'commands.json', commands)
    started, process = time.monotonic(), None
    try:
        with log.open('w') as stream:
            # Defer termination until the child handle has been assigned. The
            # enclosing exception path also covers delivery immediately after
            # unmasking; an interrupt between creation and wait cannot orphan it.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
            try:
                # 2026-09-13: a fork/exec child inherits the temporary mask.
                # GNU env restores just the signals newly blocked above before
                # execing the actual command in the same process and session.
                # process = subprocess.Popen(argv, cwd=ROOT, env=environment, stdout=stream,
                restore = {signal.SIGTERM, signal.SIGINT} - previous_mask
                options = ['--default-signal=' + ','.join(str(int(s)) for s in sorted(restore))] if restore else []
                launch_argv = [str(COMMAND_LAUNCHER), *options, '--', *argv]
                row['launch_argv'] = launch_argv
                process = subprocess.Popen(launch_argv, cwd=ROOT, env=environment, stdout=stream,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                row['pid'] = process.pid
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            process.wait(timeout=timeout)
    except BaseException as error:
        row.update(error_type=type(error).__name__, error=str(error),
                   timed_out=isinstance(error, subprocess.TimeoutExpired))
        if process is not None and process.poll() is None:
            # An unreaped leader owns this fresh session. No external group is
            # signalled; ESRCH means the group finished during the cleanup race.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
        raise
    finally:
        row.update(state='finished', seconds=time.monotonic() - started,
                   returncode=process.returncode if process else None,
                   log_sha256=benchmark.file_hash(log) if log.exists() else None)
        write_json(output / 'commands.json', commands)
    text = log.read_text()
    require(process.returncode == 0, f'Long-match command failed: {log}')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=Path('/tmp/football-optimization-native'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cpu', type=int)
    args = parser.parse_args()
    require(platform.system() == 'Linux', 'Native performance acceptance requires Linux')
    require(Path(__file__).resolve().parent == ROOT / '.project/checks',
            'Long-match acceptance must execute from the canonical checks directory')
    require(sys.flags.optimize == 0 and os.environ.get('PYTHONOPTIMIZE', '') in ('', '0'),
            'Performance acceptance requires Python assertions enabled')
    cpu = min(os.sched_getaffinity(0)) if args.cpu is None else args.cpu
    require(cpu in os.sched_getaffinity(0), 'Requested CPU is unavailable')
    # The parent quality runner owns its lock. Read the prerequisite evidence;
    # do not take a nested lock or grant completion from an independent preflight.
    sys.path.insert(0, str(ROOT / '.project'))
    from quality import Program
    program = Program(ROOT)
    for name in ('ecs_performance', 'memory_budget', 'architecture_regression'):
        require(program.check_state(name) == 'verified', f'Current prerequisite is incomplete: {name}')

    build = args.build.resolve()
    output = (args.output or ROOT / '.project/optimization/benchmarks' /
              f'performance-regression-{time.time_ns()}').resolve()
    require(output.is_relative_to(ROOT), 'Acceptance output must stay in this checkout')
    output.mkdir(parents=True, exist_ok=False)
    # 2026-09-13: retain the complete declared long-match scope.
    # original = benchmark.source_manifest()
    original = source_manifest(program)
    write_json(output / 'sources.json', original)
    references, reference_files = reference_runs()
    write_json(output / 'references.json', reference_files)
    # 2026-09-13: pin the signal-restoring launcher as part of execution identity.
    # commands, results, binaries = [], [], {}
    commands, results = [], []
    binaries = {'command_launcher': dict(path=str(COMMAND_LAUNCHER),
                                        sha256=benchmark.file_hash(COMMAND_LAUNCHER))}
    write_json(output / 'binaries.json', binaries)
    environment = dict(os.environ, LD_LIBRARY_PATH=str(build))
    for name in ('LD_PRELOAD', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT', 'GFOOTBALL_USE_PBR'):
        environment.pop(name, None)
    write_json(output / 'environment.json', {name: environment.get(name) for name in (
        'LD_LIBRARY_PATH', 'LD_PRELOAD', 'GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT',
        'GFOOTBALL_USE_PBR', 'GLIBC_TUNABLES', 'MALLOC_ARENA_MAX', 'PATH')})

    # 2026-09-13: extract owned-process execution for real timeout/signal tests.
    # def run(argv, label, timeout=180):
    #     argv = list(map(str, argv))
    #     log = output / (label + '.log')
    #     row = dict(argv=argv, log=log.name, started=time.time(), state='running')
    #     commands.append(row)
    #     write_json(output / 'commands.json', commands)
    #     started = time.monotonic()
    #     process = None
    #     try:
    #         with log.open('w') as stream:
    #             process = subprocess.Popen(argv, cwd=ROOT, env=environment, stdout=stream,
    #                                        stderr=subprocess.STDOUT, start_new_session=True)
    #             try:
    #                 process.wait(timeout=timeout)
    #             except subprocess.TimeoutExpired:
    #                 row['timed_out'] = True
    #                 # This unreaped leader owns the new session; kill only its group.
    #                 os.killpg(process.pid, signal.SIGKILL)
    #                 process.wait(timeout=10)
    #                 raise
    #             except BaseException:
    #                 if process.poll() is None:
    #                     os.killpg(process.pid, signal.SIGKILL)
    #                     process.wait(timeout=10)
    #                 raise
    #     finally:
    #         row.update(state='finished', seconds=time.monotonic() - started,
    #                    returncode=process.returncode if process else None,
    #                    log_sha256=benchmark.file_hash(log) if log.exists() else None)
    #         write_json(output / 'commands.json', commands)
    #     text = log.read_text()
    #     require(process.returncode == 0, f'Long-match command failed: {log}')
    #     return text
    #
    # def interrupted(signum, _frame):
    #     # Raising unwinds run(), reaps its owned child and retains its log.
    #     raise SystemExit(128 + signum)
    #
    def run(argv, label, timeout=180):
        return run_command(argv, label, output=output, commands=commands,
                           environment=environment, timeout=timeout)

    interrupted = interrupt_command

    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        run(['cmake', '-S', 'engine', '-B', build, '-DCMAKE_BUILD_TYPE=Release',
             '-DBUILD_PYTHON_BINDINGS=OFF', '-DFOOTBALL_ENABLE_SANITIZERS=OFF',
             f'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / "bin"}'], 'configure')
        run(['cmake', '--build', build, '-j', '1', '--target', 'engine_soak_benchmark'], 'build', 1800)
        compilation = json.loads((build / 'compile_commands.json').read_text())
        require(any(Path(item['file']).name == 'engine_soak_benchmark.cpp' for item in compilation),
                'Long-match entry is not registered in the build')
        for item in compilation:
            flags = shlex.split(item['command'])
            require(all(flag in flags for flag in ('-O3', '-DNDEBUG', '-std=c++23')) and
                    not any(flag.startswith('-fsanitize') or flag in ('-Ofast', '-ffast-math')
                            for flag in flags), 'Long-match build violates the Release contract')
        write_json(output / 'compile_commands.json', compilation)
        cache = (build / 'CMakeCache.txt').read_text()
        compiler = re.search(r'^CMAKE_CXX_COMPILER:[^=]+=(.+)$', cache, re.MULTILINE)
        require(compiler is not None, 'Compiler is missing from the build cache')
        version = run([compiler.group(1), '--version'], 'compiler')
        pointer = json.loads((ROOT / '.project/optimization/benchmarks/baseline.json').read_text())
        baseline_path = ROOT / pointer['source_artifact']
        require(benchmark.file_hash(baseline_path) == pointer['artifact_sha256'], 'Original baseline changed')
        baseline = json.loads(baseline_path.read_text())
        require(version == baseline['compiler_version'], 'Compiler differs from the original baseline')
        fixture = 'engine/tests/engine_match_benchmark.cpp'
        require(benchmark.file_hash(ROOT / fixture) == baseline['sources'][fixture],
                'Immutable short benchmark was modified')
        for name in ('libfootball_engine.so', 'bin/engine_soak_benchmark'):
            path = build / name
            binaries[name] = dict(path=str(path), sha256=benchmark.file_hash(path))
        write_json(output / 'binaries.json', binaries)
        linkage = run(['ldd', build / 'bin/engine_soak_benchmark'], 'linkage')
        require(str(build / 'libfootball_engine.so') in linkage and
                'libasan' not in linkage and 'libubsan' not in linkage,
                'Long-match entry loads the wrong engine or detector configuration')
        machine = benchmark.machine_identity(cpu)
        write_json(output / 'machine.json', machine)
        for seed in SEEDS:
            text = run([build / 'bin/engine_soak_benchmark', seed, cpu], f'seed-{seed}', 1200)
            rows = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
            require(len(rows) == 1, 'Missing or ambiguous native long-match result')
            result = rows[0]
            require(result.get('measurement_storage_prefaulted') is True and
                    result.get('workload') == 'headless-11v11-long-v1',
                    'Wrong long-match workload or sampling storage preparation')
            evaluated = assess(result, seed, cpu, reference=references[seed])
            results.append(dict(**evaluated, log=f'seed-{seed}.log',
                                log_sha256=benchmark.file_hash(output / f'seed-{seed}.log')))
            write_json(output / 'results.json', results)
        # 2026-09-13: the long-match contract and oracle tests are inputs too.
        # require(benchmark.source_manifest() == original, 'Sources changed during long-match verification')
        require(source_manifest(program) == original, 'Sources changed during long-match verification')
        for value in binaries.values():
            require(benchmark.file_hash(Path(value['path'])) == value['sha256'], 'Measured binary changed')
        for path, expected in reference_files.items():
            require(benchmark.file_hash(Path(path)) == expected, 'Reference changed during verification')
        failures = [f"seed {row['seed']}: {name}" for row in results for name in row['failures']]
        artifacts = {path.relative_to(output).as_posix(): dict(bytes=path.stat().st_size,
                     sha256=benchmark.file_hash(path)) for path in output.rglob('*') if path.is_file()}
        report = dict(passed=not failures, skipped=0, assertions=sum(row['assertions'] for row in results),
                      failures=failures, runs=results, sources=original, binaries=binaries,
                      references=reference_files, artifacts=artifacts, compiler_version=version,
                      machine=machine, scope='native headless logical p99 and sampled process RSS; '
                      '3600 simulated seconds per seed are not one wall-clock hour; '
                      'current paired CPU/p99 non-regression is a prerequisite; '
                      'rendering, WAN and physical-device feel have separate acceptance')
        artifact = output / 'report.json'
        write_json(artifact, report)
        print(json.dumps(dict(passed=report['passed'], skipped=0, assertions=report['assertions'],
                              artifact=str(artifact), artifact_sha256=benchmark.file_hash(artifact))))
        return 0 if report['passed'] else 1
    except BaseException as error:
        write_json(output / 'failure.json', dict(passed=False, error_type=type(error).__name__,
                                                error=str(error), completed_seeds=len(results)))
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == '__main__':
    raise SystemExit(main())
