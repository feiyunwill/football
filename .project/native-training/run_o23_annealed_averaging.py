"""One preregistered schema5 within-seed mean4 policy; no optimizer updates or selection."""
import argparse,hashlib,json,math,os,shutil,subprocess,sys,time
from pathlib import Path
import psutil
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity
SEEDS=(42,123,2026,31415,271828)
VERSIONS=(7424,7680,7936,8192)
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def policy(p):
    magic,checksum,payload=p.read_text().split('\n',2)
    assert magic=='FPOL1' and hashlib.sha256(payload.encode()).hexdigest()==checksum
    header,*weights=payload.splitlines();h=header.split();values=list(map(float,weights))
    assert h[:3]==['two_on_one_sticky_v1','1','1'] and len(h)==7 and len(values)==int(h[5]) and all(map(math.isfinite,values))
    return h,values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('study','diagnosis','audit','quality','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();base=read(args.study/'report.json');late=read(args.diagnosis/'report.json');audit=read(args.audit/'report.json')
    assert base['passed'] and not base['validation_passed'] and late['passed'] and audit['passed']
    assert audit['report_sha256']==sha(args.diagnosis/'report.json')
    old_study=Path(read(args.study/'protocol.json')['old_study']);old_report=old_study/'report.json';old=read(old_report)
    before=source_fingerprint();assert before==base['source_after']==late['source_after'] and before['sha256']==audit['source_sha256']
    verified=quality.verify(args.quality/'report.json');build=args.build.resolve();binary=build/'bin/native_ppo_train';cases=args.study/'cases.txt'
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False);(out/'models').mkdir()
    sources={}
    for seed in SEEDS:
        for version in VERSIONS:
            checkpoint=args.study/f'models/annealed-{seed}-u{version}.fppo'
            exported=args.diagnosis/f'{seed}-{version}.fpol' if version!=8192 else Path(next(m for m in base['models'] if m['seed']==seed)['policy'])
            sources[seed,version]=(checkpoint,exported)
    draft=ROOT/'.project/optimization/o23-annealed-mean4-protocol-20261020.md'
    files=[Path(__file__),Path(__file__).with_name('audit_o23_annealed_averaging.py'),draft,args.study/'report.json',args.diagnosis/'report.json',args.audit/'report.json',old_report,args.quality/'report.json',cases,binary,build/'libfootball_engine.so']
    files.extend(p for pair in sources.values() for p in pair)
    files.extend(args.study/f'starts-annealed-{s}.log' for s in SEEDS)
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,environment=runtime_identity(sys.executable),frozen=frozen,seeds=list(SEEDS),versions=list(VERSIONS),
        training_study=str(args.study.resolve()),old_study=str(old_study.resolve()),diagnosis=str(args.diagnosis.resolve()),quality=str(args.quality.resolve()),build=str(build),optimizer_updates=0,
        algorithm='Binary64 math.fsum of four input binary64 values,then divide by4;ascending checkpoint version.',
        gates=dict(total_goals_min=970,seed_goals_min=180,group_goals_min=180,pass_min=40,joint_min=40,improvement_vs8192_goals_min=10),
        max_command_seconds=300,max_total_seconds=2400,max_child_rss_bytes=512*1024*1024,max_output_bytes=256*1024*1024,
        scope='Single fixed mean4 window,within each seed only. FPOL is a derived inference policy,not a standalone full-state training checkpoint.')
    write(out/'protocol.json',protocol);shutil.copyfile(cases,out/'cases.txt')
    report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=verified,models=[],commands=[],validation=[],optimizer_updates=0)
    started=time.monotonic();env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    try:
        for seed in SEEDS:
            headers=[];weights=[];members=[]
            for version in VERSIONS:
                checkpoint,exported=sources[seed,version];h,w=policy(exported)
                assert int(h[3])==seed and int(h[4])==64 and h[6]==sha(checkpoint)
                headers.append(h);weights.append(w);members.append(dict(version=version,weight=.25,checkpoint=str(checkpoint.resolve()),checkpoint_sha256=sha(checkpoint),policy=str(exported.resolve()),policy_sha256=sha(exported)))
            assert len({h[5] for h in headers})==1
            averaged=[math.fsum(column)/4 for column in zip(*weights)];assert len(averaged)==8724
            manifest=out/'models'/f'{seed}-provenance.json'
            write(manifest,dict(schema='within_seed_mean4_v1',seed=seed,members=members,algorithm=protocol['algorithm'],
                derived_inference_only=True,training_resume='Use latest original FPPO with unchanged source/build/ABI/resource guards;it does not contain the averaged inference weights.'))
            provenance=sha(manifest);h=headers[0].copy();h[6]=provenance
            payload=' '.join(h)+'\n'+''.join(format(v,'.17g')+'\n' for v in averaged)
            destination=out/'models'/f'{seed}.fpol';destination.write_text('FPOL1\n'+hashlib.sha256(payload.encode()).hexdigest()+'\n'+payload)
            _,roundtrip=policy(destination);assert roundtrip==averaged
            original=next(m for m in base['models'] if m['seed']==seed);start=out/f'starts-annealed_swa4-{seed}.log';shutil.copyfile(args.study/f'starts-annealed-{seed}.log',start)
            report['models'].append(dict(configuration='annealed_swa4',seed=seed,path=original['path'],sha256=original['sha256'],
                path_role='Underlying latest real training state;not averaged inference weights',policy=str(destination),policy_sha256=sha(destination),policy_kind='within_seed_mean4_v1',
                provenance_manifest=str(manifest),provenance_sha256=provenance,members=members,conservative_episode_starts=original['conservative_episode_starts'],starts_sha256=sha(start)))
        ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in cases.read_text().splitlines()]
        for model in report['models']:
            seed=model['seed'];name=f'validation-{seed}';print(name,flush=True);begin=time.monotonic();peak=0;reason=None
            with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
                argv=[str(binary),'--inference-mode','balanced','--policy',model['policy'],'--inference-cases',str(cases)]
                child=subprocess.Popen(argv,cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
                while child.poll() is None:
                    try:peak=max(peak,proc.memory_info().rss)
                    except psutil.NoSuchProcess:pass
                    if peak>512*1024*1024:reason='RSS budget'
                    if time.monotonic()-begin>300 or time.monotonic()-started>2400:reason='Wall budget'
                    if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>256*1024*1024:reason='Output budget'
                    if reason:child.kill();child.wait();break
                    time.sleep(.2)
            report['commands'].append(dict(name=name,argv=argv,exit_code=child.returncode,seconds=time.monotonic()-begin,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
            assert reason is None and child.returncode==0,(name,reason)
            rows=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop()
            assert summary['complete'] and len(rows)==200 and [(r['index'],r['group'],r['engine_seed']) for r in rows]==ids
            report['validation'].append(dict(seed=seed,goals=sum(r['controlled_score_delta']>0 for r in rows),passes=sum(r['completed_passes']>0 for r in rows),joint=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in rows),groups=[sum(r['controlled_score_delta']>0 for r in rows if r['group']==g) for g in range(5)]))
            write(out/'progress.json',report)
        cells=report['validation'];total=sum(r['goals'] for r in cells);groups=[sum(r['groups'][g] for r in cells) for g in range(5)];base_count=sum(r['goals'] for r in base['validation'])
        gates=dict(mean=total>=970,every_seed=all(r['goals']>=180 for r in cells),groups=all(g>=180 for g in groups),cooperation=all(r['passes']>=40 and r['joint']>=40 for r in cells),versus8192=total>=base_count+10,
            original_legacy_improvement=total>=sum(r['legacy']['success_count'] for r in old['validation'])+20)
        report.update(passed=True,validation_passed=all(gates.values()),gates=gates,candidate_mean=total/1000,base8192_mean=base_count/1000,candidate_group_means=[g/200 for g in groups],selected='annealed_swa4' if all(gates.values()) else None,confirmation_opened=False)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint();report['total_seconds']=time.monotonic()-started
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,validation_passed=False,error='Frozen source or evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','validation_passed','candidate_mean','gates','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
