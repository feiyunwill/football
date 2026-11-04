"""Preregistered 2v1 cooperation study; validation pilots precede confirmation."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import shutil
import time

import numpy as np
from validate import ROOT, sha, source_fingerprint, runtime_identity
from validate_learning import paired_interval, successes, SEEDS, TEST_SEEDS

TEST_SEEDS=(1100001,1100002,1100003,1100004)

CONFIGS = {'sparse64': []}
TASKS = {'2v1': (.5, .3)}


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-pilots',type=Path,help='Reuse exact-source/binary validation pilots with immutable receipts')
    parser.add_argument('--stability',type=Path,help='Passing validation-only extra-seed stability evidence required for confirmation')
    parser.add_argument('--pilot-only',action='store_true',help='Register and run validation pilots without confirmation')
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.pilot_only and args.stability is None:
        parser.error('Confirmation requires --stability evidence')
    if args.pilot_only and args.reuse_pilots:
        parser.error('Reuse pilots only for confirmation')
    work, output = args.work_root.resolve(), args.output.resolve()
    if work == ROOT or ROOT in work.parents:
        parser.error('Use an external new work directory')
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    binary = args.build_root.resolve() / 'bin/native_ppo_train'
    core = args.build_root.resolve() / 'libfootball_engine.so'
    tools = [Path(__file__), Path(__file__).with_name('validate_learning.py'), Path(__file__).with_name('validate.py'),Path(__file__).with_name('validate_two_on_one_stability.py')]
    report = dict(passed=False, learning_passed=False, source_before=source_fingerprint(),
                  environment_before=runtime_identity(sys.executable), binary_sha256=sha(binary),
                  core_sha256=sha(core), tooling={p.name: sha(p) for p in tools}, commands=[], tasks={})
    protocol = dict(training_objective='raw goal/checkpoint rewards always preserved; first outfield teammate pass bonus2.0 once/episode plus actual positive score bonus2.0 after observed pass; historical pass marker -1/+1 in padding slot21, consistent training/bootstrap/eval; raw engine snapshots unchanged; schema3 tracking',revision='l; k confirmation rejected seed2026 success.66<=initial.66/random.68 despite joint.525; add actual joint-score bonus2; preselect sparse64 based on prior validation; uniform2048; holdout6/seeds1100001..1100004 unopened',observation='primary simple115 plus historical pass bit21 and current native sticky flags28..37; dimensions unchanged; train/bootstrap/eval consistent',fixed_teammate='native slot2 always builtin19; primary learner slot1 actions0..18, one-row PPO projection; both native slots snapshotted',curriculum='none; all training and evaluation are the actual full task; no goal masking or synthetic finishing practice',tasks=TASKS, roster='one fixed learning attacker, second native slot fixed builtinAI19 teammate, one engine-AI defender, two goalkeepers; AI logic fixed', configs=CONFIGS, pilot_seed=7, pilot_updates=2048,
                    final_training_seeds=SEEDS, final_updates=2048, rollout=256, hidden=64,
                    cadence=10, episode_limit=256, epochs=4, minibatch=64,
                    validation_seed=88173, validation_episodes=32,
                    test_seeds=TEST_SEEDS, test_episodes_per_batch=50, test_horizon=256,
                    selection='sampled-policy validation scoring success; insertion-order ties; frozen before held-out evaluation',
                    geometry='12 starts/partition; attacker x=.44+.06*i,y=-.16+.16*j; ball x=attacker x+.02; each partition adds .0125*partition to attacker x/y; AI teammate x+.12 opposite wing, defender x+.15/y*.25',
                    evaluation_partition='holdout',primary_policy='sample',pilot_only=args.pilot_only,argmax_reporting='Retained as secondary raw/batch results; no greedy-performance claim',
                    cooperation_gate='each final seed: at least10% confirmation episodes with completed_passes>0, and at least10% jointly completed pass and score; decision-boundary approximation, requests are not kicks',
                    pilot_gate='validation success>=.3, fraction episodes with completed_passes>0>=.1, jointly completed pass and score>=.1; otherwise preserve pilots and stop before confirmation',
                    success='controlled_score_delta>0 before horizon; failures/truncations remain failures',
                    gates='task mean and per-training-seed minima in tasks; each seed beats initial and random; crossed paired bootstrap lower95>0 against both',
                    statistics='10000 crossed training-seed/shared-evaluation-column bootstrap draws, RNG20261015',
                    scope='Bounded fixed-attacker 2v1 with AI teammate/defender/GKs; not joint control or11v11; no confirmation-based retuning')
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
        assert data['native_agents']==2 and data['fixed_teammate_builtin_ai'] and data['players']==1 and data['actions']==19
        assert data['total_transitions'] == updates * 256
        assert all(r['completed_episodes']==r['finishing_practice_episodes']+r['cooperative_episodes'] for r in data['iterations'])
        assert sum(r['finishing_practice_episodes'] for r in data['iterations'])==0 and sum(r['cooperative_episodes'] for r in data['iterations'])>0
        assert len(data['iterations']) == updates and all(r['parameter_delta'] > 0 for r in data['iterations'])
        assert data['state_sha256'] == sha(checkpoint)
        return checkpoint

    try:
        # Complete validation-only selection for BOTH tasks before opening test data.
        if args.reuse_pilots:
            origin=args.reuse_pilots.resolve()
            assert origin!=output and origin not in output.parents and output not in origin.parents
            old=json.loads((origin/'report.json').read_text())
            old_protocol=json.loads((origin/'protocol.json').read_text())
            assert old['passed'] and old_protocol['pilot_only']
            assert old['source_before']==old['source_after']==report['source_before']
            assert old['environment_before']==old['environment_after']==report['environment_before']
            assert old['binary_sha256']==report['binary_sha256'] and old['core_sha256']==report['core_sha256']
            assert sha(origin/'protocol.json')==old['protocol_sha256']
            assert {k:v for k,v in old_protocol.items() if k!='pilot_only'}=={k:v for k,v in json.loads(json.dumps(protocol)).items() if k!='pilot_only'}
            for name,digest in old['tooling'].items():assert sha(origin/name)==digest
            expected={f'{prefix}{task}-{config}' for task in TASKS for config in CONFIGS for prefix in ('pilot-','validation-pilot-')}
            assert {c['name'] for c in old['commands']}==expected and len(old['commands'])==len(expected)
            for command in old['commands']:
                name=command['name']+'.log'
                assert command['exit_code']==0 and sha(origin/name)==command['log_sha256']
                shutil.copyfile(origin/name,output/name)
            assert all(not t['final'] for t in old['tasks'].values())
            shutil.copytree(origin,output/'reused-pilots')
            report['reused_pilots']=dict(directory='reused-pilots',report_sha256=sha(origin/'report.json'),protocol_sha256=sha(origin/'protocol.json'))
            report['commands']=old['commands'];report['tasks']=old['tasks']
            for task,record in report['tasks'].items():write(output/('selection-'+task+'.json'),record)
        else:
            for task in TASKS:
                pilots = {}
                for config in CONFIGS:
                    name = f'pilot-{task}-{config}'
                    checkpoint = train(task, config, 7, 2048, name)
                    validation = run('validation-' + name, task, config, 7,
                                     ['--updates', '0', '--load', str(checkpoint), '--eval-partition', 'validation',
                                      '--eval-seed', '88173', '--eval-episodes', '32', '--eval-steps', '256'])
                    sample=next(row for row in validation['evaluation']['strategies'] if row['name']=='sample')['episodes']
                    pilots[config] = dict(cooperative_success=float(np.mean([e['completed_passes']>0 and e['controlled_score_delta']>0 for e in sample])),cooperation=float(np.mean([e['completed_passes']>0 for e in sample])),
                                          success=float(np.mean(successes(validation['evaluation'], 'sample'))),
                                          checkpoint_sha256=sha(checkpoint))
                eligible=[c for c in CONFIGS if pilots[c]['success']>=.3 and pilots[c]['cooperation']>=.1 and pilots[c]['cooperative_success']>=.1]
                selected = max(eligible or CONFIGS, key=lambda c: pilots[c]['success'])
                report['tasks'][task] = dict(pilots=pilots, selected=selected, final=[])
                write(output / ('selection-' + task + '.json'), report['tasks'][task])
                write(output / 'progress.json', report)
        if not args.pilot_only:
            stability=args.stability.resolve()
            extra=json.loads((stability/'report.json').read_text())
            assert extra['passed'] and extra['validation_stable']
            assert extra['source_before']==extra['source_after']==report['source_before']
            assert extra['environment_before']==extra['environment_after']==report['environment_before']
            assert extra['binary_sha256']==report['binary_sha256'] and extra['core_sha256']==report['core_sha256']
            assert extra['selected']==report['tasks']['2v1']['selected']
            assert [r['seed'] for r in extra['seeds']]==[19,101] and all(r['stable'] for r in extra['seeds'])
            assert sha(stability/'protocol.json')==extra['protocol_sha256']
            assert sha(stability/'validate_two_on_one_stability.py')==extra['runner_sha256']
            assert extra['runner_sha256']==sha(Path(__file__).with_name('validate_two_on_one_stability.py'))
            for command in extra['commands']:
                assert command['exit_code']==0 and sha(stability/(command['name']+'.log'))==command['sha256']
            shutil.copytree(stability,output/'validation-stability')
            report['validation_stability']=dict(directory='validation-stability',report_sha256=sha(stability/'report.json'),protocol_sha256=sha(stability/'protocol.json'))
            for record in report['tasks'].values():
                chosen=record['pilots'][record['selected']]
                if chosen['success']<.3 or chosen['cooperation']<.1 or chosen['cooperative_success']<.1:
                    raise RuntimeError('Validation prerequisite failed; confirmation remains unopened')
            for task, (mean_minimum, seed_minimum) in TASKS.items():
                record = report['tasks'][task]
                config = record['selected']
                final, initial, random = [], [], []
                for seed in SEEDS:
                    checkpoint = train(task, config, seed, 2048, f'final-train-{task}-{seed}')
                    row = dict(seed=seed, checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint), batches=[])
                    a, b, c, geometry, cooperation, cooperative_goals = [], [], [], set(), [], []
                    for batch, test_seed in enumerate(TEST_SEEDS):
                        options = ['--updates', '0', '--eval-partition', 'holdout', '--eval-seed', str(test_seed),
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
                                    assert abs(e['start_x'] - (.44 + .06*(i % 4) + .075 + .02)) < 1e-5
                                    assert abs(e['start_y'] - (-.16 + .16*(i // 4) + .075)) < 1e-5
                                    geometry.add(i)
                        sample=next(r for r in trained['evaluation']['strategies'] if r['name']=='sample')['episodes']
                        cooperation += [e['completed_passes']>0 for e in sample]
                        cooperative_goals += [e['completed_passes']>0 and e['controlled_score_delta']>0 for e in sample]
                        a += successes(trained['evaluation'], 'sample')
                        b += successes(fresh['evaluation'], 'sample')
                        c += successes(trained['evaluation'], 'uniform_random')
                        row['batches'].append(dict(test_seed=test_seed, argmax_success=successes(trained['evaluation'],'argmax'), trained_success=a[-50:],
                                                   initial_success=b[-50:], random_success=c[-50:]))
                    assert len(geometry) == 12 and len(a) == 200
                    row.update(cooperative_success=float(np.mean(cooperative_goals)),cooperation=float(np.mean(cooperation)), success=float(np.mean(a)), initial=float(np.mean(b)), random=float(np.mean(c)))
                    final.append(a); initial.append(b); random.append(c)
                    record['final'].append(row)
                    write(output / 'progress.json', report)
                record['success_mean'] = float(np.mean(final))
                record['versus_initial'] = paired_interval(final, initial)
                record['versus_random'] = paired_interval(final, random)
                record['learning_passed'] = (record['success_mean'] >= mean_minimum
                    and all(r['cooperative_success']>=.1 and r['cooperation']>=.1 and r['success'] >= seed_minimum and r['success'] > max(r['initial'], r['random']) for r in record['final'])
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
