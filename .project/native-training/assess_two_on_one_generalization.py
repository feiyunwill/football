"""Register and assess accepted frozen models on 200 new bounded geometries.

No training or production-source changes. Legacy episode parity is required
before opening the new cases. A failed diagnostic never replaces prior acceptance.
"""
import argparse
import json
import math
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import sys
import time

import quality
from validate import ROOT, sha, source_fingerprint, runtime_identity
from validate_learning import SEEDS, paired_interval

GROUPS = ('interpolation', 'deeper_attack', 'wide_attack', 'close_defender', 'varied_support')
MODES = {'trained_sample': ('sample', True), 'trained_argmax': ('argmax', True),
         'initial_sample': ('sample', False), 'uniform_random': ('uniform_random', True),
         'builtin_ai': ('builtin_ai', True)}
MASK = (1 << 64) - 1


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def prepare(args):
    work, output = args.work.resolve(), args.output.resolve()
    assert work != ROOT and ROOT not in work.parents and work != output
    assert ROOT not in output.parents and output != ROOT
    quality.verify(args.quality)
    study = args.study.resolve()
    accepted = read(study / 'report.json')
    assert accepted['passed'] and accepted['learning_passed']
    assert accepted['source_before'] == accepted['source_after'] == source_fingerprint()
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    models = work / 'frozen-models'; models.mkdir()
    deliveries = read(args.models / 'report.json')
    assert deliveries['passed'] and deliveries['frozen_episodes_verified'] == 1000
    assert deliveries['source_before'] == deliveries['source_after'] == source_fingerprint()
    frozen = {}
    for row in deliveries['models']:
        original = Path(row['path'])
        assert row['seed'] in SEEDS and sha(original) == row['sha256']
        target = models / original.name; shutil.copyfile(original, target)
        assert sha(target) == row['sha256']
        frozen[str(row['seed'])] = dict(path=str(target), sha256=sha(target))
    assert set(map(int, frozen)) == set(SEEDS)
    forbidden = set()
    evidence = ROOT / '.project/native-training/evidence'
    historical = [study, *evidence.glob('two-on-one-confirmation-rejected-*')]
    for directory in historical:
        for path in directory.glob('test-2v1-*.log'):
            data = read(path)
            for strategy in data['evaluation']['strategies']:
                forbidden.update(e['engine_seed'] for e in strategy['episodes'])
    rng = random.Random(20261019019)
    cases = []; geometries = set(); used = set(forbidden)
    for group in range(5):
        for _ in range(40):
            ax = rng.uniform(.44, .68); ay = rng.uniform(-.22, .22)
            gap = rng.uniform(.12, .20)
            if group == 1: ax = rng.uniform(.28, .44)
            if group == 2: ay = rng.choice((-1, 1)) * rng.uniform(.22, .34)
            if group == 3: gap = rng.uniform(.06, .12)
            tx = ax + rng.uniform(.08, .18)
            ty = (-1 if ay > 0 else 1) * rng.uniform(.12, .26)
            if group == 4:
                tx = ax + rng.uniform(.025, .21)
                ty = rng.uniform(-.32, .32)
                if abs(ty - ay) < .08: ty = -.24 if ay >= 0 else .24
            dx = ax + gap; dy = ay * .25 + rng.uniform(-.06, .06)
            coords = [round(v, 6) for v in (ax, ay, tx, ty, dx, dy)]
            ax, ay, tx, ty, dx, dy = coords
            assert tuple(coords) not in geometries
            geometries.add(tuple(coords))
            # Exclude all previous finite training/validation/confirmation starts.
            assert all(abs(ax - (.44 + .06 * i + .0125 * p)) > 1e-5
                       or abs(ay - (-.16 + .16 * j + .0125 * p)) > 1e-5
                       for p in range(7) for i in range(4) for j in range(3))
            engine_seed = rng.randrange(1, 2000000001)
            while engine_seed in used: engine_seed = rng.randrange(1, 2000000001)
            used.add(engine_seed)
            index = len(cases)
            cases.append(dict(index=index, group=group, group_name=GROUPS[group],
                engine_seed=engine_seed, action_seed=(1220401 ^ 0x13198A2E03707344 ^ (index * 0x9E3779B97F4A7C15)) & MASK,
                attacker=[ax, ay], teammate=[tx, ty], defender=[dx, dy]))
    write(output / 'cases.json', cases)
    with (output / 'cases.txt').open('w') as stream:
        for c in cases:
            stream.write(' '.join(map(str, [c['index'], c['group'], 0, c['engine_seed'], c['action_seed'],
                *c['attacker'], *c['teammate'], *c['defender']])) + '\n')
    legacy = read(study / 'test-2v1-42-b0.log')['evaluation']['strategies'][0]['episodes']
    with (output / 'legacy.txt').open('w') as stream:
        for i, c in enumerate(legacy):
            action = (1100001 ^ 0x13198A2E03707344 ^ (i * 0x9E3779B97F4A7C15)) & MASK
            stream.write(f"{i} 0 1 {c['engine_seed']} {action} 0 0 0 0 0 0\n")
    tools = [Path(__file__), Path(__file__).with_name('evaluate_two_on_one_generalization.cpp')]
    for tool in tools: shutil.copyfile(tool, output / tool.name)
    build = args.build.resolve()
    protocol = dict(schema=1, task='Frozen accepted one-player+fixed-AI 2v1 generalization assessment',
        source=source_fingerprint(), environment=runtime_identity(sys.executable),
        study=str(study), study_report_sha256=sha(study / 'report.json'),
        accepted_models_report_sha256=sha(args.models / 'report.json'), models=frozen,
        build=str(build), work=str(work), quality=str(args.quality.resolve()),
        binary_sha256=sha(build / 'bin/native_ppo_train'), core_sha256=sha(build / 'libfootball_engine.so'),
        link_sha256=sha(build / 'CMakeFiles/native_ppo_train.dir/link.txt'),
        flags_sha256=sha(build / 'CMakeFiles/native_ppo_train.dir/flags.make'),
        tools={t.name: sha(t) for t in tools}, cases_sha256=sha(output / 'cases.json'),
        case_text_sha256=sha(output / 'cases.txt'), legacy_sha256=sha(output / 'legacy.txt'),
        training_seeds=list(SEEDS), groups=list(GROUPS), cases_per_group=40, cases_per_model=200,
        total_primary_episodes=1000, strategies=list(MODES), primary_policy='trained_sample',
        cadence=10, episode_limit=256, reward='Raw native rewards/score only; no shaped evaluation reward',
        gates=dict(mean_success_minimum=.75, every_seed_beats_initial_and_random=True,
            cooperation_minimum=.1, joint_pass_and_goal_minimum=.1, paired_ci95_low_minimum=0),
        statistics='10000 crossed paired seed/scenario bootstrap draws, RNG20261015',
        parity='All50 legacy episodes for all5 modes; exact metrics and coordinates against accepted CLI logs',
        scope='Five bounded geometry families,200 distinct geometries; selected models frozen. Not arbitrary starts or11v11.',
        seed_exclusion='No previously recorded confirmation engine seeds; no exhaustive claim about unlogged training episode seeds.',
        reuse='If used to design future training, these cases become diagnostic data; future confirmation must be fresh.')
    write(output / 'protocol.json', protocol)
    print(json.dumps(dict(prepared=True, output=str(output), protocol_sha256=sha(output / 'protocol.json'))), flush=True)


