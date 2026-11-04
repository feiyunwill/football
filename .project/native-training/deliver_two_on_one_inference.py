"""Deliver frozen confirmed inference; replay relocated package and actual archive."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import quality
from validate import ROOT, sha, source_fingerprint
from validate_learning import SEEDS


def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('assessment','audit','work','artifacts'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); assessment=args.assessment.resolve(); audit=read(args.audit/'report.json')
    protocol=read(assessment/'protocol.json'); study=read(assessment/'report.json'); current=source_fingerprint()
    assert audit['passed'] and audit['confirmation_passed'] and study['passed'] and study['confirmation_passed']
    assert audit['report_sha256']==sha(assessment/'report.json') and current==protocol['source']==study['source_after']
    quality_path=ROOT/'.project/native-training/evidence/two-on-one-quality-20261018-final/report.json'
    verified=quality.verify(quality_path)
    base=ROOT/'.project/native-training/evidence'
    prior_path=base/'two-on-one-delivery-20261018-final/report.json'; prior=read(prior_path)
    baseline_path=base/'two-on-one-baseline-20261018-final/report.json'; baseline=read(baseline_path)
    accepted_path=base/'two-on-one-audit-20261018-final/report.json'; accepted=read(accepted_path)
    assert prior['passed'] and prior['source_before']==prior['source_after']==current
    assert baseline['passed'] and baseline['source_before']==baseline['source_after']==current
    assert baseline['native']['duration_seconds']>=1800 and baseline['environment_passed'] and baseline['resumed_bytes_equal']
    assert accepted['passed'] and accepted['agreed_next_goal_complete'] and accepted['source_sha256']==current['sha256']
    assert all(sha(p) in accepted['receipts'].values() for p in (quality_path,baseline_path,prior_path))
    work=args.work.resolve(); artifacts=args.artifacts.resolve()
    work.mkdir(parents=True,exist_ok=False); artifacts.mkdir(parents=True,exist_ok=False)
    out=work/'delivery';out.mkdir(); package=work/'native-inference'; original=Path(prior['native_package']['path'])
    manifest=prior['native_package']['manifest']['files']
    assert all(sha(original/n)==h for n,h in manifest.items())
    shutil.copytree(original,package);assert all(sha(package/n)==h for n,h in manifest.items())
    shutil.copy2(assessment/'evaluate',package/'bin/evaluate-inference')
    shutil.copy2(assessment/'contract',package/'bin/contract-inference')
    cases=package/'inference';cases.mkdir()
    for name in ('cases.json','cases.txt','protocol.json','deterministic_inference.hpp','evaluate_two_on_one_inference.cpp','contract_deterministic_inference.cpp'):
        shutil.copyfile(assessment/name,cases/name)
    wrapper=package/'evaluate-inference.sh'
    wrapper.write_text('#!/bin/sh\nset -eu\nbundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport GFOOTBALL_DATA_DIR="$bundle/data"\nexport GFOOTBALL_FONT="$bundle/fonts/AlegreyaSansSC-ExtraBold.ttf"\nexport LD_LIBRARY_PATH="$bundle${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\nexport FOOTBALL_INFERENCE_RESUME=1\nexec "$bundle/bin/evaluate-inference" "$@"\n');wrapper.chmod(0o755)
    clean={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','FOOTBALL_INFERENCE_TRACE','FOOTBALL_INFERENCE_RESUME') and not k.startswith('GFOOTBALL_')}
    commands=[]; frozen_self=sha(Path(__file__))
    report=dict(passed=False,source_before=current,commands=commands,assessment_report_sha256=sha(assessment/'report.json'),
        audit_sha256=sha(args.audit/'report.json'),reused_receipts={str(p):sha(p) for p in (quality_path,baseline_path,prior_path,accepted_path)},
        reused_duration_seconds=baseline['native']['duration_seconds'],quality=verified,
        limitation='Prior exact-source installed77 tests/training duration/resume reused; no new training or speed claim. Adapter state must be saved with engine state, metrics and observations; FPPO alone does not contain it.')
    def run(name,argv,env=clean):
        print(name,flush=True)
        with (out/(name+'.log')).open('w') as stream:
            result=subprocess.run(list(map(str,argv)),cwd=out,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
        commands.append(dict(name=name,exit_code=result.returncode,sha256=sha(out/(name+'.log'))));assert result.returncode==0,name
    try:
        run('linkage',['ldd',package/'bin/evaluate-inference'],dict(clean,LD_LIBRARY_PATH=str(package)))
        linkage=(out/'linkage.log').read_text();assert str(package/'libfootball_engine.so') in linkage and 'not found' not in linkage and 'libpython' not in linkage
        run('controller-contract',[package/'bin/contract-inference'])
        expected=[]; mode=protocol['selected']
        for seed in SEEDS:
            model=package/f'study-models/2v1-{seed}.fppo';assert sha(model)==protocol['models'][str(seed)]['sha256']
            name=f'{seed}-{mode}';run(name,[wrapper,seed,model,mode,cases/'cases.txt'])
            assert (out/(name+'.log')).read_bytes()==(assessment/(name+'.log')).read_bytes()
            expected.append(f'{sha(out/(name+".log"))}  {name}.jsonl')
        (cases/'expected-results.sha256').write_text('\n'.join(expected)+'\n')
        script=package/'reproduce-inference.sh'
        script.write_text('#!/bin/sh\nset -eu\nbundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\noutput=${1:?Usage: reproduce-inference.sh NEW_OUTPUT_DIRECTORY}\nmkdir -- "$output"\nfor seed in 42 123 2026 31415 271828; do\n  "$bundle/evaluate-inference.sh" "$seed" "$bundle/study-models/2v1-$seed.fppo" '+mode+' "$bundle/inference/cases.txt" > "$output/$seed-'+mode+'.jsonl"\ndone\n(cd -- "$output" && sha256sum -c "$bundle/inference/expected-results.sha256")\n');script.chmod(0o755)
        (cases/'STATE.md').write_text('Deterministic probability-credit adapter; not pure argmax. Reset per episode. For mid-episode continuation save DIC1 controller state together with native environment snapshot, cooperation metrics, current observation and action RNG. The model FPPO checkpoint does not include this adapter. Native/controller serialized continuation checks execute at decision8 of cases0/40/80/120/160 when reached.\n')
        files={str(p.relative_to(package)):sha(p) for p in package.rglob('*') if p.is_file()}
        write(package/'inference-manifest.json',dict(files=files,source_sha256=current['sha256']))
        archive=artifacts/'football-two-on-one-inference-native.tar.gz'
        with tarfile.open(archive,'w:gz') as stream:stream.add(package,arcname='football-two-on-one-inference')
        extracted=work/'extracted';extracted.mkdir()
        with tarfile.open(archive) as stream:stream.extractall(extracted,filter='data')
        relocated=extracted/'football-two-on-one-inference'
        assert all(sha(relocated/n)==h for n,h in files.items())
        run('persistent-archive-reproduction',[relocated/'reproduce-inference.sh',work/'archive-replayed'])
        assert (out/'persistent-archive-reproduction.log').read_text().count(': OK')==5
        for seed in SEEDS:assert (work/'archive-replayed'/f'{seed}-{mode}.jsonl').read_bytes()==(assessment/f'{seed}-{mode}.log').read_bytes()
        assert source_fingerprint()==current and sha(Path(__file__))==frozen_self
        report.update(passed=True,delivered_replayed_episodes=1000,persistent_archive_replayed_episodes=1000,
            archive=str(archive),archive_sha256=sha(archive),package=str(package),source_after=source_fingerprint())
    except BaseException as error:report.update(error=f'{type(error).__name__}: {error}',source_after=source_fingerprint())
    write(out/'report.json',report)
    if not report['passed']:raise RuntimeError(report.get('error'))
    evidence=base/'two-on-one-inference-20261019-a';evidence.mkdir(exist_ok=False)
    sources=dict(assessment=assessment,audit=args.audit,delivery=out,
        validation=Path('/tmp/football-inference-validation-20261019-c'),traces=Path('/tmp/football-inference-traces-20261019-a'))
    for label,path in sources.items():shutil.copytree(path,evidence/label)
    for label in ('validation','confirmation'):
        names=('a','b') if label=='validation' else ('a',)
        for suffix in names:
            path=Path(f'/tmp/football-inference-{label}-20261019-{suffix}')
            if path.exists():shutil.copytree(path,evidence/f'{label}-attempt-{suffix}')
    partial=(evidence/'validation-attempt-b/balanced-42.log').read_text().splitlines()
    complete=(evidence/'validation/balanced-42.log').read_text().splitlines()
    assert partial==complete[:len(partial)]
    assert (evidence/'confirmation-attempt-a/cases.txt').read_bytes()==(evidence/'assessment/cases.txt').read_bytes()
    write(evidence/'attempts.json',dict(validation_a='Compile-only failure; no candidate episodes',
        validation_b='Stopped before complete candidate aggregate to reduce duplicate serialized-restore instrumentation',
        validation_b_prefix_rows=len(partial),validation_b_prefix_equal=True,
        confirmation_a='Executable permission failure before any episode; copy2 preserves mode in b',
        confirmation_a_b_cases_bytes_equal=True))
    final=dict(passed=True,agreed_next_goal_complete=True,selected=mode,source_sha256=current['sha256'],
        means=audit['means'],seeds=audit['seeds'],versus_argmax=audit['versus_argmax'],gates=audit['gates'],
        primary_episodes=1000,distinct_geometries=200,strategy_episodes=5000,
        serialized_native_controller_checks=audit['serialized_native_controller_checks'],
        delivery=report,scope=protocol['scope'])
    write(evidence/'report.json',final);write(artifacts/'acceptance.json',final)
    for name in ('deliver_two_on_one_inference.py','audit_two_on_one_inference.py'):
        shutil.copyfile(Path(__file__).with_name(name),evidence/name)
    write(evidence/'integrity.json',{str(p.relative_to(evidence)):sha(p) for p in evidence.rglob('*') if p.is_file()})
    (artifacts/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(artifacts.iterdir()) if p.is_file()))
    print(json.dumps(dict(passed=True,evidence=str(evidence),artifacts=str(artifacts))),flush=True)


if __name__=='__main__':main()
