"""Archive current-source installed CLI and exercise relocated/extracted replay."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import statistics
import subprocess
import tarfile

import quality
from validate import ROOT,sha,source_fingerprint
from validate_learning import SEEDS


def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('assessment','quality','delivery','micro','boundary','work','artifacts'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();current=source_fingerprint();q=quality.verify(args.quality/'report.json')
    assessment=read(args.assessment/'report.json');delivery=read(args.delivery/'report.json');micro=read(args.micro)
    assert assessment['passed'] and delivery['passed'] and micro['contract_passed']
    boundary=read(args.boundary/'report.json')
    assert boundary['passed'] and boundary['modes_resumed']==5 and boundary['episode_boundary_resumed']
    assert boundary['source_sha256']==micro['source_sha256']==current['sha256']
    assert assessment['source_before']==assessment['source_after']==delivery['source_before']==delivery['source_after']==current
    reference=ROOT/'.project/native-training/evidence/two-on-one-inference-20261019-a/assessment'
    parity_protocol=read(args.assessment/'protocol.json')
    assert sha(args.assessment/'protocol.json')==assessment['protocol_sha256']
    assert all(sha(Path(p))==h for p,h in parity_protocol['frozen'].items())
    for command in assessment['commands']:
        name=command['name'];expected=0 if name!='strict-old-fppo-rejected' else 1
        assert command['exit_code']==expected
        assert sha(args.assessment/(name+'.log'))==command['stdout_sha256']
        assert sha(args.assessment/(name+'.stderr'))==command['stderr_sha256']
    for seed in SEEDS:
        for mode in ('balanced','argmax','sample'):
            name=f'{seed}-{mode}.log'
            rows=(args.assessment/name).read_bytes().splitlines(keepends=True)[:-1]
            assert len(rows)==200 and rows==(reference/name).read_bytes().splitlines(keepends=True)[:-1]
        rows=lambda suffix:(args.assessment/f'{seed}-resume-{suffix}.log').read_bytes().splitlines(keepends=True)[:-1]
        assert rows('full')==rows('prefix')+rows('continuation')
    for command in boundary['commands']:
        assert command['exit_code']==0 and sha(args.boundary/(command['name']+'.log'))==command['sha256']
    for command in delivery['commands']:assert command['exit_code']==0 and sha(args.delivery/command['log'])==command['sha256']
    integration=(args.delivery/'installed-integration.log').read_text();assert 'skipped' not in integration and '\nOK\n' in integration
    original=Path(delivery['native_package']['path']);files=delivery['native_package']['manifest']['files']
    assert all(sha(original/n)==h for n,h in files.items())
    work=args.work.resolve();artifacts=args.artifacts.resolve();work.mkdir(parents=True,exist_ok=False);artifacts.mkdir(parents=True,exist_ok=False)
    package=work/'native-o21';shutil.copytree(original,package)
    exports=Path('/root/work_space/football-artifacts/o21-policy-exports-20261019-a')
    data=package/'inference';data.mkdir();shutil.copyfile(args.assessment/'cases.txt',data/'cases.txt')
    shutil.copyfile(exports/'report.json',data/'export-provenance.json')
    (data/'README.txt').write_text('Run ./reproduce-inference.sh NEW_OUTPUT_DIRECTORY from the package root to replay all five models.\n'
        'The root native_ppo_train launcher accepts --inference-mode balanced --policy inference/42.fpol --inference-cases inference/cases.txt.\n'
        'Pause using --inference-decisions 8 --inference-state-out NEW_SESSION.fifs; resume using --inference-state-in NEW_SESSION.fifs with identical mode,policy,cases and compatible core/resources.\n'
        'FPOL1 is inference-only weights exported by the original compatible O20 engine, not an FPPO training checkpoint. FIFS1 includes native and controller state and rejects incompatible builds.\n'
        'Episode rows are deterministic; the final summary includes per-invocation timing and is excluded from reproduction SHA checks.\n')
    expected=[]
    for seed in SEEDS:
        shutil.copyfile(exports/f'{seed}.fpol',data/f'{seed}.fpol')
        target=data/f'{seed}-expected.jsonl'
        target.write_bytes(b''.join((args.assessment/f'{seed}-balanced.log').read_bytes().splitlines(keepends=True)[:-1]))
        expected.append(f'{sha(target)}  {seed}-balanced.jsonl')
    (data/'expected-results.sha256').write_text('\n'.join(expected)+'\n')
    script=package/'reproduce-inference.sh'
    script.write_text('''#!/bin/sh
set -eu
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
output=${1:?Usage: reproduce-inference.sh NEW_OUTPUT_DIRECTORY}
mkdir -- "$output"
for seed in 42 123 2026 31415 271828; do
  "$bundle/native_ppo_train" --inference-mode balanced --policy "$bundle/inference/$seed.fpol" --inference-cases "$bundle/inference/cases.txt" > "$output/$seed-balanced.raw.jsonl"
  sed '$d' "$output/$seed-balanced.raw.jsonl" > "$output/$seed-balanced.jsonl"
done
(cd -- "$output" && sha256sum -c "$bundle/inference/expected-results.sha256")
''');script.chmod(0o755)
    manifest={str(p.relative_to(package)):sha(p) for p in package.rglob('*') if p.is_file()}
    write(package/'o21-manifest.json',dict(files=manifest,source_sha256=current['sha256']))
    clean={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH') and not k.startswith(('GFOOTBALL_','FOOTBALL_INFERENCE_'))}
    commands=[]
    def run(name,argv):
        print(name,flush=True)
        with (work/(name+'.log')).open('w') as stream:
            result=subprocess.run(list(map(str,argv)),cwd=work,env=clean,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
        commands.append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,sha256=sha(work/(name+'.log'))));assert result.returncode==0,name
    run('relocated-reproduction',[script,work/'relocated-replayed'])
    assert (work/'relocated-reproduction.log').read_text().count(': OK')==5
    archive=artifacts/'football-o21-native-inference.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:stream.add(package,arcname='football-o21')
    extracted=work/'extracted';extracted.mkdir()
    with tarfile.open(archive) as stream:stream.extractall(extracted,filter='data')
    moved=extracted/'football-o21';assert all(sha(moved/n)==h for n,h in manifest.items())
    run('archive-reproduction',[moved/'reproduce-inference.sh',work/'archive-replayed'])
    assert (work/'archive-reproduction.log').read_text().count(': OK')==5
    for seed in SEEDS:
        for directory in ('relocated-replayed','archive-replayed'):
            assert (work/directory/f'{seed}-balanced.jsonl').read_bytes()==(data/f'{seed}-expected.jsonl').read_bytes()
    # Test serialized continuation with the installed package's own core identity.
    one=work/'one-case.txt';one.write_text((data/'cases.txt').read_text().splitlines()[0]+'\n')
    common=[moved/'native_ppo_train','--inference-mode','balanced','--policy',moved/'inference/42.fpol','--inference-cases',one]
    run('installed-inference-full',common)
    run('installed-inference-prefix',[*common,'--inference-decisions',8,'--inference-state-out',work/'installed.fifs'])
    run('installed-inference-resumed',[*common,'--inference-state-in',work/'installed.fifs'])
    rows=lambda name:(work/(name+'.log')).read_bytes().splitlines(keepends=True)[:-1]
    assert rows('installed-inference-full')==rows('installed-inference-prefix')+rows('installed-inference-resumed')
    # The delivery receipt identifies the independently built and installed wheel.
    wheel_name=delivery['wheel']['name'];wheel_candidates=list(Path(delivery['native_package']['path']).parent.glob('wheels/'+wheel_name))
    assert len(wheel_candidates)==1 and sha(wheel_candidates[0])==delivery['wheel']['sha256']
    shutil.copyfile(wheel_candidates[0],artifacts/wheel_name)
    assert source_fingerprint()==current
    medians={mode:statistics.median(m['nanoseconds_per_decision'] for m in micro['measurements'] if m['mode']==mode) for mode in ('balanced','argmax','sample')}
    final=dict(passed=True,agreed_next_goal_complete=True,source_sha256=current['sha256'],quality=q,
        primary_episodes_byte_equal=1000,baseline_episodes_byte_equal=2000,new_process_resumes=5,
        installed_session_resume=True,all_five_modes_resume=True,episode_boundary_resume=True,
        installed_integration_test_count=int(re.search(r'^Ran (\d+) tests',integration,re.MULTILINE).group(1)),
        relocated_replayed_episodes=1000,archive_replayed_episodes=1000,
        strict_old_fppo_rejected=assessment['strict_old_fppo_rejected'],
        micro_median_nanoseconds=medians,controller_bytes=micro['controller_bytes'],serialized_controller_bytes=micro['serialized_controller_bytes'],
        micro_scope='Synthetic primary observation,hidden64,5 repeats x20000 decisions; forward+distribution+action. No isolated engine speedup claim.',
        process_costs=assessment['seeds'],archive=str(archive),archive_sha256=sha(archive),wheel=delivery['wheel'],
        commands=commands,receipts={str(p.resolve()):sha(p) for p in (args.assessment/'report.json',args.quality/'report.json',args.delivery/'report.json',args.micro)},
        scope='Official inference-only fixed-simple115 2v1 CLI. O20 cases are parity regression, not new learning confirmation. No new30-minute training claim.')
    evidence=ROOT/'.project/native-training/evidence/o21-cli-20261019-a';evidence.mkdir(exist_ok=False)
    for label,source in dict(assessment=args.assessment,quality=args.quality,delivery=args.delivery,exports=exports,boundary=args.boundary).items():shutil.copytree(source,evidence/label)
    attempt=Path('/root/work_space/football-artifacts/work-o21-parity-20261019-a')
    shutil.copytree(attempt,evidence/'parity-attempt-a')
    write(evidence/'attempts.json',dict(parity_a='External /usr/bin/time unavailable; no episode executed. b uses wait4 resource accounting; source and gates unchanged.'))
    shutil.copyfile(args.micro,evidence/'microbenchmark.json')
    sources=evidence/'source-files'
    for name in ('engine/src/training/native_ppo_train.cpp','engine/src/training/native_inference.hpp',
                 'engine/src/training/deterministic_inference.hpp','gfootball/test_native_ppo_cli.py',
                 'gfootball/doc/native_training.md'):
        target=sources/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    tools=evidence/'tooling';tools.mkdir()
    for name in ('export_o20_policy.cpp','prepare_o21_exports.py','assess_o21_cli.py','check_o21_boundaries.py',
                 'benchmark_o21_inference.cpp','run_o21_micro.py','finalize_o21_cli.py'):
        shutil.copyfile(Path(__file__).with_name(name),tools/name)
    for name in ('relocated-reproduction','archive-reproduction','installed-inference-full','installed-inference-prefix','installed-inference-resumed'):
        shutil.copyfile(work/(name+'.log'),evidence/(name+'.log'))
    write(evidence/'report.json',final);write(artifacts/'acceptance.json',final)
    shutil.copyfile(Path(__file__),evidence/Path(__file__).name)
    write(evidence/'integrity.json',{str(p.relative_to(evidence)):sha(p) for p in evidence.rglob('*') if p.is_file()})
    (artifacts/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(artifacts.iterdir()) if p.is_file()))
    print(json.dumps(dict(passed=True,evidence=str(evidence),micro_medians=medians)),flush=True)


if __name__=='__main__':main()
