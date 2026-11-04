"""Independent fresh-confirmation audit for the schema8 midl candidate."""
import argparse,json
from pathlib import Path
import numpy as np
import quality
from validate import sha,source_fingerprint
from validate_learning import SEEDS,paired_interval
from confirm_o23_learning import physical

def read(p):return json.loads(p.read_text())
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assessment',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.assessment;p=read(root/'protocol.json');r=read(root/'report.json')
    assert r['passed'] and r['protocol_sha256']==sha(root/'protocol.json')
    assert p['source']==r['source_after']==source_fingerprint();quality.verify(Path(p['quality']))
    assert all(sha(Path(path))==h for path,h in p['frozen'].items())
    excluded=np.fromfile(root/'forbidden-engine-seeds.u32le',dtype='<u4');assert len(excluded)==p['unique_forbidden_seeds']
    cases=read(root/'cases.json');assert len(cases)==len({c['engine_seed'] for c in cases})==200
    assert all(sum(c['group']==g for c in cases)==40 for g in range(5))
    geometry=set();history_geometry=set()
    for entry in p['history']:
        path=Path(entry['path']);assert sha(path)==entry['sha256']
        if path.name.startswith('starts-'):
            for line in path.read_text().splitlines():
                row=json.loads(line);history_geometry.add(tuple(row['geometry']+row['ball']))
        elif path.name=='cases.json':
            rows=read(path)
            for c in rows:
                if isinstance(c,dict) and all(k in c for k in ('attacker','teammate','defender')):history_geometry.add(physical(c,p['formation_y_scale']))
    for c in cases:
        seed=c['engine_seed'];index=np.searchsorted(excluded,seed);assert index==len(excluded) or int(excluded[index])!=seed
        point=physical(c,p['formation_y_scale']);assert point not in history_geometry and point not in geometry;geometry.add(point)
    assert len(r['commands'])==25
    for command in r['commands']:
        assert command['exit_code']==0 and sha(root/(command['name']+'.log'))==command['sha256']
        assert sha(root/(command['name']+'.stderr'))==command['stderr_sha256']
    primary=[];baseline=[];cells=[]
    for seed in SEEDS:
        row=dict(seed=seed,success_counts={});data={}
        for mode in p['modes']:
            lines=[json.loads(s) for s in (root/f'{seed}-{mode}.log').read_text().splitlines()];summary=lines.pop()
            assert summary['complete'] and len(lines)==200
            for e,c in zip(lines,cases):assert (e['index'],e['group'],e['engine_seed'])==(c['index'],c['group'],c['engine_seed'])
            data[mode]=lines;row['success_counts'][mode]=sum(e['controlled_score_delta']>0 for e in lines)
        row['pass_count']=sum(e['completed_passes']>0 for e in data['candidate'])
        row['joint_count']=sum(e['completed_passes']>0 and e['controlled_score_delta']>0 for e in data['candidate'])
        row['group_success_counts']=[sum(e['controlled_score_delta']>0 for e in data['candidate'] if e['group']==g) for g in range(5)]
        assert row==r['seeds'][len(cells)];cells.append(row)
        primary.append([int(e['controlled_score_delta']>0) for e in data['candidate']]);baseline.append([int(e['controlled_score_delta']>0) for e in data['old_balanced']])
    totals={mode:sum(c['success_counts'][mode] for c in cells) for mode in p['modes']}
    groups=[sum(c['group_success_counts'][g] for c in cells) for g in range(5)];interval=paired_interval(primary,baseline)
    gates=dict(mean=totals['candidate']>=930,every_seed=all(c['success_counts']['candidate']>=170 for c in cells),
        groups=all(n>=170 for n in groups),cooperation=all(c['pass_count']>=40 and c['joint_count']>=40 for c in cells),paired_improvement=interval['low']>0)
    assert gates==r['gates'] and all(gates.values())==r['confirmation_passed'] and interval==r['versus_old']
    means={k:n/1000 for k,n in totals.items()};assert means==r['means']
    result=dict(passed=True,confirmation_passed=all(gates.values()),gates=gates,seeds=cells,means=means,group_means=[n/200 for n in groups],
        versus_old=interval,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=p['source']['sha256'],
        unique_confirmation_geometries=200,excluded_engine_seeds=len(excluded),auditor_sha256=sha(Path(__file__)))
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
