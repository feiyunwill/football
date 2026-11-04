"""Reconcile duration, independent analysis, frozen load and current quality."""
import json
from pathlib import Path
import quality
import validate

def main():
    evidence=Path(__file__).with_name('evidence')
    run_path=evidence/'sustained-ppo-20261017-a/report.json'
    analysis_path=evidence/'sustained-ppo-analysis-20261017-a/report.json'
    load_path=evidence/'sustained-checkpoint-load-20261017-a/report.json'
    quality_path=evidence/'selected-digests-quality-20261017-a/report.json'
    run,analysis,load=[json.loads(p.read_text()) for p in (run_path,analysis_path,load_path)]
    accepted=quality.verify(quality_path); current=validate.source_fingerprint()
    assert run['passed'] and analysis['passed'] and load['passed']
    assert run['duration_seconds']>=1800 and run['updates']==analysis['updates']==load['version']
    assert run['transitions']==analysis['transitions'] and run['source_before']==run['source_after']==current
    assert analysis['source_sha256']==load['source_sha256']==current['sha256']
    for name,digest in analysis['receipts'].items(): assert validate.sha(run_path.parent/name)==digest
    assert validate.sha(analysis_path.parent/'minute-costs.csv')==analysis['minute_costs_csv_sha256']
    assert load['checkpoint_sha256']==run['checkpoint_sha256']
    for file,receipt in [('profile_sustained_ppo.py',run['tooling']['profile_sustained_ppo.py']),
                         ('analyze_sustained_ppo.py',analysis['runner_sha256']),
                         ('verify_sustained_checkpoint.py',load['runner_sha256'])]:
        assert validate.sha(Path(__file__).with_name(file))==receipt
    assert run['workers_reaped'] and run['exit_codes']==[0]*4
    assert run['parent_before']['fds']==run['parent_after_close']['fds']
    output=evidence/'sustained-baseline-audit-20261017-a'; output.mkdir(exist_ok=False)
    result=dict(passed=True,source_sha256=current['sha256'],quality=accepted,
        duration_seconds=run['duration_seconds'],transitions=run['transitions'],updates=run['updates'],
        receipts={str(p.relative_to(evidence)):validate.sha(p) for p in (run_path,analysis_path,load_path,quality_path)},
        runner_sha256=validate.sha(Path(__file__)),
        remaining=['Matched single-worker duration baseline and independent repeated scaling runs',
                   'Step RPC decomposition into engine, IPC and scheduling',
                   'Variable-start/keeper learning study, current wheel delivery, remote CI; GPU deferred'])
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,transitions=run['transitions'])))
    return 0
if __name__=='__main__': raise SystemExit(main())
