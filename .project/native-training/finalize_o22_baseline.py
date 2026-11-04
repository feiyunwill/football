"""Verify O22 recovery/diagnostics/pilot and preregister bounded O23 budget."""
import argparse
import datetime
import json
import math
from pathlib import Path
import shutil
import quality
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('quality','pilot','failures','runtime'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();current=source_fingerprint();verified=quality.verify(args.quality/'report.json')
    pilot=read(args.pilot/'report.json');failure=read(args.failures/'report.json');environment=read(args.runtime/'environment.json')
    assert pilot['passed'] and pilot['resume_bytes_equal'] and pilot['policy_export_bytes_equal'] and pilot['total_seconds']<=1800
    assert pilot['source_before']==pilot['source_after']==failure['source_before']==failure['source_after']==current
    assert environment['packages_match'] and environment['tools_match'] and environment['source_sha256']==current['sha256']
    assert sha(args.pilot/'protocol.json')==pilot['protocol_sha256'] and sha(args.pilot/'resources.json')==pilot['resource_log_sha256']
    for c in pilot['commands']:
        assert c['exit_code']==0 and sha(args.pilot/(c['name']+'.log'))==c['stdout_sha256'] and sha(args.pilot/(c['name']+'.stderr'))==c['stderr_sha256']
    assert (args.pilot/'full.fppo').read_bytes()==(args.pilot/'resumed.fppo').read_bytes()
    assert (args.pilot/'full.fpol').read_bytes()==(args.pilot/'resumed.fpol').read_bytes()
    old=ROOT/'.project/native-training/evidence';inference=old/'two-on-one-inference-20261019-a';broad=old/'two-on-one-broad-20261018-a'
    hashes=read(inference/'integrity.json')
    records={str(ROOT/r['path']):r['sha256'] for r in read(broad/'report.json')['archived_receipts']}
    for path,digest in failure['raw_hashes'].items():
        p=Path(path);assert sha(p)==digest
        if p.is_relative_to(inference):assert hashes[str(p.relative_to(inference))]==digest
        else:assert records[str(p)]==digest
    assert failure['aggregated']['balanced']['counts']['failures']==101
    # Operational caps are fixed before any O23 score is opened. They are not
    # performance acceptance claims or permission to add candidate searches.
    seconds=pilot['full_training_process_seconds'];cap=max(600,math.ceil(2*seconds*(2048/64)+120))
    assert cap<=3600,'Observed pilot too expensive for the proposed one-hour per-run cap; register a revised resource plan first'
    budget=dict(schema=1,design='One broad80 candidate vs legacy baseline; no parameter sweep',
        pilot_report_sha256=sha(args.pilot/'report.json'),pilot_source_sha256=current['sha256'],
        frozen_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),seeds=[42,123,2026,31415,271828],
        configurations=['legacy','broad80'],updates=2048,rollout=256,transitions_per_run=524288,
        hidden=64,epochs=4,minibatch=64,cadence=10,episode_limit=256,
        max_wall_seconds_per_training_run=cap,max_total_training_wall_seconds=cap*10,
        max_child_rss_bytes=512*1024*1024,max_study_output_bytes=2*1024*1024*1024,
        rationale='2x measured64-update process cost scaled to2048 updates +120s; minimum600s, maximum3600s. No training result used.',
        source_and_tools_freeze_required_before_training=True,new_confirmation_opened=False)
    directory=ROOT/'.project/native-training/evidence/o22-execution-20261020-a';directory.mkdir(exist_ok=False)
    for name,source in dict(quality=args.quality,pilot=args.pilot,failures=args.failures).items():shutil.copytree(source,directory/name)
    runtime=directory/'runtime';runtime.mkdir()
    for name in ('requirements.txt','pip-freeze.txt','environment.json'):shutil.copyfile(args.runtime/name,runtime/name)
    for name in ('analyze_o22_failures.py','pilot_o22_training.py','finalize_o22_baseline.py'):shutil.copyfile(Path(__file__).with_name(name),directory/name)
    write(directory/'o23-budget.json',budget)
    final=dict(passed=True,o22_goal_complete=True,long_term_goal_complete=False,source_sha256=current['sha256'],quality=verified,
        runtime_python=str(args.runtime/'venv/bin/python'),diagnostic_only=True,
        failure_counts=failure['aggregated']['balanced']['counts'],training_pilot=pilot,
        o23_budget=budget,receipts={str(p):sha(p) for p in (args.quality/'report.json',args.pilot/'report.json',args.failures/'report.json')},
        limitations=failure['limitations'],next_stage='O23 candidate implementation and current-source quality before10 training runs')
    write(directory/'report.json',final)
    write(directory/'integrity.json',{str(p.relative_to(directory)):sha(p) for p in directory.rglob('*') if p.is_file()})
    print(json.dumps(dict(passed=True,evidence=str(directory),pilot_tps=pilot['process_transition_tps'],training_wall_cap_seconds=budget['max_total_training_wall_seconds'])),flush=True)

if __name__=='__main__':main()
