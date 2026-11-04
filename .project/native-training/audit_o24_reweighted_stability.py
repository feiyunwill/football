"""Audit raw one-hour samples and schema6 disk checkpoints independently."""
import argparse,hashlib,json,math,statistics,struct
from pathlib import Path
from validate import sha,source_fingerprint

def read(p):return json.loads(p.read_text())
class Cursor:
    def __init__(self,data):self.data=data;self.offset=0
    def take(self,n):
        assert 0<=n<=len(self.data)-self.offset
        value=self.data[self.offset:self.offset+n];self.offset+=n;return value
    def unpack(self,fmt):return struct.unpack('<'+fmt,self.take(struct.calcsize('<'+fmt)))
    def u32(self):return self.unpack('I')[0]
    def u64(self):return self.unpack('Q')[0]
    def blob(self):return self.take(self.u32())

def checkpoint(path):
    data=path.read_bytes();assert 44<=len(data)<=32*1024**2 and data[:4]==b'FPPO'
    assert struct.unpack('<II',data[4:12])==(1,len(data)-44) and data[12:44]==hashlib.sha256(data[44:]).digest()
    c=Cursor(data[44:]);assert c.unpack('III')==(6,1,1) and c.unpack('IIIII')==(1,115,64,1,0)
    parameters=c.unpack('10d');assert all(math.isfinite(v) for v in parameters) and parameters[5]==.0003
    assert c.unpack('III')==(4,64,1);seed=c.u64();assert seed==42 and c.unpack('IIII')==(10,256,0,6)
    assert c.blob() and c.blob()
    version,transitions,episode,next_episode=c.unpack('QQQQ');assert next_episode==episode+1
    episode_steps=c.u32();reward=c.unpack('d')[0];assert episode_steps<=256 and math.isfinite(reward)
    c.take(24);count=c.u32();assert count==8724
    assert all(math.isfinite(v) for v in c.unpack(str(3*count)+'d'))
    optimizer_steps=c.u64();assert c.blob()
    observations=c.u32();assert observations in (115,230)
    assert all(math.isfinite(v) for v in c.unpack(str(observations)+'f'))
    assert c.u32() in (0,1) and c.u32() in (0,1)
    requests,passes,transfers,turnovers=c.unpack('QQQQ');assert passes<=requests
    team,player,pending,age=c.unpack('iiiI');assert team in (-1,0,1) and -1<=player<=2 and pending in (-1,1) and age<=31
    assert c.offset==len(c.data)
    return dict(version=version,transitions=transitions,optimizer_steps=optimizer_steps,seed=seed,schema=6)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('assessment','output'):ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args();root=a.assessment;out=a.output;out.mkdir(parents=True,exist_ok=False);result=dict(passed=False)
    try:
        p=read(root/'protocol.json');r=read(root/'report.json')
        assert r['passed'] and p['source']==r['source_before']==r['source_after']==source_fingerprint()
        assert sha(root/'protocol.json')==r['protocol_sha256'] and all(sha(Path(f))==h for f,h in p['frozen'].items())
        assert p['duration_seconds']==3600 and p['process_wall_cap_seconds']==4000 and p['minimum_restore_checks']==50
        assert p['peak_rss_cap_bytes']==512*1024**2 and p['median_rss_growth_cap_bytes']==32*1024**2
        assert p['final_median_fd_growth_cap']==2 and p['absolute_fd_cap']==64
        assert r['child_reaped'] and r['exit_code']==0 and not r['build_observations'] and not r['descendant_pids']
        assert 3600<=r['wall_seconds']<=4000 and math.isfinite(r['cpu_seconds']) and r['cpu_seconds']>0
        assert sha(root/'continuous')==r['binary_sha256'] and len(r['commands'])==2
        for command in r['commands']:
            assert command['exit_code']==0 and sha(root/(command['name']+'.log'))==command['sha256']
        assert sha(root/'training.log')==r['training_log_sha256'] and sha(root/'resources.jsonl')==r['resource_log_sha256']
        lines=[json.loads(s) for s in (root/'training.log').read_text().splitlines()];native=lines.pop();assert native==r['native']
        assert native['passed'] and native['duration_gate'] and native['learning_rate_floor_verified'] and native['seconds']>=3600
        restores=native['restore_checks'];updates=native['updates'];assert restores>=50 and updates>restores
        assert native['transitions']==256*(updates-restores)+16*restores
        assert native['optimizer_steps']==16*(updates-restores)+4*restores
        assert r['wall_seconds']>=native['seconds'] and len(lines)>1
        for row in lines:
            assert row['progress'] and row['version']>8192 and row['restore_checks']<=restores
            calls=row['version']-8192;assert calls>=row['restore_checks']
            assert row['transitions']==256*(calls-row['restore_checks'])+16*row['restore_checks']
        assert all(b['seconds']>a['seconds'] and b['version']>a['version'] and b['transitions']>a['transitions'] for a,b in zip(lines,lines[1:]))
        samples=[json.loads(s) for s in (root/'resources.jsonl').read_text().splitlines()]
        assert samples and all(0<=x['seconds']<=r['wall_seconds'] and 0<x['rss']<=512*1024**2 and 0<=x['fds']<=64 for x in samples)
        assert all(b['seconds']>a['seconds'] and b['user']>=a['user'] and b['system']>=a['system'] for a,b in zip(samples,samples[1:]))
        warm=[x for x in samples if 300<=x['seconds']<=600];late=[x for x in samples if 3300<=x['seconds']<=3600]
        assert len(warm)>=250 and len(late)>=250
        rss_growth=statistics.median(x['rss'] for x in late)-statistics.median(x['rss'] for x in warm)
        fd_growth=statistics.median(x['fds'] for x in late)-statistics.median(x['fds'] for x in warm)
        assert rss_growth==r['median_rss_growth_bytes'] and rss_growth<=32*1024**2
        assert fd_growth==r['median_fd_growth'] and fd_growth<=2 and r['peak_rss_bytes']<=512*1024**2
        expected={f'learner-states/minute-{i}.fppo' for i in range(restores)}|{'learner-states/stability-only-final.fppo'}
        assert set(r['checkpoint_manifest'])==expected
        metadata=[]
        for name,h in r['checkpoint_manifest'].items():
            path=root/name;assert sha(path)==h;state=checkpoint(path)
            branches=restores if path.name=='stability-only-final.fppo' else int(path.stem.split('-')[-1])
            calls=state['version']-8192;assert calls>=branches
            assert state['transitions']==8192*256+256*(calls-branches)+16*branches
            assert state['optimizer_steps']==8192*16+16*(calls-branches)+4*branches
            if path.name=='stability-only-final.fppo':assert calls==updates
            metadata.append(dict(path=name,**state))
        gates=dict(duration=True,restore=True,global_lr_floor=True,quiet_no_observed_builds=True,no_sampler_workers=True,peak_rss=True,rss_growth=True,fd_growth=True)
        assert gates==r['gates']
        result.update(passed=True,gates=gates,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=p['source']['sha256'],
            auditor_sha256=sha(Path(__file__)),samples=len(samples),restore_checks=restores,checkpoints=metadata,median_rss_growth_bytes=rss_growth,median_fd_growth=fd_growth)
    except BaseException as e:result['error']=f'{type(e).__name__}: {e}'
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
