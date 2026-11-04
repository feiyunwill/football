"""Frozen two-task, five-seed varied-start categorical PPO study."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from validate import ROOT, sha, source_fingerprint, runtime_identity
from validate_learning import paired_interval, successes, SEEDS, TEST_SEEDS

CONFIGS = {'sparse64': [], 'checkpoints64': ['--checkpoints']}
TASKS = {'varied_empty_goal': (.7, .5), 'varied_keeper': (.2, .1)}


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work, output = args.work_root.resolve(), args.output.resolve()
    if work == ROOT or ROOT in work.parents:
        parser.error('Use an external new work directory')
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    binary = args.build_root.resolve() / 'bin/native_ppo_train'
    core = args.build_root.resolve() / 'libfootball_engine.so'
    tools = [Path(__file__), Path(__file__).with_name('validate_learning.py'), Path(__file__).with_name('validate.py')]
    report = dict(passed=False, learning_passed=False, source_before=source_fingerprint(),
                  environment_before=runtime_identity(sys.executable), binary_sha256=sha(binary),
                  core_sha256=sha(core), tooling={p.name: sha(p) for p in tools}, commands=[], tasks={})
    protocol = dict(tasks=TASKS, goalkeeper=dict(varied_empty_goal=dict(position=[1,.6],lazy=True,outside_shot_region=True),varied_keeper=dict(position=[1,0],lazy=False,normal_engine_AI=True)), configs=CONFIGS, pilot_seed=7, pilot_updates=390,
                    final_training_seeds=SEEDS, final_updates=780, rollout=256, hidden=64,
                    cadence=10, episode_limit=256, epochs=4, minibatch=64,
                    validation_seed=77173, validation_episodes=32,
                    test_seeds=TEST_SEEDS, test_episodes_per_batch=50, test_horizon=256,
                    selection='argmax validation scoring success; insertion-order ties; frozen before held-out evaluation',
                    geometry='12 starts/partition; training x=.68+.05*i,y=-.10+.10*j; ball x=player x+.02; validation offsets(.0125,.0125),test offsets(.025,.025)',
                    success='controlled_score_delta>0 before horizon; failures/truncations remain failures',
                    gates='task mean and per-training-seed minima in tasks; each seed beats initial and random; crossed paired bootstrap lower95>0 against both',
                    statistics='10000 crossed training-seed/shared-evaluation-column bootstrap draws, RNG20261015',
                    scope='Two bounded one-agent shooting tasks; not11v11 football competence; no test-based retuning or sample replacement')
    write(output / 'protocol.json', protocol)
    report['protocol_sha256'] = sha(output / 'protocol.json')
    for path in tools:
        (output / path.name).write_bytes(path.read_bytes())
    env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
               GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))

    def run(name, task, config, seed, options):
        command = [str(binary), '--scenario', task, '--seed', str(seed), '--hidden', '64',
                   '--cadence', '10', '--episode-limit', '256', '--rollout', '256',
                   '--epochs', '4', '--minibatch', '64', '--no-initial-eval', *CONFIGS[config], *options]
        log = output / (name + '.log')
        started = time.monotonic()
        print(json.dumps(dict(running=name)), flush=True)
        with log.open('w') as stream:
            result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=3600)
        report['commands'].append(dict(name=name, argv=command, exit_code=result.returncode,
                                       seconds=time.monotonic()-started, log_sha256=sha(log)))
        if result.returncode:
            raise RuntimeError(f'{name} failed; raw log retained')
        data = json.loads(log.read_text())
        if not data['evaluation']['isolated'] or data['state_before_evaluation_sha256'] != data['state_sha256']:
            raise RuntimeError('Evaluation mutated learner')
        for row in data['iterations']:
            if not all(math.isfinite(value) for value in row.values() if isinstance(value, (int, float))):
                raise RuntimeError('Nonfinite training metrics')
        return data

    def train(task, config, seed, updates, name):
        checkpoint = work / (name + '.fppo')
        data = run(name, task, config, seed, ['--updates', str(updates), '--eval-episodes', '0', '--save', str(checkpoint)])
        assert data['total_transitions'] == updates * 256
        assert len(data['iterations']) == updates and all(r['parameter_delta'] > 0 for r in data['iterations'])
        assert data['state_sha256'] == sha(checkpoint)
        return checkpoint

    try:
        # Complete validation-only selection for BOTH tasks before opening test data.
        for task in TASKS:
            pilots = {}
            for config in CONFIGS:
                name = f'pilot-{task}-{config}'
                checkpoint = train(task, config, 7, 390, name)
                validation = run('validation-' + name, task, config, 7,
                                 ['--updates', '0', '--load', str(checkpoint), '--eval-partition', 'validation',
                                  '--eval-seed', '77173', '--eval-episodes', '32', '--eval-steps', '256'])
                pilots[config] = dict(success=float(np.mean(successes(validation['evaluation'], 'argmax'))),
                                      checkpoint_sha256=sha(checkpoint))
            selected = max(CONFIGS, key=lambda c: pilots[c]['success'])
            report['tasks'][task] = dict(pilots=pilots, selected=selected, final=[])
            write(output / ('selection-' + task + '.json'), report['tasks'][task])
            write(output / 'progress.json', report)
        for task, (mean_minimum, seed_minimum) in TASKS.items():
            record = report['tasks'][task]
            config = record['selected']
            final, initial, random = [], [], []
            for seed in SEEDS:
                checkpoint = train(task, config, seed, 780, f'final-train-{task}-{seed}')
                row = dict(seed=seed, checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint), batches=[])
                a, b, c, geometry = [], [], [], set()
                for batch, test_seed in enumerate(TEST_SEEDS):
                    options = ['--updates', '0', '--eval-partition', 'test', '--eval-seed', str(test_seed),
                               '--eval-episodes', '50', '--eval-steps', '256']
                    fresh = run(f'initial-{task}-{seed}-b{batch}', task, config, seed, options)
                    trained = run(f'test-{task}-{seed}-b{batch}', task, config, seed, options + ['--load', str(checkpoint)])
                    assert trained['state_sha256'] == sha(checkpoint)
                    reference = None
                    for evaluation in (fresh['evaluation'], trained['evaluation']):
                        for strategy in evaluation['strategies']:
                            episodes = strategy['episodes']
                            assert len(episodes) == 50
                            identities = [(e['engine_seed'], e['start_index'], e['start_x'], e['start_y']) for e in episodes]
                            if reference is None:
                                reference = identities
                            assert identities == reference
                            assert all(e['terminated'] ^ e['truncated'] for e in episodes)
                            for e in episodes:
                                i = e['start_index']
                                assert 0 <= i < 12
                                assert abs(e['start_x'] - (.68 + .05*(i % 4) + .025 + .02)) < 1e-5
                                assert abs(e['start_y'] - (-.10 + .10*(i // 4) + .025)) < 1e-5
                                geometry.add(i)
                    a += successes(trained['evaluation'], 'argmax')
                    b += successes(fresh['evaluation'], 'argmax')
                    c += successes(trained['evaluation'], 'uniform_random')
                    row['batches'].append(dict(test_seed=test_seed, trained_success=a[-50:],
                                               initial_success=b[-50:], random_success=c[-50:]))
                assert len(geometry) == 12 and len(a) == 200
                row.update(success=float(np.mean(a)), initial=float(np.mean(b)), random=float(np.mean(c)))
                final.append(a); initial.append(b); random.append(c)
                record['final'].append(row)
                write(output / 'progress.json', report)
            record['success_mean'] = float(np.mean(final))
            record['versus_initial'] = paired_interval(final, initial)
            record['versus_random'] = paired_interval(final, random)
            record['learning_passed'] = (record['success_mean'] >= mean_minimum
                and all(r['success'] >= seed_minimum and r['success'] > max(r['initial'], r['random']) for r in record['final'])
                and record['versus_initial']['low'] > 0 and record['versus_random']['low'] > 0)
            write(output / 'progress.json', report)
        report['learning_passed'] = all(t['learning_passed'] for t in report['tasks'].values())
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        report['source_after'] = source_fingerprint()
        report['environment_after'] = runtime_identity(sys.executable)
        if (report['source_before'] != report['source_after'] or report['environment_before'] != report['environment_after']
                or report['binary_sha256'] != sha(binary) or report['core_sha256'] != sha(core)
                or report['tooling'] != {p.name: sha(p) for p in tools}):
            report.update(passed=False, learning_passed=False, error='Source, environment, artifacts or tooling changed')
        write(output / 'report.json', report)
    print(json.dumps(dict(passed=report['passed'], learning_passed=report['learning_passed'], error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
