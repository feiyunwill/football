"""Replay new frozen-model cases with the previously installed relocated core.

Production and models are unchanged: explicitly reuse their source-bound quality,
installation, resume and 30-minute training receipts, and freshly replay new cases.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

import quality
from validate import sha, source_fingerprint
from validate_learning import SEEDS


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assessment', 'audit', 'accepted', 'quality', 'baseline', 'delivery', 'work', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(); assessment = args.assessment.resolve()
    protocol = read(assessment / 'protocol.json'); study = read(assessment / 'report.json')
    audit = read(args.audit); accepted = read(args.accepted); delivery = read(args.delivery); baseline = read(args.baseline)
    current = source_fingerprint(); verified = quality.verify(args.quality)
    assert study['passed'] and audit['passed'] and audit['report_sha256'] == sha(assessment / 'report.json')
    assert accepted['passed'] and accepted['agreed_next_goal_complete'] and accepted['source_sha256'] == current['sha256']
    assert protocol['source'] == study['source_before'] == study['source_after'] == current
    assert delivery['passed'] and delivery['source_before'] == delivery['source_after'] == current
    assert baseline['passed'] and baseline['source_before'] == baseline['source_after'] == current
    assert baseline['native']['duration_seconds'] >= 1800 and baseline['environment_passed'] and baseline['resumed_bytes_equal']
    assert all(sha(p) in accepted['receipts'].values() for p in (args.quality, args.baseline, args.delivery))
    work = args.work.resolve(); output = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False); output.mkdir(parents=True, exist_ok=False)
    original = Path(delivery['native_package']['path']); package = work / 'native-broad'
    for name, digest in delivery['native_package']['manifest']['files'].items(): assert sha(original / name) == digest
    shutil.copytree(original, package)
    for name, digest in delivery['native_package']['manifest']['files'].items(): assert sha(package / name) == digest
    evaluator = Path(protocol['work']) / 'evaluate'
    assert sha(evaluator) == study['evaluator_sha256']
    shutil.copyfile(evaluator, package / 'bin/evaluate_two_on_one_generalization')
    (package / 'bin/evaluate_two_on_one_generalization').chmod(0o755)
    cases = package / 'broad-cases'; cases.mkdir()
    for name in ('cases.json', 'cases.txt', 'protocol.json', 'evaluate_two_on_one_generalization.cpp'):
        shutil.copyfile(assessment / name, cases / name)
    wrapper = package / 'evaluate-broad.sh'
    wrapper.write_text('#!/bin/sh\nset -eu\nbundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'export GFOOTBALL_DATA_DIR="$bundle/data"\nexport GFOOTBALL_FONT="$bundle/fonts/AlegreyaSansSC-ExtraBold.ttf"\n'
        'export LD_LIBRARY_PATH="$bundle${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
        'exec "$bundle/bin/evaluate_two_on_one_generalization" "$@"\n')
    wrapper.chmod(0o755)
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH') and not k.startswith('GFOOTBALL_')}
    commands = []; models = []
    def run(name, argv, env=environment):
        print(name, flush=True)
        with (output / (name + '.log')).open('w') as stream:
            result = subprocess.run(list(map(str, argv)), cwd=output, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        commands.append(dict(name=name, argv=list(map(str, argv)), exit_code=result.returncode, sha256=sha(output / (name + '.log'))))
        if result.returncode: raise RuntimeError(name + ' failed; raw log retained')
    report = dict(passed=False, source_before=current, commands=commands, models=models,
        assessment_report_sha256=sha(assessment / 'report.json'), assessment_audit_sha256=sha(args.audit),
        reused_receipts={str(p.resolve()): sha(p) for p in (args.accepted, args.quality, args.baseline, args.delivery)},
        quality=verified, reused_duration_seconds=baseline['native']['duration_seconds'],
        scope='New1000 primary episodes replayed; unchanged production/models reuse exact-source prior30-minute training and installed77-test/resume receipts; no fresh duration or throughput claim',
        verifier_sha256=sha(Path(__file__)))
    try:
        linkage_env = dict(environment, LD_LIBRARY_PATH=str(package))
        run('linkage', ['ldd', package / 'bin/evaluate_two_on_one_generalization'], linkage_env)
        linkage = (output / 'linkage.log').read_text()
        assert str(package / 'libfootball_engine.so') in linkage
        assert all(s not in linkage for s in ('not found', 'libpython', 'libgame.so', '_gameplayfootball'))
        expected = []
        for seed in SEEDS:
            model = package / f'study-models/2v1-{seed}.fppo'
            assert sha(model) == protocol['models'][str(seed)]['sha256']
            name = f'{seed}-trained_sample'
            run(name, [wrapper, seed, model, 'sample', cases / 'cases.txt'])
            assert (output / (name + '.log')).read_bytes() == (assessment / (name + '.log')).read_bytes()
            models.append(dict(seed=seed, model_sha256=sha(model), episodes=200, raw_rows_bytes_equal=True,
                replay_sha256=sha(output / (name + '.log'))))
            expected.append(f"{sha(output / (name + '.log'))}  {seed}-trained_sample.jsonl")
        (cases / 'expected-results.sha256').write_text('\n'.join(expected) + '\n')
        script = package / 'reproduce-broad.sh'
        script.write_text('#!/bin/sh\nset -eu\nbundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'output=${1:?Usage: reproduce-broad.sh NEW_OUTPUT_DIRECTORY}\nmkdir -- "$output"\n'
            'for seed in 42 123 2026 31415 271828; do\n'
            '  "$bundle/evaluate-broad.sh" "$seed" "$bundle/study-models/2v1-$seed.fppo" sample "$bundle/broad-cases/cases.txt" > "$output/$seed-trained_sample.jsonl"\n'
            'done\n(cd -- "$output" && sha256sum -c "$bundle/broad-cases/expected-results.sha256")\n')
        script.chmod(0o755); subprocess.run(['sh', '-n', script], check=True)
        manifest = {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
        (package / 'broad-manifest.json').write_text(json.dumps(dict(files=manifest, source_sha256=current['sha256']), indent=2) + '\n')
        report.update(passed=True, replayed_primary_episodes=1000, package=str(package),
            manifest_sha256=sha(package / 'broad-manifest.json'), linked_delivered_core=True)
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        report['source_after'] = source_fingerprint()
        if report['source_after'] != current or report['verifier_sha256'] != sha(Path(__file__)):
            report.update(passed=False, error='Source or verifier changed')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        shutil.copyfile(Path(__file__), output / Path(__file__).name)
    print(json.dumps(dict(passed=report['passed'], models=len(models), error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
