#!/usr/bin/env python3
"""Pre-registered bounded empty-goal learning study, independent held-out eval.

One pilot seed, three configurations, five final training seeds. Train state
never sees validation/test seeds. Raw CLI JSON and logs are retained on failure.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np
from validate import ROOT, sha, source_fingerprint, runtime_identity


CONFIGS = {'sparse16': ['--hidden', '16'], 'sparse64': ['--hidden', '64'],
           'checkpoints64': ['--hidden', '64', '--checkpoints']}
SEEDS = (42, 123, 2026, 31415, 271828)
TEST_SEEDS = (600001, 600002, 600003, 600004)


def successes(evaluation, name):
    row = next(s for s in evaluation['strategies'] if s['name'] == name)
    return [int(e['controlled_score_delta'] > 0) for e in row['episodes']]


def paired_interval(final, baseline, repeats=10000):
    """Resample training seeds and matched scenario indices, preserving pairing.

Scenario indices are shared across training runs, so use the same resampled
episode columns for all sampled training seeds (crossed bootstrap).
"""
    differences = np.asarray(final, dtype=float) - np.asarray(baseline, dtype=float)
    if differences.ndim != 2 or differences.shape[0] < 2:
        raise ValueError('Need independent training seeds and matched episodes')
    rng = np.random.default_rng(20261015)
    values = []
    for _ in range(repeats):
        rows = rng.integers(differences.shape[0], size=differences.shape[0])
        columns = rng.integers(differences.shape[1], size=differences.shape[1])
        values.append(differences[np.ix_(rows, columns)].mean())
    return dict(mean=float(differences.mean()),
                low=float(np.quantile(values, .025)), high=float(np.quantile(values, .975)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build, work, output = (p.resolve() for p in (args.build_root, args.work_root, args.output))
    if work == ROOT or ROOT in work.parents:
        parser.error('Checkpoint work-root must be outside the repository')
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    binary = build / 'bin/native_ppo_train'
    report = dict(schema=1, passed=False, outcome='incomplete', commands=[],
                  source_before=source_fingerprint(), environment=runtime_identity(sys.executable),
                  validator_sha256=sha(Path(__file__)), binary_sha256=sha(binary),
                  protocol=dict(configurations=CONFIGS, training_seeds=SEEDS, tuning_seed=77173,
                    test_seeds=TEST_SEEDS, updates=390, rollout=256, transitions_per_run=99840,
                    evaluation_episodes_per_batch=50, evaluation_horizon=256,
                    selection='pilot argmax scoring success, insertion order breaks ties',
                    budget='three pilots plus five independent training seeds; no adaptive sweep'),
                  pilots={}, final=[])
    (output / 'protocol.json').write_text(json.dumps(report['protocol'], indent=2) + '\n')
    env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
               GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))

    def run(name, config, seed, options, timeout=1800):
        print(name, flush=True)
        command = [str(binary), '--scenario', 'empty_goal', '--seed', str(seed),
                   '--rollout', '256', '--episode-limit', '256', '--epochs', '4',
                   '--minibatch', '64'] + CONFIGS[config] + options
        log = output / (name + '.log')
        start = time.monotonic()
        with log.open('wb') as stream:
            process = subprocess.Popen(command, env=env, cwd=ROOT, stdout=stream,
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
                    exit_code=process.returncode, seconds=time.monotonic()-start, sha256=sha(log)))
                raise
        report['commands'].append(dict(name=name, argv=command, exit_code=code,
                                       seconds=time.monotonic()-start, sha256=sha(log)))
        if code:
            raise RuntimeError('Experiment failed: ' + name)
        data = json.loads(log.read_text())
        if not data['evaluation']['isolated'] or data['state_before_evaluation_sha256'] != data['state_sha256']:
            raise RuntimeError('Evaluation mutated learner: ' + name)
        (output / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')
        return data

    def train(config, seed):
        checkpoint = work / f'{config}-{seed}.bin'
        data = run(f'train-{config}-{seed}', config, seed,
                   ['--updates', '390', '--eval-episodes', '0', '--save', str(checkpoint)])
        if data['total_transitions'] != 99840 or any(r['parameter_delta'] <= 0 for r in data['iterations']):
            raise RuntimeError('Missing real PPO updates')
        return checkpoint, data

    try:
        checkpoints = {}
        for config in CONFIGS:
            checkpoint, training = train(config, 7)
            checkpoints[config] = checkpoint
            tuning = run('tune-' + config, config, 7,
                         ['--updates', '0', '--load', str(checkpoint), '--no-initial-eval',
                          '--eval-seed', '77173', '--eval-episodes', '32', '--eval-steps', '256'])
            report['pilots'][config] = dict(success=float(np.mean(successes(tuning['evaluation'], 'argmax'))),
                seconds=training['wall_seconds'], checkpoint_sha256=sha(checkpoint))
            (output / 'progress.json').write_text(json.dumps(report, indent=2) + '\n')
        selected = max(CONFIGS, key=lambda c: report['pilots'][c]['success'])
        report['selected'] = selected
        # Selection is frozen before the first held-out evaluation.
        (output / 'selection.json').write_text(json.dumps(dict(selected=selected, pilots=report['pilots']), indent=2))
        final, initial, random = [], [], []
        for seed in SEEDS:
            checkpoint = train(selected, seed)[0]
            row = dict(seed=seed, checkpoint_sha256=sha(checkpoint), batches=[])
            model_success, initial_success, random_success = [], [], []
            for batch, test_seed in enumerate(TEST_SEEDS):
                common = ['--updates', '0', '--no-initial-eval', '--eval-seed', str(test_seed),
                          '--eval-episodes', '50', '--eval-steps', '256']
                fresh = run(f'initial-{seed}-b{batch}', selected, seed, common)
                trained = run(f'final-{seed}-b{batch}', selected, seed, common + ['--load', str(checkpoint)])
                if trained['state_sha256'] != sha(checkpoint):
                    raise RuntimeError('Frozen evaluation did not retain checkpoint bytes')
                for strategy in trained['evaluation']['strategies']:
                    seeds = [e['engine_seed'] for e in strategy['episodes']]
                    expected = [e['engine_seed'] for e in fresh['evaluation']['strategies'][0]['episodes']]
                    if len(seeds) != 50 or seeds != expected:
                        raise RuntimeError('Unmatched evaluation episodes')
                    if any(not (e['terminated'] ^ e['truncated']) for e in strategy['episodes']):
                        raise RuntimeError('Evaluation omitted terminal/horizon outcome')
                model_success.extend(successes(trained['evaluation'], 'argmax'))
                initial_success.extend(successes(fresh['evaluation'], 'argmax'))
                random_success.extend(successes(trained['evaluation'], 'uniform_random'))
                row['batches'].append(dict(initial=fresh['evaluation'], final=trained['evaluation']))
            final.append(model_success); initial.append(initial_success); random.append(random_success)
            row['argmax_success'] = float(np.mean(model_success))
            report['final'].append(row)
            (output / 'progress.json').write_text(json.dumps(report, indent=2) + '\n')
        report['success_mean'] = float(np.mean(final))
        report['versus_initial'] = paired_interval(final, initial)
        report['versus_random'] = paired_interval(final, random)
        report['learning_passed'] = (report['success_mean'] >= .9 and
            min(r['argmax_success'] for r in report['final']) >= .8 and
            report['versus_initial']['low'] > 0 and report['versus_random']['low'] > 0)
        report['outcome'] = 'learning_verified' if report['learning_passed'] else 'budget_exhausted_no_learning_claim'
        report['passed'] = True  # Protocol execution, separate from learning_passed.
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        report['source_after'] = source_fingerprint()
        if report['source_before'] != report['source_after']:
            report.update(passed=False, outcome='invalidated', error='Source/resources changed during experiment')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], outcome=report['outcome'], error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
