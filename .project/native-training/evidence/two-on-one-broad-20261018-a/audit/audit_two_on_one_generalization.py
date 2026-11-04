"""Recompute frozen-model broad-start assessment from immutable raw rows."""
import argparse
import json
from pathlib import Path

from validate import sha, source_fingerprint
from validate_learning import SEEDS, paired_interval


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); root = args.evidence.resolve()
    protocol = read(root / 'protocol.json'); report = read(root / 'report.json')
    assert report['passed'] and report['parity_passed']
    assert report['protocol_sha256'] == sha(root / 'protocol.json')
    assert protocol['source'] == report['source_before'] == report['source_after'] == source_fingerprint()
    assert protocol['training_seeds'] == list(SEEDS)
    assert protocol['gates'] == dict(mean_success_minimum=.75, every_seed_beats_initial_and_random=True,
        cooperation_minimum=.1, joint_pass_and_goal_minimum=.1, paired_ci95_low_minimum=0)
    assert protocol['cases_per_model'] == 200 and protocol['cases_per_group'] == 40
    for key, name in [('cases_sha256', 'cases.json'), ('case_text_sha256', 'cases.txt'), ('legacy_sha256', 'legacy.txt')]:
        assert sha(root / name) == protocol[key]
    for name, digest in protocol['tools'].items(): assert sha(root / name) == digest
    study = Path(protocol['study']); old = read(study / 'report.json')
    assert sha(study / 'report.json') == protocol['study_report_sha256']
    assert old['passed'] and old['learning_passed']
    assert sha(Path(__file__).with_name('validate_learning.py')) == old['tooling']['validate_learning.py']
    for row in old['tasks']['2v1']['final']:
        model = protocol['models'][str(row['seed'])]
        assert model['sha256'] == row['checkpoint_sha256'] == sha(Path(model['path']))
    cases = read(root / 'cases.json'); assert len(cases) == 200
    assert len({tuple(c['attacker'] + c['teammate'] + c['defender']) for c in cases}) == 200
    assert len({tuple(c['attacker']) for c in cases}) == 200
    assert len({c['engine_seed'] for c in cases}) == 200
    for g in range(5): assert sum(c['group'] == g for c in cases) == 40
    commands = {c['name']: c for c in report['commands']}
    modes = ('trained_sample', 'trained_argmax', 'initial_sample', 'uniform_random', 'builtin_ai')
    expected = {'compile', 'link', *('legacy-' + m for m in modes),
        *(f'{s}-{m}' for s in SEEDS for m in modes)}
    assert set(commands) == expected and len(commands) == len(report['commands']) == 32
    for name, command in commands.items():
        assert command['exit_code'] == 0 and sha(root / (name + '.log')) == command['sha256']
    def rows(name, count, trained):
        values = [json.loads(line) for line in (root / (name + '.log')).read_text().splitlines()]
        summary = values.pop(); assert len(values) == count == summary['episodes']
        assert summary['summary'] and summary['isolated']
        assert summary['version'] == (2048 if trained else 0)
        assert summary['transitions'] == (524288 if trained else 0)
        for i, e in enumerate(values):
            assert e['index'] == i and e['terminated'] ^ e['truncated']
            assert 0 <= e['completed_passes'] <= e['pass_requests'] <= e['steps'] <= 256
        return values
    for mode in modes:
        trained = mode != 'initial_sample'; name = 'sample' if mode in ('trained_sample', 'initial_sample') else mode.removeprefix('trained_')
        reference = read(study / ('test-2v1-42-b0.log' if trained else 'initial-2v1-42-b0.log'))
        expected_rows = next(s['episodes'] for s in reference['evaluation']['strategies'] if s['name'] == name)
        for actual, reference_row in zip(rows('legacy-' + mode, 50, trained), expected_rows):
            assert all(actual[k] == value for k, value in reference_row.items() if k != 'start_index')
    all_scores = {m: [] for m in modes}; recomputed = []; baseline = {}
    for seed, recorded in zip(SEEDS, report['seeds']):
        assert recorded['seed'] == seed
        data = {m: rows(f'{seed}-{m}', 200, m != 'initial_sample') for m in modes}
        for mode, values in data.items():
            for e, c in zip(values, cases):
                assert e['engine_seed'] == c['engine_seed'] and e['group'] == c['group']
                assert abs(e['start_x'] - c['attacker'][0] - .02) < 1e-6
                assert abs(e['start_y'] - c['attacker'][1]) < 1e-6
            if mode in ('uniform_random', 'builtin_ai'):
                if mode in baseline: assert values == baseline[mode]
                baseline[mode] = values
            all_scores[mode].append([int(e['controlled_score_delta'] > 0) for e in values])
        fractions = {m: sum(all_scores[m][-1]) / 200 for m in modes}
        primary = data['trained_sample']
        calculated = dict(seed=seed, success=fractions['trained_sample'], initial=fractions['initial_sample'],
            random=fractions['uniform_random'], builtin_ai=fractions['builtin_ai'], argmax=fractions['trained_argmax'],
            cooperation=sum(e['completed_passes'] > 0 for e in primary) / 200,
            cooperative_success=sum(e['completed_passes'] > 0 and e['controlled_score_delta'] > 0 for e in primary) / 200,
            groups={protocol['groups'][g]: {m: sum(e['controlled_score_delta'] > 0 for e in values if e['group'] == g) / 40
                for m, values in data.items()} for g in range(5)})
        assert calculated == recorded
        recomputed.append(calculated)
    assert len(report['seeds']) == len(recomputed) == 5
    mean = sum(r['success'] for r in recomputed) / 5
    initial_ci = paired_interval(all_scores['trained_sample'], all_scores['initial_sample'])
    random_ci = paired_interval(all_scores['trained_sample'], all_scores['uniform_random'])
    assert mean == report['success_mean'] and initial_ci == report['versus_initial'] and random_ci == report['versus_random']
    passed = (mean >= .75 and all(r['success'] > max(r['initial'], r['random']) and r['cooperation'] >= .1
        and r['cooperative_success'] >= .1 for r in recomputed) and initial_ci['low'] > 0 and random_ci['low'] > 0)
    assert passed == report['generalization_passed']
    groups = {g: {m: sum(r['groups'][g][m] for r in recomputed) / 5 for m in modes} for g in protocol['groups']}
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    result = dict(passed=True, generalization_passed=passed, source_sha256=protocol['source']['sha256'],
        report_sha256=sha(root / 'report.json'), protocol_sha256=sha(root / 'protocol.json'),
        raw_commands=32, legacy_parity_episodes=250, primary_episodes=1000, all_new_strategy_episodes=5000,
        seeds=recomputed, success_mean=mean, versus_initial=initial_ci, versus_random=random_ci, groups=groups,
        auditor_sha256=sha(Path(__file__)), scope=protocol['scope'], reuse=protocol['reuse'])
    (output / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=True, generalization_passed=passed, success_mean=mean)))


if __name__ == '__main__':
    main()
