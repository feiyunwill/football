"""Independent rational-mean verification and raw old-validation gate audit."""
import argparse,hashlib,json,math
from fractions import Fraction
from pathlib import Path
from validate import sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def decode(p):
    raw=p.read_bytes();parts=raw.split(b'\n',2);assert parts[0]==b'FPOL1' and hashlib.sha256(parts[2]).hexdigest().encode()==parts[1]
    fields=parts[2].split();assert fields[:3]==[b'two_on_one_sticky_v1',b'1',b'1']
    seed,hidden,count=map(int,fields[3:6]);weights=list(map(float,fields[7:]));assert len(weights)==count and all(map(math.isfinite,weights))
    return seed,hidden,fields[6].decode(),weights
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.study;out=args.output;out.mkdir(parents=True,exist_ok=False);result=dict(passed=False,validation_passed=False)
    try:
        p=read(root/'protocol.json');r=read(root/'report.json');assert r['passed'] and r['optimizer_updates']==p['optimizer_updates']==0
        assert p['source']==r['source_before']==r['source_after']==source_fingerprint() and sha(root/'protocol.json')==r['protocol_sha256']
        assert all(sha(Path(path))==checksum for path,checksum in p['frozen'].items())
        assert r['total_seconds']<=2400 and [(m['seed'],m['configuration']) for m in r['models']]==[(s,'broad80_swa4') for s in (42,123,2026,31415,271828)]
        base=read(Path(p['training_study'])/'report.json');ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in (root/'cases.txt').read_text().splitlines()]
        cells=[];metadata=[]
        for model in r['models']:
            seed=model['seed'];assert model['policy_kind']=='within_seed_mean4_v1' and sha(Path(model['policy']))==model['policy_sha256']
            manifest_path=Path(model['provenance_manifest']);manifest=read(manifest_path)
            assert sha(manifest_path)==model['provenance_sha256'] and manifest['members']==model['members'] and manifest['seed']==seed and manifest['derived_inference_only']
            assert [m['version'] for m in model['members']]==[7424,7680,7936,8192] and all(m['weight']==.25 for m in model['members'])
            weights=[]
            for member in model['members']:
                checkpoint,exported=Path(member['checkpoint']),Path(member['policy'])
                assert sha(checkpoint)==member['checkpoint_sha256'] and sha(exported)==member['policy_sha256']
                source_seed,hidden,provenance,values=decode(exported)
                assert source_seed==seed and hidden==64 and provenance==member['checkpoint_sha256'];weights.append(values)
            derived_seed,hidden,provenance,derived=decode(Path(model['policy']))
            assert derived_seed==seed and hidden==64 and provenance==sha(manifest_path) and len(derived)==8724
            expected=[float(sum((Fraction(v) for v in column),Fraction())/4) for column in zip(*weights)]
            assert derived==expected,'Averaged parameters disagree with independent exact-rational calculation'
            original=next(m for m in base['models'] if m['seed']==seed)
            assert model['path']==original['path'] and sha(Path(model['path']))==original['sha256']==model['sha256']
            assert sha(root/f'starts-broad80_swa4-{seed}.log')==original['starts_sha256']==model['starts_sha256']
            metadata.append(dict(seed=seed,parameters_verified=8724,members=4,within_seed=True,derived_inference_only=True,latest_real_fppo_unchanged=True))
            log=root/f'validation-{seed}.log';data=[json.loads(line) for line in log.read_text().splitlines()];summary=data.pop()
            assert summary['complete'] and summary['policy_sha256']==model['policy_sha256'] and len(data)==200 and [(x['index'],x['group'],x['engine_seed']) for x in data]==ids
            cells.append(dict(seed=seed,goals=sum(x['controlled_score_delta']>0 for x in data),passes=sum(x['completed_passes']>0 for x in data),joint=sum(x['completed_passes']>0 and x['controlled_score_delta']>0 for x in data),groups=[sum(x['controlled_score_delta']>0 for x in data if x['group']==g) for g in range(5)]))
        assert cells==r['validation'] and len(r['commands'])==5
        for command in r['commands']:
            assert command['exit_code']==0 and command['seconds']<=300 and command['observed_peak_rss']<=512*1024*1024
            assert sha(root/(command['name']+'.log'))==command['stdout_sha256'] and sha(root/(command['name']+'.stderr'))==command['stderr_sha256']
        total=sum(c['goals'] for c in cells);groups=[sum(c['groups'][g] for c in cells) for g in range(5)];base_count=sum(c['broad80']['success_count'] for c in base['validation'])
        gates=dict(mean=total>=950,every_seed=all(c['goals']>=180 for c in cells),groups=all(n>=180 for n in groups),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in cells),versus8192=total>=base_count+10,
            original_legacy_improvement=total>=sum(c['legacy']['success_count'] for c in base['validation'])+20)
        assert gates==r['gates'] and all(gates.values())==r['validation_passed'] and total/1000==r['candidate_mean']
        result.update(passed=True,validation_passed=all(gates.values()),gates=gates,candidate_mean=total/1000,metadata=metadata,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=p['source']['sha256'],auditor_sha256=sha(Path(__file__)))
    except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
