"""Reconcile matched long runs, frozen load and independent worker CPU traces."""
import json
import math
from pathlib import Path
import pstats
import quality
import validate

def main():
    evidence=Path(__file__).with_name('evidence')
    comparison_path=evidence/'matched-worker-comparison-20261017-a/report.json'
    load_path=evidence/'matched-w1-checkpoint-load-20261017-a/report.json'
    cpu_dir=evidence/'worker-cpu-20261017-b'
    cpu_path=cpu_dir/'cpu-analysis.json'
    comparison,load,cpu=[json.loads(p.read_text()) for p in (comparison_path,load_path,cpu_path)]
    run=json.loads((cpu_dir/'report.json').read_text())
    single=json.loads((evidence/'matched-w1-20261017-a/report.json').read_text())
    current=validate.source_fingerprint()
    accepted=quality.verify(evidence/'selected-digests-quality-20261017-a/report.json')
    assert comparison['passed'] and load['passed'] and cpu['passed'] and run['passed']
    assert comparison['cross_run_environment_equal']
    assert comparison['source_sha256']==load['source_sha256']==current['sha256']
    assert run['source_before']==run['source_after']==current
    assert load['checkpoint_sha256']==single['checkpoint_sha256'] and load['version']==comparison['updates']
    for path,digest in comparison['receipts'].items(): assert validate.sha(Path(path))==digest
    assert cpu['run_report_sha256']==validate.sha(cpu_dir/'report.json')
    total=0.
    for name,digest in cpu['profiles'].items():
        path=cpu_dir/name; assert validate.sha(path)==digest
        total+=pstats.Stats(str(path)).total_tt
    assert math.isclose(total,cpu['profiled_cpu_seconds'],rel_tol=1e-12)
    for name,digest in cpu['timing_files'].items(): assert validate.sha(cpu_dir/name)==digest
    for path,digest in run['artifacts'].items(): assert validate.sha(Path(path))==digest
    assert run['workers_reaped'] and run['exit_codes']==[0]*4
    assert run['parent_before']['fds']==run['parent_after_close']['fds']
    assert validate.sha(cpu_dir/'iterations.jsonl')==run['iterations.jsonl_sha256']
    compared=0
    with (cpu_dir/'iterations.jsonl').open() as measured, (evidence/'sustained-ppo-20261017-a/iterations.jsonl').open() as control:
        for left,right in zip(measured,control):
            a,b=json.loads(left),json.loads(right)
            assert (a['version'],a['transitions'],a['update'])==(b['version'],b['transitions'],b['update'])
            compared+=1
    assert compared==run['updates']==128
    native={}; env={}; queue_wait_ns=0
    for row in cpu['worker_call_timings'].values():
        for target,key in ((native,'native_calls'),(env,'calls')):
            for name,values in row[key].items():
                result=target.setdefault(name,dict(calls=0,wall_ns=0,cpu_ns=0))
                for metric,value in values.items(): result[metric]+=value
        before,after=row['schedstat_before'],row['schedstat_after']
        if before is not None and after is not None:
            assert all(a>=b for a,b in zip(after,before))
            queue_wait_ns+=after[1]-before[1]
    assert env['step']['calls']==run['transitions']+4*20==native['step']['calls']
    for file,digest in [('compare_matched_ppo.py',comparison['runner_sha256']),
                        ('verify_sustained_checkpoint.py',load['runner_sha256']),
                        ('diagnose_worker_cpu.py',cpu['runner_sha256'])]:
        assert validate.sha(Path(__file__).with_name(file))==digest
    output=evidence/'matched-worker-audit-20261017-a'; output.mkdir(exist_ok=False)
    report=dict(passed=True,quality=accepted,source_sha256=current['sha256'],
        observed_speedup=comparison['observed_four_over_single_tps'],updates=comparison['updates'],
        profiled_updates_equal=compared,profiled_cpu_seconds=total,native_call_totals=native,environment_call_totals=env,
        scheduler_runqueue_wait_sum_seconds=queue_wait_ns/1e9,
        note='CPU/wall/runqueue sums span four instrumented workers and cannot be added to parent RPC wall. One historical pair is not a statistical scaling gate.',
        all_configuration_twofold_accepted=False,
        receipts={str(p.relative_to(evidence)):validate.sha(p) for p in (comparison_path,load_path,cpu_path,cpu_dir/'report.json')},
        runner_sha256=validate.sha(Path(__file__)))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,observed_speedup=report['observed_speedup'],native_call_totals=native)))
    return 0
if __name__=='__main__': raise SystemExit(main())
