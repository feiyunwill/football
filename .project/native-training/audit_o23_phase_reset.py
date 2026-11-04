"""Recompute every paired row/count and retain phase-reset rejection."""
import argparse,json
from pathlib import Path
from validate import sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();p=read(args.study/'protocol.json');r=read(args.study/'report.json');args.output.mkdir(parents=True,exist_ok=False)
    assert r['passed'] and r['optimizer_updates']==0 and p['source']==r['source_before']==r['source_after']==source_fingerprint()
    assert sha(args.study/'protocol.json')==r['protocol_sha256'] and all(sha(Path(path))==h for path,h in p['frozen'].items())
    base=Path(p['study']);cells=[];paired=[]
    for seed in (42,123,2026,31415,271828):
        original=[json.loads(s) for s in (base/f'validation-{seed}.log').read_text().splitlines()][:-1];data={}
        for mode in ('balanced','phase_reset'):
            rows=[json.loads(s) for s in (args.study/f'{seed}-{mode}.log').read_text().splitlines()];summary=rows.pop()
            assert summary['complete'] and len(rows)==200 and [(x['index'],x['group'],x['engine_seed']) for x in rows]==[(x['index'],x['group'],x['engine_seed']) for x in original]
            if mode=='balanced':assert rows==original and summary['phase_resets']==0
            else:assert 0<=summary['phase_resets']<=sum(x['completed_passes']>0 for x in rows)
            cells.append(dict(seed=seed,mode=mode,goals=sum(x['controlled_score_delta']>0 for x in rows),passes=sum(x['completed_passes']>0 for x in rows),joint=sum(x['completed_passes']>0 and x['controlled_score_delta']>0 for x in rows),groups=[sum(x['controlled_score_delta']>0 for x in rows if x['group']==g) for g in range(5)],resets=summary['phase_resets']))
            data[mode]=rows
        paired.append(dict(seed=seed,gained=sum(a['controlled_score_delta']<=0 and b['controlled_score_delta']>0 for a,b in zip(data['balanced'],data['phase_reset'])),lost=sum(a['controlled_score_delta']>0 and b['controlled_score_delta']<=0 for a,b in zip(data['balanced'],data['phase_reset']))))
    assert cells==r['cells'] and len(r['commands'])==12
    for c in r['commands']:
        assert c['exit_code']==0 and c['observed_peak_rss']<=512*1024*1024
        assert sha(args.study/(c['name']+'.log'))==c['stdout_sha256'] and sha(args.study/(c['name']+'.stderr'))==c['stderr_sha256']
    candidate=[c for c in cells if c['mode']=='phase_reset'];a=sum(c['goals'] for c in cells if c['mode']=='balanced');b=sum(c['goals'] for c in candidate);groups=[sum(c['groups'][g] for c in candidate) for g in range(5)]
    gates=dict(mean=b>=970,every_seed=all(c['goals']>=180 for c in candidate),groups=all(n>=180 for n in groups),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in candidate),improvement=b>=a+10)
    assert gates==r['gates'] and all(gates.values())==r['validation_passed'] and a/1000==r['baseline_mean'] and b/1000==r['candidate_mean']
    result=dict(passed=True,validation_passed=all(gates.values()),gates=gates,baseline_mean=a/1000,candidate_mean=b/1000,paired=paired,report_sha256=sha(args.study/'report.json'),auditor_sha256=sha(Path(__file__)),interpretation='Single reset rule rejected;no new confirmation opened. Does not support this phase-reset intervention as the main improvement mechanism.')
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
