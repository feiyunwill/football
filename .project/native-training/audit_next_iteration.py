#!/usr/bin/env python3
"""Reconcile the local iteration against current source, tools and raw receipts.

This checks local evidence, not remote CI or GPU acceptance. It preserves failed
experiments and reports performance goals separately from protocol execution.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from validate import ROOT, sha, source_fingerprint, runtime_identity
from quality import verify
from decide_candidate import decision
from validate_learning import successes, paired_interval


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = Path(__file__).parent / 'evidence'
    paths = dict(baseline='o1-baseline-20261015-a', latency='o1-latency-20261015-a',
        learning='o2-learning-20261015-a', workers='o4-ppo-workers-20261015-a',
        delivery='o5-delivery-20261015-b')
    runners = dict(baseline='benchmark_next_baseline.py', learning='validate_learning.py',
                   delivery='validate_delivery.py')
    report = dict(passed=False, environment=runtime_identity(sys.executable), reports={}, commands=[])
    try:
        current = source_fingerprint()
        report['source'] = current
        report['native_quality'] = verify(evidence/'o3-restored-quality-20261015-a/report.json',sys.executable)
        data = {}
        for name, directory in paths.items():
            path = evidence/directory/'report.json'
            row = json.loads(path.read_text())
            if not row.get('passed') or row['source_before']!=current or row['source_after']!=current:
                raise ValueError('Failed/stale local report: '+name)
            if name in runners and row['validator_sha256']!=sha(Path(__file__).with_name(runners[name])):
                raise ValueError('Changed experiment runner: '+name)
            for command in row.get('commands',[]):
                log = path.parent / command.get('log', command['name']+'.log')
                if command['exit_code']!=0 or sha(log)!=command['sha256']:
                    raise ValueError('Failed/changed command receipt: '+str(log))
            report['reports'][name] = dict(path=str(path),sha256=sha(path))
            data[name]=row
        for path, expected in data['baseline']['artifacts'].items():
            if sha(Path(path))!=expected:
                raise ValueError('Restored runtime differs from the measured baseline: '+path)
        for name, expected in data['workers']['tooling'].items():
            if sha(Path(__file__).with_name(name))!=expected:
                raise ValueError('Changed PPO diagnostic tool: '+name)
        primary_path=evidence/'o3-primary-20261015-a/report.json'
        primary=json.loads(primary_path.read_text())
        decided=json.loads((primary_path.parent/'decision.json').read_text())
        if decision(primary)!=decided or decided['action']!='reject':
            raise ValueError('Candidate decision does not match raw paired samples')
        if not json.loads((primary_path.parent/'restoration.json').read_text())['passed']:
            raise ValueError('Missing restoration record')
        report['reports']['candidate']=dict(path=str(primary_path),sha256=sha(primary_path),action=decided['action'])
        final, initial, random = [], [], []
        model_root=Path('/tmp/football-o2-learning-20261015-a')
        for row in data['learning']['final']:
            arrays={name:[] for name in ('final','initial','random')}
            model=model_root/f"{data['learning']['selected']}-{row['seed']}.bin"
            if sha(model)!=row['checkpoint_sha256']:
                raise ValueError('Trained checkpoint changed')
            for batch, saved in enumerate(row['batches']):
                for kind in ('initial','final'):
                    log=evidence/paths['learning']/f"{kind}-{row['seed']}-b{batch}.log"
                    actual=json.loads(log.read_text())
                    if actual['evaluation']!=saved[kind]:
                        raise ValueError('Evaluation summary differs from raw CLI output')
                arrays['final']+=successes(saved['final'],'argmax')
                arrays['initial']+=successes(saved['initial'],'argmax')
                arrays['random']+=successes(saved['final'],'uniform_random')
            if len(arrays['final'])!=200:
                raise ValueError('Incomplete held-out evaluation')
            final.append(arrays['final']); initial.append(arrays['initial']); random.append(arrays['random'])
        if (paired_interval(final,initial)!=data['learning']['versus_initial'] or
            paired_interval(final,random)!=data['learning']['versus_random']):
            raise ValueError('Learning intervals differ from raw matched episodes')
        if not data['learning']['learning_passed'] or not data['workers']['resume_verified']:
            raise ValueError('Learning/replay gate did not pass')
        for test in ('test_quality.py','test_learning_study.py'):
            command=[sys.executable,str(Path(__file__).with_name(test)),'-v']
            started=time.monotonic()
            run=subprocess.run(command,capture_output=True,timeout=60)
            log=output/(test+'.log'); log.write_bytes(run.stdout+run.stderr)
            report['commands'].append(dict(argv=command,exit_code=run.returncode,
                seconds=time.monotonic()-started,log=log.name,sha256=sha(log)))
            if run.returncode:
                raise ValueError('Failed statistical/acceptance self-test: '+test)
        report['goals']=dict(first_learning_gate=True,
            all_four_worker_twofold=data['workers']['twofold_target_observed'],
            remote_ci_executed=False,gpu_accepted=False)
        report['tooling']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in ('.py','.cpp')}
        report['ci_sha256']=sha(ROOT/'.github/workflows/native-training.yml')
        report['passed']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        if 'source' in report and source_fingerprint()!=report['source']:
            report.update(passed=False,error='Source changed during audit')
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],error=report.get('error')),indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
