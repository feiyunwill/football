"""Recompute paired action-rule diagnostic from immutable episode logs."""
import argparse,json
from pathlib import Path
from validate import sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('assessment','output'):ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args();root=a.assessment;out=a.output;out.mkdir(exist_ok=False)
    result=dict(passed=False)
    try:
        p=read(root/'protocol.json');r=read(root/'report.json')
        assert r['passed'] and p['source']==r['source_before']==r['source_after']==source_fingerprint()
        assert sha(root/'protocol.json')==r['protocol_sha256'] and all(sha(Path(f))==h for f,h in p['frozen'].items())
        assert r['seconds']<=p['max_total_seconds'] and len(r['commands'])==len(r['cells'])==len(p['models'])==10
        ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in Path(p['cases']).read_text().splitlines()]
        recomputed=[];paired=[]
        for m,c in zip(p['models'],r['commands']):
            name=f'sample-{m["label"]}-{m["seed"]}'
            assert c['name']==name and c['exit_code']==0 and c['seconds']<=300 and c['peak_rss']<=512*1024**2
            assert sha(root/(name+'.log'))==c['stdout_sha256'] and sha(root/(name+'.stderr'))==c['stderr_sha256']
            sets=[]
            for path in (root/(name+'.log'),Path(m['balanced'])):
                rr=[json.loads(line) for line in path.read_text().splitlines()];summary=rr.pop()
                assert summary['complete'] and summary['policy_sha256']==sha(Path(m['policy']))
                assert [(x['index'],x['group'],x['engine_seed']) for x in rr]==ids
                sets.append(rr)
            tallies=[]
            for rr in sets:
                goals=passes=joint=0;groups=[0]*5
                for x in rr:
                    g=int(x['controlled_score_delta']>0);q=int(x['completed_passes']>0)
                    goals+=g;passes+=q;joint+=g*q;groups[x['group']]+=g
                tallies.append(dict(goals=goals,passes=passes,joint=joint,groups=groups))
            recomputed.append(dict(label=m['label'],seed=m['seed'],sample=tallies[0],balanced=tallies[1]))
            wins=losses=0
            for sample,balanced in zip(*sets):
                delta=int(sample['controlled_score_delta']>0)-int(balanced['controlled_score_delta']>0)
                wins+=delta>0;losses+=delta<0
            paired.append(dict(label=m['label'],seed=m['seed'],sample_only_goal=wins,balanced_only_goal=losses))
        assert recomputed==r['cells']
        totals={label:{mode:sum(c[mode]['goals'] for c in recomputed if c['label']==label) for mode in ('sample','balanced')} for label in ('final8192','mean4')}
        result.update(passed=True,source_sha256=p['source']['sha256'],report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),auditor_sha256=sha(Path(__file__)),new_episodes=2000,totals=totals,paired=paired,selected_candidate=False)
    except BaseException as e:result['error']=f'{type(e).__name__}: {e}'
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
