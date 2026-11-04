#!/usr/bin/env python3
"""Bounded O1 baseline: current source/resources, isolated artifacts, raw samples.

Run after quality.py run. Commands execute serially; reports never imply learning
or parallel PPO speedups. Output must be new; failures remain on disk.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

from validate import ROOT, runtime_identity, sha, source_fingerprint
from quality import verify


def summary(values):
    ordered = sorted(values)
    def percentile(q):
        index = (len(ordered) - 1) * q
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
    return dict(count=len(values), min=min(values), max=max(values),
                p50=statistics.median(values), p95=percentile(.95), p99=percentile(.99))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--quality-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=8)
    parser.add_argument('--steps', type=int, default=256)
    args = parser.parse_args()
    if not 8 <= args.repeats <= 20 or not 32 <= args.steps <= 1024:
        parser.error('repeats=8..20; steps=32..1024')
    build, output = args.build_root.resolve(), args.output.resolve()
    if build == ROOT or ROOT in build.parents:
        parser.error('build-root must be outside the repository')
    output.mkdir(parents=True, exist_ok=False)
    stage = build / 'validation-stage'
    binary = build / 'bin/native_ppo_train'
    env = dict(os.environ, PYTHONPATH=str(stage) + os.pathsep + str(ROOT),
               GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
               GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    report = dict(schema=1, passed=False, source_before=source_fingerprint(),
                  environment=runtime_identity(sys.executable), platform=platform.platform(),
                  validator_sha256=sha(Path(__file__)), commands=[], workloads=[],
                  units='one joint transition, regardless of controlled player count',
                  limitations=['PPO subprocess timings include initialization, snapshots and shutdown',
                               'rollout percentiles summarize repeated whole-rollout costs, not individual steps',
                               'feedback policy is a deterministic heuristic, not PPO',
                               'RSS is measured separately by the worker resource benchmark'])
    def run(name, command, timeout=600):
        print(name, flush=True)
        log = output / (name + '.log')
        started = time.monotonic()
        with log.open('wb') as stream:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                report['commands'].append(dict(name=name, argv=command, timeout=True,
                    exit_code=process.returncode, seconds=time.monotonic()-started, log=log.name, sha256=sha(log)))
                raise
        row = dict(name=name, argv=command, exit_code=code,
                   seconds=time.monotonic()-started, log=log.name, sha256=sha(log))
        report['commands'].append(row)
        if code:
            raise RuntimeError(f'{name} failed; see {log}')
        return row
    try:
        report['quality'] = verify(args.quality_output / 'report.json', sys.executable)
        report['artifacts'] = {str(path): sha(path) for path in
            (binary, stage / 'gfootball_engine/_gameplayfootball.so', stage / 'gfootball_engine/libfootball_engine.so')}
        report['quality_report_sha256'] = sha(args.quality_output / 'report.json')
        # The existing probe pins its own CPU and excludes reset/warmup/digest.
        for repeat in range(args.repeats):
            workloads = [(p, c, f) for p in (1, 11) for c in (2, 10) for f in (False, True)]
            shift = repeat % len(workloads)
            for players, cadence, feedback in workloads[shift:] + workloads[:shift]:
                name = f'rollout-p{players}-c{cadence}-f{int(feedback)}-r{repeat}'
                path = output / (name + '.json')
                command = [sys.executable, str(Path(__file__).with_name('benchmark_candidate_rollout.py')),
                           '--players', str(players), '--cadence', str(cadence),
                           '--steps', str(args.steps), '--output', str(path)]
                if feedback:
                    command += ['--feedback']
                run(name, command)
                data = json.loads(path.read_text())
                if Path(data['loaded_module']) != stage / 'gfootball_engine/_gameplayfootball.so':
                    raise RuntimeError('Wrong staged module loaded')
                key = [players, cadence, feedback]
                rows = next((w for w in report['workloads'] if w['key'] == key), None)
                if rows is None:
                    rows = dict(key=key, samples=[])
                    report['workloads'].append(rows)
                if rows['samples'] and rows['samples'][0]['final_sha256'] != data['final_sha256']:
                    raise RuntimeError('Repeated rollout digest differs')
                rows['samples'].append(data)
        for workload in report['workloads']:
            workload['wall_ns'] = summary([r['elapsed_ns'] for r in workload['samples']])
            workload['cpu_ns'] = summary([r['cpu_ns'] for r in workload['samples']])
        run('phase-profile', [sys.executable, str(Path(__file__).with_name('validate_profile.py')),
            '--python', sys.executable, '--build-root', str(build), '--output', str(output / 'phases'),
            '--steps', str(args.steps), '--repeats', str(args.repeats)], 1200)
        # Actual PPO updates. Each fresh process has the same seed/configuration.
        report['ppo'] = []
        for repeat in range(args.repeats):
            command = [str(binary), '--scenario', 'empty_goal', '--seed', '42', '--updates', '8',
                       '--hidden', '16', '--rollout', '128', '--eval-episodes', '0']
            name = f'ppo-r{repeat}'
            run(name, command)
            data = json.loads((output / (name + '.log')).read_text())
            if not data['evaluation']['isolated'] or data['total_transitions'] != 1024:
                raise RuntimeError('PPO evaluation isolation or transition count failed')
            if report['ppo'] and report['ppo'][0]['state_sha256'] != data['state_sha256']:
                raise RuntimeError('Repeated PPO state differs')
            report['ppo'].append(data)
        report['ppo_wall_seconds'] = summary([row['wall_seconds'] for row in report['ppo']])
        run('workers', [sys.executable, str(Path(__file__).with_name('validate_workers.py')),
            '--python', sys.executable, '--build-root', str(build), '--output', str(output / 'workers'),
            '--steps', '128', '--repeats', '3'], 1200)
        report['passed'] = True
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        report['source_after'] = source_fingerprint()
        if report['source_before'] != report['source_after']:
            report.update(passed=False, error='Source/resources changed during baseline')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
