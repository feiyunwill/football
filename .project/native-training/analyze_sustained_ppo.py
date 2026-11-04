"""Independently reconcile streamed sustained-PPO timing and resource evidence."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import validate

def quantile(values,q):
    ordered=sorted(values); position=(len(ordered)-1)*q
    lower=math.floor(position); upper=math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--minimum-duration',type=float,default=1800)
    args=parser.parse_args(); evidence=args.evidence.resolve(); output=args.output.resolve()
    report=json.loads((evidence/'report.json').read_text())
    if not report['passed'] or report['status']!='completed': raise ValueError('No completed passing run')
    if report['duration_seconds']<args.minimum_duration: raise ValueError('Duration below protocol')
    if report['source_before']!=report['source_after'] or report['source_after']!=validate.source_fingerprint():
        raise ValueError('Stale source evidence')
    if report['artifacts']!=report['artifacts_after'] or report['tooling']!=report['tooling_after']:
        raise ValueError('Artifacts/tooling changed during run')
    for path,digest in report['artifacts'].items():
        if validate.sha(Path(path))!=digest: raise ValueError('Artifact changed after run')
    for name,digest in report['tooling'].items():
        if validate.sha(evidence/name)!=digest: raise ValueError('Archived tool changed')
    for name in ('iterations.jsonl','resources.jsonl'):
        if validate.sha(evidence/name)!=report[name+'_sha256']: raise ValueError('Stream changed')
    versions=transitions=iteration_ns=0; totals={}; previous=0.; start=0.; window_transitions=0; windows=[]; window_stages={}
    with (evidence/'iterations.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line); versions+=1
            if row['version']!=versions or row['elapsed_seconds']<=previous: raise ValueError('Nonmonotonic update')
            if not 1<=row['transitions']<=256 or row['update']['optimizer_steps']<=0: raise ValueError('Invalid update')
            if not all(math.isfinite(v) for v in row['update'].values()): raise ValueError('Nonfinite PPO metric')
            if any(v<0 for v in row['stages'].values()): raise ValueError('Negative stage time')
            if sum(row['stages'].values())>row['iteration_ns']: raise ValueError('Stage overlap')
            for name,value in row['stages'].items():
                totals[name]=totals.get(name,0)+value
                window_stages[name]=window_stages.get(name,0)+value
            iteration_ns+=row['iteration_ns']; transitions+=row['transitions']; window_transitions+=row['transitions']
            previous=row['elapsed_seconds']
            if previous-start>=60:
                windows.append(dict(end_seconds=previous,duration_seconds=previous-start,
                    transitions=window_transitions,tps=window_transitions/(previous-start),
                    stage_ns_per_transition={k:v/window_transitions for k,v in window_stages.items()}))
                start=previous; window_transitions=0; window_stages={}
    if versions!=report['updates'] or transitions!=report['transitions']: raise ValueError('Count mismatch')
    if dict(totals,iteration_ns=iteration_ns)!=report['stage_totals_ns']: raise ValueError('Timing totals mismatch')
    checkpoint=json.loads((evidence/'latest-checkpoint.json').read_text())
    if validate.sha(evidence/'latest-checkpoint.json')!=report['checkpoint_sha256']:
        raise ValueError('Checkpoint changed')
    if checkpoint['next_update']!=versions or checkpoint['state']['version']!=versions:
        raise ValueError('Checkpoint update mismatch')
    resources=report['resources']; parent=[r['parent']['rss_bytes'] for r in resources]
    worker=[sum(v['rss_bytes'] for v in r['workers'].values()) for r in resources]
    parent_fds=[r['parent']['fds'] for r in resources]
    worker_fds=[sum(v['fds'] for v in r['workers'].values()) for r in resources]
    tps=[w['tps'] for w in windows]
    summary=dict(passed=True,scope='one sustained four-worker duration baseline; not a scaling or learning-success gate',
        source_sha256=report['source_after']['sha256'],duration_seconds=report['duration_seconds'],
        updates=versions,transitions=transitions,aggregate_tps=report['transitions_per_second'],
        stage_fractions_of_iteration={k:v/iteration_ns for k,v in totals.items()},
        iteration_fraction_of_session=iteration_ns/(report['duration_seconds']*1e9),
        checkpoint_fraction_of_session=report['checkpoint_ns']/(report['duration_seconds']*1e9),
        minute_windows=windows,minute_tps=dict(p10=quantile(tps,.1),median=statistics.median(tps),
            p90=quantile(tps,.9),minimum=min(tps),maximum=max(tps)) if tps else None,
        memory=dict(parent_rss_first=parent[0],parent_rss_last=parent[-1],parent_rss_peak=max(parent),
            worker_rss_sum_first=worker[0],worker_rss_sum_last=worker[-1],worker_rss_sum_peak=max(worker),
            note='RSS sum double-counts shared pages; instrumentation retains bounded per-window metadata'),
        fds=dict(parent_min=min(parent_fds),parent_max=max(parent_fds),
            worker_sum_min=min(worker_fds),worker_sum_max=max(worker_fds),
            parent_before=report['parent_before']['fds'],parent_after=report['parent_after_close']['fds']),
        worker_cpu_seconds=(sum(v['cpu_ticks'] for v in resources[-1]['workers'].values())-
                            sum(v['cpu_ticks'] for v in resources[0]['workers'].values()))/__import__('os').sysconf('SC_CLK_TCK'),
        workers_reaped=report['workers_reaped'],runner_sha256=validate.sha(Path(__file__)),
        receipts={name:validate.sha(evidence/name) for name in ('report.json','iterations.jsonl','resources.jsonl','latest-checkpoint.json')})
    if len(windows)>=10:
        summary['last_five_vs_first_five_minute_tps_ratio']=statistics.median(tps[-5:])/statistics.median(tps[:5])
        def unit_cost(selected,key):
            return sum(w['stage_ns_per_transition'][key]*w['transitions'] for w in selected)/sum(w['transitions'] for w in selected)
        summary['first_last_five_minute_unit_costs']={key:dict(
            first_ns_per_transition=unit_cost(windows[:5],key),
            last_ns_per_transition=unit_cost(windows[-5:],key),
            last_over_first=unit_cost(windows[-5:],key)/unit_cost(windows[:5],key)) for key in totals}
    output.mkdir(parents=True,exist_ok=False)
    with (output/'minute-costs.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['end_seconds','duration_seconds','transitions','joint_transitions_per_second',
                         *[k.replace('_ns','_ms_per_transition') for k in totals]])
        for window in windows:
            writer.writerow([window['end_seconds'],window['duration_seconds'],window['transitions'],window['tps'],
                             *[window['stage_ns_per_transition'][k]/1e6 for k in totals]])
    summary['minute_costs_csv_sha256']=validate.sha(output/'minute-costs.csv')
    (output/'report.json').write_text(json.dumps(summary,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,duration_seconds=summary['duration_seconds'],transitions=transitions)))
    return 0
if __name__=='__main__': raise SystemExit(main())
