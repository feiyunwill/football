"""Descriptive diagnostics on existing validation data; never new confirmation."""
import argparse
import collections
import json
from pathlib import Path
from validate import ROOT,sha,source_fingerprint
from validate_learning import SEEDS

def read_rows(p):
    data=[json.loads(line) for line in p.read_text().splitlines()]
    summary=data.pop();assert summary['episodes']==len(data)==200 and summary['isolated']
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    out=p.parse_args().output;out.mkdir(parents=True,exist_ok=False)
    before=source_fingerprint();evidence=ROOT/'.project/native-training/evidence'
    inference=evidence/'two-on-one-inference-20261019-a'
    broad=evidence/'two-on-one-broad-20261018-a/assessment';cases=json.loads((broad/'cases.json').read_text())
    frozen={str(broad/'cases.json'):sha(broad/'cases.json')};result=[];groups=collections.defaultdict(list)
    for seed in SEEDS:
        for mode in ('balanced','argmax','sample'):
            path=inference/'validation'/f'balanced-{seed}.log' if mode=='balanced' else broad/f'{seed}-trained_{mode}.log'
            frozen[str(path)]=sha(path);rows=read_rows(path)
            for row,case in zip(rows,cases):assert row['engine_seed']==case['engine_seed'] and row['index']==case['index']
            failed=[r for r in rows if r['controlled_score_delta']<=0]
            counts=dict(successes=len(rows)-len(failed),failures=len(failed),
                truncated_failures=sum(r['truncated'] for r in failed),
                no_pass_request_failures=sum(r['pass_requests']==0 for r in failed),
                requested_without_observed_completion_failures=sum(r['pass_requests']>0 and r['completed_passes']==0 for r in failed),
                observed_pass_without_goal_failures=sum(r['completed_passes']>0 for r in failed),
                turnover_failures=sum(r['turnovers']>0 for r in failed))
            assert counts['no_pass_request_failures']+counts['requested_without_observed_completion_failures']+counts['observed_pass_without_goal_failures']==len(failed)
            result.append(dict(seed=seed,mode=mode,episodes=200,success_rate=counts['successes']/200,counts=counts))
            for g in range(5):
                subset=[r for r in rows if r['group']==g];assert len(subset)==40
                groups[(mode,g)].extend(subset)
    aggregated={}
    for mode in ('balanced','argmax','sample'):
        records=[r for r in result if r['mode']==mode]
        aggregated[mode]=dict(episodes=1000,success_rate=sum(r['counts']['successes'] for r in records)/1000,
            counts={k:sum(r['counts'][k] for r in records) for k in records[0]['counts']},
            groups={cases[g*40]['group_name']:dict(episodes=200,success_rate=sum(r['controlled_score_delta']>0 for r in groups[(mode,g)])/200,
                failures=sum(r['controlled_score_delta']<=0 for r in groups[(mode,g)])) for g in range(5)})
    trace_report=inference/'traces/report.json';trace=json.loads(trace_report.read_text());assert trace['passed']
    frozen[str(trace_report)]=sha(trace_report)
    report=dict(passed=True,diagnostic_only=True,source_before=before,source_after=source_fingerprint(),
        raw_hashes=frozen,results=result,aggregated=aggregated,prior_repetition_diagnostics=trace['results'],
        limitations=['Old validation geometries only; no new confirmation opened.',
            'Pass completion is a decision-boundary approximation, not a kick event.',
            'Turnovers and truncation overlap the three mutually exclusive pass-history categories.',
            'Episode logs do not identify all terminal causes; no invented possession/out-of-play cause.',
            'Prior repetition traces cover argmax/sample for seeds123 and31415, not balanced or every model.',
            'Association only; candidate benefits require controlled validation.'])
    assert report['source_before']==report['source_after']
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(aggregated,indent=2),flush=True)

if __name__=='__main__':main()