def run(args):
    output = args.output.resolve(); protocol = read(output / 'protocol.json')
    assert not (output / 'report.json').exists()
    work = Path(protocol['work']); build = Path(protocol['build'])
    tools = [Path(__file__), Path(__file__).with_name('evaluate_two_on_one_generalization.cpp')]
    def unchanged():
        assert protocol['source'] == source_fingerprint()
        assert protocol['environment'] == runtime_identity(sys.executable)
        assert sha(build / 'bin/native_ppo_train') == protocol['binary_sha256']
        assert sha(build / 'libfootball_engine.so') == protocol['core_sha256']
        assert sha(build / 'CMakeFiles/native_ppo_train.dir/link.txt') == protocol['link_sha256']
        assert sha(build / 'CMakeFiles/native_ppo_train.dir/flags.make') == protocol['flags_sha256']
        assert all(sha(t) == protocol['tools'][t.name] == sha(output / t.name) for t in tools)
        assert sha(output / 'cases.json') == protocol['cases_sha256']
        assert sha(output / 'cases.txt') == protocol['case_text_sha256']
        assert sha(output / 'legacy.txt') == protocol['legacy_sha256']
        assert all(sha(Path(m['path'])) == m['sha256'] for m in protocol['models'].values())
    unchanged()
    report = dict(passed=False, generalization_passed=False, protocol_sha256=sha(output / 'protocol.json'),
        source_before=source_fingerprint(), commands=[], seeds=[], parity_passed=False)
    env = dict(os.environ, GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
        GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'), LD_LIBRARY_PATH=str(build))
    def command(name, argv):
        print(name, flush=True); start = time.monotonic()
        with (output / (name + '.log')).open('w') as stream:
            result = subprocess.run(list(map(str, argv)), cwd=build, env=env, stdout=stream,
                stderr=subprocess.STDOUT, timeout=1800)
        report['commands'].append(dict(name=name, argv=list(map(str, argv)), exit_code=result.returncode,
            seconds=time.monotonic() - start, sha256=sha(output / (name + '.log'))))
        if result.returncode: raise RuntimeError(name + ' failed; raw log retained')
    binary = work / 'evaluate'; obj = work / 'evaluate.o'
    def evaluate(name, seed, mode, trained, cases):
        checkpoint = protocol['models'][str(seed)]['path'] if trained else '-'
        command(name, [binary, seed, checkpoint, mode, cases])
        lines = [json.loads(x) for x in (output / (name + '.log')).read_text().splitlines()]
        summary = lines.pop()
        assert summary['summary'] and summary['isolated'] and summary['episodes'] == len(lines)
        assert summary['version'] == (2048 if trained else 0)
        assert summary['transitions'] == (524288 if trained else 0)
        assert all(e['terminated'] ^ e['truncated'] for e in lines)
        assert all(math.isfinite(e['reward']) and math.isfinite(e['controlled_score_delta']) for e in lines)
        assert all(e['index'] == i and e['completed_passes'] <= e['pass_requests'] <= e['steps'] <= 256
            for i, e in enumerate(lines))
        return lines
    try:
        flags = {}
        for line in (build / 'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:
                k, v = line.split(' = ', 1); flags[k] = shlex.split(v)
        link = shlex.split((build / 'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        command('compile', [link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'],
            '-c', tools[1], '-o', obj])
        index = [i for i, x in enumerate(link) if x.endswith('native_ppo_train.cpp.o')]
        assert len(index) == 1
        link[index[0]] = str(obj); link[link.index('-o') + 1] = str(binary)
        command('link', link)
        report['evaluator_sha256'] = sha(binary)
        study = Path(protocol['study'])
        for label, (mode, trained) in MODES.items():
            rows = evaluate('legacy-' + label, 42, mode, trained, output / 'legacy.txt')
            origin = read(study / ('test-2v1-42-b0.log' if trained else 'initial-2v1-42-b0.log'))
            expected = next(s['episodes'] for s in origin['evaluation']['strategies'] if s['name'] == mode)
            assert len(rows) == len(expected) == 50
            for a, b in zip(rows, expected):
                assert all(a[k] == v for k, v in b.items() if k != 'start_index'), (label, a['index'])
        report['parity_passed'] = True
        write(output / 'progress.json', report)
        cases = read(output / 'cases.json'); final = []; initial = []; random_baseline = []
        for seed in SEEDS:
            data = {}
            for label, (mode, trained) in MODES.items():
                rows = evaluate(f'{seed}-{label}', seed, mode, trained, output / 'cases.txt')
                assert len(rows) == 200
                for row, case in zip(rows, cases):
                    assert row['engine_seed'] == case['engine_seed'] and row['group'] == case['group']
                    assert abs(row['start_x'] - (case['attacker'][0] + .02)) < 1e-6
                    assert abs(row['start_y'] - case['attacker'][1]) < 1e-6
                data[label] = rows
            scores = {k: [int(e['controlled_score_delta'] > 0) for e in rows] for k, rows in data.items()}
            primary = data['trained_sample']
            row = dict(seed=seed, success=sum(scores['trained_sample']) / 200,
                initial=sum(scores['initial_sample']) / 200, random=sum(scores['uniform_random']) / 200,
                builtin_ai=sum(scores['builtin_ai']) / 200, argmax=sum(scores['trained_argmax']) / 200,
                cooperation=sum(e['completed_passes'] > 0 for e in primary) / 200,
                cooperative_success=sum(e['completed_passes'] > 0 and e['controlled_score_delta'] > 0 for e in primary) / 200,
                groups={GROUPS[g]: {label: sum(e['controlled_score_delta'] > 0 for e in rows if e['group'] == g) / 40
                    for label, rows in data.items()} for g in range(5)})
            report['seeds'].append(row)
            final.append(scores['trained_sample']); initial.append(scores['initial_sample']); random_baseline.append(scores['uniform_random'])
            write(output / 'progress.json', report)
        report['success_mean'] = sum(r['success'] for r in report['seeds']) / 5
        report['versus_initial'] = paired_interval(final, initial)
        report['versus_random'] = paired_interval(final, random_baseline)
        report['generalization_passed'] = (report['success_mean'] >= .75
            and all(r['success'] > max(r['initial'], r['random']) and r['cooperation'] >= .1
                and r['cooperative_success'] >= .1 for r in report['seeds'])
            and report['versus_initial']['low'] > 0 and report['versus_random']['low'] > 0)
        report['passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        try: unchanged()
        except BaseException as error: report.update(passed=False, generalization_passed=False, error='Frozen inputs changed: ' + str(error))
        report['source_after'] = source_fingerprint()
        write(output / 'report.json', report)
    print(json.dumps({k: report.get(k) for k in ('passed', 'generalization_passed', 'parity_passed', 'error')}), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    for name in ('work', 'build', 'quality', 'study', 'models'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        if any(getattr(args, x) is None for x in ('work', 'build', 'quality', 'study', 'models')):
            parser.error('prepare requires work/build/quality/study/models')
        prepare(args); return 0
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
