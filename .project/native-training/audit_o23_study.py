"""Reconstruct O23 gates from raw logs and audit native training-start metadata."""
import argparse,hashlib,json,math,struct
from pathlib import Path
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
class Reader:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        assert 0<=n<=len(self.data)-self.pos
        b=self.data[self.pos:self.pos+n];self.pos+=n;return b
    def u32(self):return struct.unpack('<I',self.take(4))[0]
    def u64(self):return struct.unpack('<Q',self.take(8))[0]
    def vec(self):
        values=struct.unpack('<fff',self.take(12));assert all(math.isfinite(x) for x in values);return list(values)
    def blob(self):return self.take(self.u32())

def native_start(path,seed,variation,expected_version=2048):
    data=path.read_bytes();assert data[:4]==b'FPPO'
    header=Reader(data[4:]);assert header.u32()==1 and header.u32()==len(data)-44
    assert header.take(32)==hashlib.sha256(data[44:]).digest()
    p=Reader(data[44:]);assert p.u32()==variation and p.u32()==p.u32()==1
    assert [p.u32() for _ in range(5)]==[1,115,64,1,0]
    p.take(80);assert [p.u32() for _ in range(3)]==[4,64,1]
    assert p.u64()==seed and [p.u32() for _ in range(4)]==[10,256,0,variation]
    p.blob();scene=Reader(p.blob())
    version=p.u64();transitions=p.u64();episode=p.u64();next_episode=p.u64()
    assert version==expected_version and transitions==expected_version*256 and next_episode==episode+1
    assert scene.u32()==1;ball=scene.vec();teams=[]
    for _ in range(2):
        count=scene.u32();assert 1<=count<=11;team=[]
        for _ in range(count):
            scene.u32();position=scene.vec();scene.vec();scene.u32();scene.u32();team.append(position)
        teams.append(team)
    assert [len(t) for t in teams]==[3,2]
    scene.take(20);engine_seed=scene.u32()
    geometry=[*teams[0][1][:2],*teams[0][2][:2],*teams[1][1][:2]]
    return dict(episode=episode,engine_seed=engine_seed,geometry=geometry,ball=ball[:2])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();study=args.study;out=args.output;out.mkdir(parents=True,exist_ok=False)
    protocol=read(study/'protocol.json');r=read(study/'report.json')
    assert r['passed'] and protocol['source']==r['source_before']==r['source_after']==source_fingerprint()
    assert r['protocol_sha256']==sha(study/'protocol.json')
    assert all(sha(Path(p))==h for p,h in protocol['frozen'].items())
    assert r['resources_sha256']==sha(study/'resources.jsonl')
    assert [(m['configuration'],m['seed']) for m in r['models']]==[tuple(x) for x in protocol['training_order']]
    assert r['training_seconds']<=protocol['budget']['max_total_training_wall_seconds']
    for command in r['commands']:
        assert command['exit_code']==0 and sha(study/(command['name']+'.log'))==command['stdout_sha256']
        assert sha(study/(command['name']+'.stderr'))==command['stderr_sha256']
        assert command['peak_rss']<=protocol['budget']['max_child_rss_bytes']
    ppo=None;metadata=[]
    for model in r['models']:
        label,seed=model['configuration'],model['seed'];completed=0
        for chunk in range(1,9):
            data=read(study/f'train-{label}-{seed}-u{chunk*256}.log')
            assert data['scenario']==('2v1' if label=='legacy' else '2v1_broad')
            assert data['seed']==seed and data['hidden']==64 and data['start_version']==(chunk-1)*256 and data['version']==chunk*256
            assert data['total_transitions']==chunk*65536 and len(data['iterations'])==256
            if ppo is None:ppo=data['ppo']
            assert data['ppo']==ppo and data['cadence']==10 and data['episode_limit']==256
            checkpoint=study/f'models/{label}-{seed}-u{chunk*256}.fppo'
            assert data['state_sha256']==data['state_before_evaluation_sha256']==sha(checkpoint)==model['chunks'][chunk-1]['checkpoint_sha256']
            completed+=sum(row['completed_episodes'] for row in data['iterations'])
        assert sha(Path(model['path']))==model['sha256'] and sha(Path(model['policy']))==model['policy_sha256']
        starts_path=study/f'starts-{label}-{seed}.log';assert sha(starts_path)==model['starts_sha256']
        starts=[json.loads(line) for line in starts_path.read_text().splitlines()]
        assert len(starts)==completed+1==model['conservative_episode_starts']
        actual=native_start(Path(model['path']),seed,3 if label=='legacy' else 4)
        assert actual['episode'] in (completed,completed-1)
        expected=starts[actual['episode']]
        assert all(actual[k]==expected[k] for k in ('engine_seed','geometry','ball'))
        metadata.append(dict(configuration=label,seed=seed,final_native_start_matches=True,conservative_starts=len(starts)))
    cells={};case_ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in (study/'cases.txt').read_text().splitlines()]
    for seed in (42,123,2026,31415,271828):
        for label in ('legacy','broad80'):
            rows=[json.loads(s) for s in (study/f'validation-{label}-{seed}.log').read_text().splitlines()];summary=rows.pop()
            assert summary['complete'] and len(rows)==200 and [(x['index'],x['group'],x['engine_seed']) for x in rows]==case_ids
            cells[label,seed]=dict(success=sum(x['controlled_score_delta']>0 for x in rows),passes=sum(x['completed_passes']>0 for x in rows),
                joint=sum(x['completed_passes']>0 and x['controlled_score_delta']>0 for x in rows),
                groups=[sum(x['controlled_score_delta']>0 for x in rows if x['group']==g) for g in range(5)])
    seeds=(42,123,2026,31415,271828)
    a=sum(cells['legacy',s]['success'] for s in seeds);b=sum(cells['broad80',s]['success'] for s in seeds)
    groups=[sum(cells['broad80',s]['groups'][g] for s in seeds) for g in range(5)]
    gates=dict(mean=b>=920,versus_legacy=b>=a+20,every_seed=all(cells['broad80',s]['success']>=166 for s in seeds),
        cooperation=all(cells['broad80',s]['passes']>=40 and cells['broad80',s]['joint']>=40 for s in seeds),groups=all(n>=164 for n in groups))
    assert all(gates.values())==r['validation_passed'] and r['legacy_mean']==a/1000 and r['candidate_mean']==b/1000
    result=dict(passed=True,validation_passed=all(gates.values()),gates=gates,legacy_mean=a/1000,candidate_mean=b/1000,
        metadata=metadata,report_sha256=sha(study/'report.json'),protocol_sha256=sha(study/'protocol.json'),source_sha256=protocol['source']['sha256'],
        confirmation_opened=False,auditor_sha256=sha(Path(__file__)))
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
