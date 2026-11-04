"""Recompute registered learning decisions from immutable CLI logs/checkpoints."""
import argparse
import json
from pathlib import Path

import numpy as np
from validate import sha, source_fingerprint
from validate_learning import paired_interval, successes, SEEDS, TEST_SEEDS


def read(path):
    return json.loads(path.read_text())


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

    def load(name):
        data = read(root/(name+'.log'))
        assert data['evaluation']['isolated']
        assert data['state_sha256'] == data['state_before_evaluation_sha256']
        return data

    def train(name, task, config, seed, updates):
        data = load(name)
        assert data['scenario'] == task and data['seed'] == seed
        assert data['hidden'] == 64 and data['cadence'] == 10 and data['episode_limit'] == 256
        assert data['checkpoint_rewards'] == (config == 'checkpoints64')
        assert data['version'] == updates and data['start_version'] == 0
        assert data['total_transitions'] == updates*256
        assert len(data['iterations']) == updates
        assert all(r['version'] == i and r['transitions'] == 256 and r['parameter_delta'] > 0
                   for i, r in enumerate(data['iterations'], 1))
        assert '--load' not in commands[name]['argv']
        path = Path(commands[name]['argv'][commands[name]['argv'].index('--save')+1])
        assert sha(path) == data['state_sha256']
        return path, data

    results = {}
    for task, thresholds in protocol['tasks'].items():
        record = report['tasks'][task]
        pilots = {}
        for config in protocol['configs']:
            train(f'pilot-{task}-{config}', task, config, 7, 390)
            validation = load(f'validation-pilot-{task}-{config}')
            assert validation['evaluation_partition'] == 1
            pilots[config] = float(np.mean(successes(validation['evaluation'], 'argmax')))
            assert pilots[config] == record['pilots'][config]['success']
        selected = max(pilots, key=pilots.get)
        assert selected == record['selected'] == read(root/('selection-'+task+'.json'))['selected']
        assert [row['seed'] for row in record['final']] == list(SEEDS)
        all_final, all_initial, all_random = [], [], []
        for row in record['final']:
            seed = row['seed']; path, data = train(f'final-train-{task}-{seed}', task, selected, seed, 780)
            assert sha(path) == row['checkpoint_sha256']
            final, initial, random, geometries = [], [], [], set()
            for batch, test_seed in enumerate(TEST_SEEDS):
                fresh_name = f'initial-{task}-{seed}-b{batch}'
                trained_name = f'test-{task}-{seed}-b{batch}'
                fresh, trained = load(fresh_name), load(trained_name)
                assert '--load' not in commands[fresh_name]['argv']
                assert fresh['version'] == fresh['total_transitions'] == 0
                assert trained['version'] == 780 and trained['state_sha256'] == data['state_sha256']
                identity = None
                for run in (fresh, trained):
                    assert run['evaluation_seed'] == test_seed and run['evaluation_partition'] == 2
                    assert run['scenario'] == task and run['seed'] == seed
                    for strategy in run['evaluation']['strategies']:
                        rows = strategy['episodes']; assert len(rows) == 50
                        assert all(e['terminated'] ^ e['truncated'] for e in rows)
                        keys = [(e['engine_seed'], e['start_index'], e['start_x'], e['start_y']) for e in rows]
                        if identity is None: identity = keys
                        assert identity == keys
                        for e in rows:
                            i=e['start_index']; assert 0 <= i < 12
                            assert abs(e['start_x']-(.725+.05*(i%4))) < 1e-5
                            assert abs(e['start_y']-(-.075+.10*(i//4))) < 1e-5
                            geometries.add(i)
                a=successes(trained['evaluation'],'argmax')
                b=successes(fresh['evaluation'],'argmax')
                c=successes(trained['evaluation'],'uniform_random')
                assert row['batches'][batch] == dict(test_seed=test_seed,trained_success=a,initial_success=b,random_success=c)
                final+=a; initial+=b; random+=c
            assert len(final) == 200 and len(geometries) == 12
            assert float(np.mean(final)) == row['success']
            assert float(np.mean(initial)) == row['initial'] and float(np.mean(random)) == row['random']
            all_final.append(final); all_initial.append(initial); all_random.append(random)
        mean = float(np.mean(all_final))
        initial_ci = paired_interval(all_final, all_initial)
        random_ci = paired_interval(all_final, all_random)
        passed = (mean >= thresholds[0]
                  and all(r['success'] >= thresholds[1] and r['success'] > max(r['initial'],r['random']) for r in record['final'])
                  and initial_ci['low'] > 0 and random_ci['low'] > 0)
        assert mean == record['success_mean'] and initial_ci == record['versus_initial'] and random_ci == record['versus_random']
        assert passed == record['learning_passed']
        results[task] = dict(learning_passed=passed, success_mean=mean, versus_initial=initial_ci,
                             versus_random=random_ci, seeds=[{k:r[k] for k in ('seed','success','initial','random','checkpoint','checkpoint_sha256')} for r in record['final']])
    accepted = all(r['learning_passed'] for r in results.values())
    assert accepted == report['learning_passed']
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    result = dict(passed=True, learning_passed=accepted, tasks=results,
                  source_sha256=report['source_after']['sha256'], report_sha256=sha(root/'report.json'),
                  protocol_sha256=sha(root/'protocol.json'), raw_commands=len(commands),
                  auditor_sha256=sha(Path(__file__)),
                  scope='Both preregistered bounded shooting tasks; five independent training seeds/task,200 held-out episodes/seed. Not general11v11 competence.')
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,learning_passed=accepted,raw_commands=len(commands))))


if __name__ == '__main__':
    main()
