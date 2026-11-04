"""Independently recompute extended candidate gates,continuation and start records."""
import argparse,json,math
from pathlib import Path
from validate import sha,source_fingerprint
from audit_o23_study import native_start
def read(p):return json.loads(p.read_text())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();study=args.study;out=args.output;out.mkdir(parents=True,exist_ok=False)
    p=read(study/'protocol.json');r=read(study/'report.json');previous_path=Path(p['predecessor']);previous=read(previous_path/'report.json');audit=read(Path(p['predecessor_audit'])/'report.json')
    assert r['passed'] and r['source_before']==r['source_after']==p['source']==source_fingerprint()
    assert sha(study/'protocol.json')==r['protocol_sha256'] and all(sha(Path(k))==v for k,v in p['frozen'].items())
    assert previous['passed'] and not previous['validation_passed'] and audit['passed'] and not audit['validation_passed']
    assert audit['report_sha256']==sha(previous_path/'report.json')==r['predecessor_report_sha256']
    assert r['training_seconds']<=21000 and sha(study/'resources.jsonl')==r['resources_sha256']
    assert [(m['configuration'],m['seed']) for m in r['models']]==[tuple(x) for x in p['training_order']]
    for c in r['commands']:
        assert c['exit_code']==0 and c['peak_rss']<=512*1024*1024
        assert sha(study/(c['name']+'.log'))==c['stdout_sha256'] and sha(study/(c['name']+'.stderr'))==c['stderr_sha256']
    metadata=[];cells={};ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in (study/'cases.txt').read_text().splitlines()]
    for model in r['models']:
        seed=model['seed'];old=next(m for m in previous['models'] if m['seed']==seed and m['configuration']=='broad80')
        assert model['initial_model_sha256']==old['sha256'] and sha(Path(old['path']))==old['sha256']
        assert model['training_seconds']<=4200 and model['initial_version']==2048 and model['final_version']==8192
        assert len(model['chunks'])==24
        completed=old['conservative_episode_starts']-1;expected_ppo=read(previous_path/f'train-broad80-{seed}-u2048.log')['ppo']
        for index,target in enumerate(range(2304,8193,256)):
            data=read(study/f'train-broad80-{seed}-u{target}.log');checkpoint=study/f'models/broad80-{seed}-u{target}.fppo'
            assert data['scenario']=='2v1_broad' and data['seed']==seed and data['hidden']==64 and data['ppo']==expected_ppo
            assert data['cadence']==10 and data['episode_limit']==256 and data['start_version']==target-256 and data['version']==target and data['total_transitions']==target*256
            assert data['evaluation']['isolated'] and data['state_sha256']==data['state_before_evaluation_sha256']==sha(checkpoint)==model['chunks'][index]['checkpoint_sha256']
            assert len(data['iterations'])==256 and all(math.isfinite(row[k]) for row in data['iterations'] for k in ('loss','entropy','gradient_norm','parameter_delta'))
            completed+=sum(row['completed_episodes'] for row in data['iterations'])
        assert sha(Path(model['path']))==model['sha256'] and sha(Path(model['policy']))==model['policy_sha256']
        starts=study/f'starts-broad80-{seed}.log';assert sha(starts)==model['starts_sha256']
        rows=[json.loads(s) for s in starts.read_text().splitlines()];assert len(rows)==completed+1==model['conservative_episode_starts']
        actual=native_start(Path(model['path']),seed,4,8192);expected=rows[actual['episode']]
        assert actual['episode'] in (completed,completed-1) and all(actual[k]==expected[k] for k in ('engine_seed','geometry','ball'))
        metadata.append(dict(configuration='broad80',seed=seed,version=8192,final_native_start_matches=True,conservative_starts=len(rows)))
        data=[json.loads(s) for s in (study/f'validation-broad80-{seed}.log').read_text().splitlines()];summary=data.pop()
        assert summary['complete'] and len(data)==200 and [(x['index'],x['group'],x['engine_seed']) for x in data]==ids
        cells[seed]=dict(success=sum(x['controlled_score_delta']>0 for x in data),passes=sum(x['completed_passes']>0 for x in data),joint=sum(x['completed_passes']>0 and x['controlled_score_delta']>0 for x in data),groups=[sum(x['controlled_score_delta']>0 for x in data if x['group']==g) for g in range(5)])
    a=sum(row['legacy']['success_count'] for row in previous['validation']);b=sum(c['success'] for c in cells.values());groups=[sum(c['groups'][g] for c in cells.values()) for g in range(5)]
    gates=dict(mean=b>=920,versus_legacy=b>=a+20,every_seed=all(c['success']>=166 for c in cells.values()),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in cells.values()),groups=all(n>=164 for n in groups))
    assert all(gates.values())==r['validation_passed'] and r['legacy_mean']==a/1000 and r['candidate_mean']==b/1000
    for row in r['validation']:
        c=cells[row['seed']];assert row['broad80']['success_count']==c['success'] and row['broad80']['pass_count']==c['passes'] and row['broad80']['joint_count']==c['joint'] and row['broad80']['group_success_counts']==c['groups']
    result=dict(passed=True,validation_passed=all(gates.values()),gates=gates,legacy_mean=a/1000,candidate_mean=b/1000,metadata=metadata,
        report_sha256=sha(study/'report.json'),protocol_sha256=sha(study/'protocol.json'),source_sha256=p['source']['sha256'],confirmation_opened=False,auditor_sha256=sha(Path(__file__)))
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
