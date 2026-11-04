"""Audit every raw 2v1 learning and cooperation receipt."""
import argparse
import json
from pathlib import Path

import numpy as np
from validate import sha, source_fingerprint
from validate_learning import paired_interval, successes, SEEDS, TEST_SEEDS


def read(path):
    return json.loads(path.read_text())


def audit_prerequisites(root, report, protocol):
    reused=report.get('reused_pilots')
    if reused:
        origin=root/reused['directory'];old=read(origin/'report.json');old_protocol=read(origin/'protocol.json')
        assert sha(origin/'report.json')==reused['report_sha256'] and sha(origin/'protocol.json')==reused['protocol_sha256']
        assert old['passed'] and old_protocol['pilot_only'] and not protocol['pilot_only']
        assert old['source_before']==old['source_after']==report['source_before']
        assert old['binary_sha256']==report['binary_sha256'] and old['core_sha256']==report['core_sha256']
        assert {k:v for k,v in old_protocol.items() if k!='pilot_only'}=={k:v for k,v in protocol.items() if k!='pilot_only'}
        assert report['commands'][:len(old['commands'])]==old['commands']
        for name,digest in old['tooling'].items():assert sha(origin/name)==digest
    reference=report['validation_stability'];extra_root=root/reference['directory'];extra=read(extra_root/'report.json')
    assert sha(extra_root/'report.json')==reference['report_sha256']
    p=read(extra_root/'protocol.json');assert sha(extra_root/'protocol.json')==reference['protocol_sha256']==extra['protocol_sha256']
    assert extra['passed'] and extra['validation_stable'] and p['partition']=='validation'
    assert p['training_seeds']==[19,101] and p['evaluation_seeds']==[88174,88175]
    assert set(p['training_seeds']).isdisjoint(SEEDS)
    assert extra['source_before']==extra['source_after']==report['source_before']
    assert extra['binary_sha256']==report['binary_sha256'] and extra['core_sha256']==report['core_sha256']
    assert extra['environment_before']==extra['environment_after']==report['environment_before']
    assert sha(extra_root/'validate_two_on_one_stability.py')==extra['runner_sha256']==report['tooling']['validate_two_on_one_stability.py']
    assert extra['selected']==p['selected']==report['tasks']['2v1']['selected']
    commands={c['name']:c for c in extra['commands']};assert len(commands)==len(extra['commands'])==10
    for name,c in commands.items():assert c['exit_code']==0 and sha(extra_root/(name+'.log'))==c['sha256']
    def load(name):
        data=read(extra_root/(name+'.log'))
        assert data['scenario']=='2v1' and data['players']==1 and data['native_agents']==2
        assert data['actions']==19 and data['fixed_teammate_builtin_ai']
        assert data['evaluation']['isolated'] and data['state_sha256']==data['state_before_evaluation_sha256']
        return data
    assert [r['seed'] for r in extra['seeds']]==p['training_seeds']
    for row in extra['seeds']:
        seed=row['seed'];train=load(f'train-{seed}')
        assert train['seed']==seed and train['version']==2048 and train['total_transitions']==2048*256
        assert len(train['iterations'])==2048 and all(r['parameter_delta']>0 for r in train['iterations'])
        assert '--load' not in commands[f'train-{seed}']['argv']
        assert sha(Path(row['checkpoint']))==row['checkpoint_sha256']==train['state_sha256']
        final=[];initial=[];random=[];cooperation=[];joint=[]
        for batch,test_seed in enumerate(p['evaluation_seeds']):
            fresh=load(f'initial-{seed}-b{batch}');frozen=load(f'frozen-{seed}-b{batch}')
            assert fresh['version']==0 and '--load' not in commands[f'initial-{seed}-b{batch}']['argv']
            assert frozen['state_sha256']==train['state_sha256']
            identity=None
            for document in (fresh,frozen):
                assert document['seed']==seed and document['evaluation_partition']==1 and document['evaluation_seed']==test_seed
                for strategy in document['evaluation']['strategies']:
                    rows=strategy['episodes'];assert len(rows)==32 and all(e['terminated']^e['truncated'] for e in rows)
                    keys=[(e['engine_seed'],e['start_index'],e['start_x'],e['start_y']) for e in rows]
                    if identity is None:identity=keys
                    assert keys==identity
            rows=next(s['episodes'] for s in frozen['evaluation']['strategies'] if s['name']=='sample')
            final+=successes(frozen['evaluation'],'sample');initial+=successes(fresh['evaluation'],'sample');random+=successes(frozen['evaluation'],'uniform_random')
            cooperation += [e['completed_passes']>0 for e in rows]
            joint += [e['completed_passes']>0 and e['controlled_score_delta']>0 for e in rows]
        for key,values in [('success',final),('initial',initial),('random',random),('cooperation',cooperation),('cooperative_success',joint)]:
            assert row[key]==float(np.mean(values))
        assert row['stable'] and row['success']>=.5 and row['success']>max(row['initial'],row['random'])
        assert row['cooperation']>=.1 and row['cooperative_success']>=.1
    return len(commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); root = args.evidence.resolve()
    report = read(root/'report.json'); protocol = read(root/'protocol.json')
    assert report['passed'] and report['source_before'] == report['source_after'] == source_fingerprint()
    assert report['environment_before'] == report['environment_after']
    assert sha(root/'protocol.json') == report['protocol_sha256']
    assert sha(Path(__file__).with_name('validate_learning.py'))==report['tooling']['validate_learning.py']
    for name, digest in report['tooling'].items():
        assert sha(root/name) == digest
    commands = {r['name']: r for r in report['commands']}
    assert len(commands) == len(report['commands'])
    for name, command in commands.items():
        assert command['exit_code'] == 0 and sha(root/(name+'.log')) == command['log_sha256']
    stability_commands=audit_prerequisites(root,report,protocol)

    def load(name):
        data = read(root/(name+'.log'))
        assert data['evaluation']['isolated']
        assert data['state_sha256'] == data['state_before_evaluation_sha256']
        return data

    def train(name, task, config, seed, updates):
        data = load(name)
        assert data['scenario'] == task and data['seed'] == seed
        assert data['native_agents']==2 and data['fixed_teammate_builtin_ai'] and data['players']==1 and data['actions']==19
        assert data['hidden'] == 64 and data['cadence'] == 10 and data['episode_limit'] == 256
        assert data['checkpoint_rewards'] == (config == 'checkpoints64')
        assert data['version'] == updates and data['start_version'] == 0
        assert data['total_transitions'] == updates*256
        assert all(r['completed_episodes']==r['finishing_practice_episodes']+r['cooperative_episodes'] for r in data['iterations'])
        assert sum(r['finishing_practice_episodes'] for r in data['iterations'])==0 and sum(r['cooperative_episodes'] for r in data['iterations'])>0
        assert len(data['iterations']) == updates
        assert all(r['version'] == i and r['transitions'] == 256 and r['parameter_delta'] > 0
                   for i, r in enumerate(data['iterations'], 1))
        assert '--load' not in commands[name]['argv']
        path = Path(commands[name]['argv'][commands[name]['argv'].index('--save')+1])
        assert sha(path) == data['state_sha256']
        return path, data

    assert protocol['primary_policy']=='sample' and protocol['evaluation_partition']=='holdout'
    assert protocol['test_seeds']==[1100001,1100002,1100003,1100004]
    test_seeds=protocol['test_seeds']
    results = {}
    for task, thresholds in protocol['tasks'].items():
        record = report['tasks'][task]
        pilots = {}; cooperation_pilots={};joint_pilots={}
        for config in protocol['configs']:
            train(f'pilot-{task}-{config}', task, config, 7, protocol['pilot_updates'])
            validation = load(f'validation-pilot-{task}-{config}')
            assert validation['evaluation_partition'] == 1
            pilots[config] = float(np.mean(successes(validation['evaluation'], 'sample')))
            rows=next(r for r in validation['evaluation']['strategies'] if r['name']=='sample')['episodes']
            cooperation_pilots[config]=float(np.mean([e['completed_passes']>0 for e in rows]))
            joint_pilots[config]=float(np.mean([e['completed_passes']>0 and e['controlled_score_delta']>0 for e in rows]))
            assert joint_pilots[config]==record['pilots'][config]['cooperative_success']
            assert pilots[config] == record['pilots'][config]['success']
            assert cooperation_pilots[config]==record['pilots'][config]['cooperation']
        eligible=[c for c in pilots if pilots[c]>=.3 and cooperation_pilots[c]>=.1 and joint_pilots[c]>=.1]
        assert eligible
        selected = max(eligible,key=pilots.get)
        assert selected == record['selected'] == read(root/('selection-'+task+'.json'))['selected']
        assert [row['seed'] for row in record['final']] == list(SEEDS)
        all_final, all_initial, all_random = [], [], []
        for row in record['final']:
            seed = row['seed']; path, data = train(f'final-train-{task}-{seed}', task, selected, seed, 2048)
            assert sha(path) == row['checkpoint_sha256']
            final, initial, random, geometries, cooperation, cooperative_goals = [], [], [], set(), [], []
            for batch, test_seed in enumerate(test_seeds):
                fresh_name = f'initial-{task}-{seed}-b{batch}'
                trained_name = f'test-{task}-{seed}-b{batch}'
                fresh, trained = load(fresh_name), load(trained_name)
                assert '--load' not in commands[fresh_name]['argv']
                assert fresh['version'] == fresh['total_transitions'] == 0
                assert trained['version'] == 2048 and trained['state_sha256'] == data['state_sha256']
                identity = None
                for run in (fresh, trained):
                    assert run['evaluation_seed'] == test_seed and run['evaluation_partition'] == 6
                    assert run['scenario'] == task and run['seed'] == seed
                    for strategy in run['evaluation']['strategies']:
                        rows = strategy['episodes']; assert len(rows) == 50
                        assert all(e['terminated'] ^ e['truncated'] for e in rows)
                        keys = [(e['engine_seed'], e['start_index'], e['start_x'], e['start_y']) for e in rows]
                        if identity is None: identity = keys
                        assert identity == keys
                        for e in rows:
                            i=e['start_index']; assert 0 <= i < 12
                            assert abs(e['start_x']-(.535+.06*(i%4))) < 1e-5
                            assert abs(e['start_y']-(-.085+.16*(i//4))) < 1e-5
                            geometries.add(i)
                rows=next(r for r in trained['evaluation']['strategies'] if r['name']=='sample')['episodes']
                assert all(0<=e['completed_passes']<=e['pass_requests']<=e['steps'] for e in rows)
                cooperation += [e['completed_passes']>0 for e in rows]
                cooperative_goals += [e['completed_passes']>0 and e['controlled_score_delta']>0 for e in rows]
                a=successes(trained['evaluation'],'sample')
                b=successes(fresh['evaluation'],'sample')
                c=successes(trained['evaluation'],'uniform_random')
                assert row['batches'][batch] == dict(test_seed=test_seed,argmax_success=successes(trained['evaluation'],'argmax'),trained_success=a,initial_success=b,random_success=c)
                final+=a; initial+=b; random+=c
            assert len(final) == 200 and len(geometries) == 12
            assert float(np.mean(cooperative_goals)) == row['cooperative_success']
            assert float(np.mean(cooperation)) == row['cooperation']
            assert float(np.mean(final)) == row['success']
            assert float(np.mean(initial)) == row['initial'] and float(np.mean(random)) == row['random']
            all_final.append(final); all_initial.append(initial); all_random.append(random)
        mean = float(np.mean(all_final))
        initial_ci = paired_interval(all_final, all_initial)
        random_ci = paired_interval(all_final, all_random)
        passed = (mean >= thresholds[0]
                  and all(r['cooperative_success']>=.1 and r['cooperation']>=.1 and r['success'] >= thresholds[1] and r['success'] > max(r['initial'],r['random']) for r in record['final'])
                  and initial_ci['low'] > 0 and random_ci['low'] > 0)
        assert mean == record['success_mean'] and initial_ci == record['versus_initial'] and random_ci == record['versus_random']
        assert passed == record['learning_passed']
        results[task] = dict(learning_passed=passed,selected=selected, success_mean=mean, versus_initial=initial_ci,
                             versus_random=random_ci, seeds=[{k:r[k] for k in ('seed','success','initial','random','cooperation','cooperative_success','checkpoint','checkpoint_sha256')} for r in record['final']])
    accepted = all(r['learning_passed'] for r in results.values())
    assert accepted == report['learning_passed']
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    result = dict(passed=True, learning_passed=accepted, tasks=results,
                  source_sha256=report['source_after']['sha256'], report_sha256=sha(root/'report.json'),
                  protocol_sha256=sha(root/'protocol.json'), raw_commands=len(commands),stability_raw_commands=stability_commands,
                  auditor_sha256=sha(Path(__file__)),
                  primary_policy='sample',scope='Registered bounded2v1 with fixed learning attacker and AI teammate; five seeds,200 confirmation episodes/seed; explicit observed-pass gate. Not11v11.')
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,learning_passed=accepted,raw_commands=len(commands))))


if __name__ == '__main__':
    main()
