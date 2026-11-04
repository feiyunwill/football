"""Preregistered reweighted task:five fresh8192 runs,fixed within-seed mean4."""
import argparse,hashlib,json,math,os,shutil,subprocess,sys,time
from run_o23_averaging import policy as decode_policy
from pathlib import Path
import psutil
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity
from audit_o23_study import native_start
SEEDS=(42,123,2026,31415,271828)
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('pilot','audit','quality','build','oldstudy','meanstudy','predecessor','budget','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();pilot=read(args.pilot/'report.json');audit=read(args.audit/'report.json');old=read(args.oldstudy/'report.json');mean=read(args.meanstudy/'report.json')
    assert pilot['passed'] and audit['passed'] and audit['report_sha256']==sha(args.pilot/'report.json')
    assert old['passed'] and mean['passed'] and old['validation_passed'] and mean['validation_passed']
    verified=quality.verify(args.quality/'report.json');before=source_fingerprint();assert before==pilot['source_after']
    budget_record=read(args.budget);budget=budget_record['budget'];assert all(sha(Path(f))==h for f,h in budget_record['frozen'].items());assert budget_record['passed'] and budget_record['source_sha256']==before['sha256'] and budget_record['pilot_report_sha256']==sha(args.pilot/'report.json')
    assert budget_record['pilot_audit_sha256']==sha(args.audit/'report.json')
    assert 0<budget['max_wall_seconds_per_training_run']<=5113 and budget['max_total_training_wall_seconds']==5*budget['max_wall_seconds_per_training_run']
    predecessor=read(args.predecessor/'report.json');assert predecessor['passed'] and not predecessor['validation_passed']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False);models=out/'models';models.mkdir()
    build=args.build.resolve();binary=build/'bin/native_ppo_train';dump=args.pilot/'starts';assert sha(dump)==pilot['starts_binary_sha256']
    cases=args.oldstudy/'cases.txt';assert sha(cases)==sha(args.meanstudy/'cases.txt')
    baselines=[]
    for label,study,report in (('constant8192',args.oldstudy,old),('mean4',args.meanstudy,mean)):
        for seed in SEEDS:
            model=next(m for m in report['models'] if m['seed']==seed);policy=Path(model['policy']);assert sha(policy)==model['policy_sha256']
            log=study/(f'validation-broad80-{seed}.log' if label=='constant8192' else f'validation-{seed}.log')
            baselines.append(dict(label=label,seed=seed,policy=str(policy.resolve()),policy_sha256=sha(policy),reference_log=str(log.resolve()),reference_sha256=sha(log)))
    draft=ROOT/'.project/optimization/o23-reweighted-training-protocol-20261021.md';here=Path(__file__).parent
    files=[Path(__file__),here/'audit_o23_reweighted_study.py',here/'audit_o23_study.py',here/'run_o23_averaging.py',here/'audit_o23_averaging.py',args.budget,args.predecessor/'report.json',args.predecessor/'protocol.json',here/'dump_o23_reweighted_starts.cpp',draft,args.pilot/'report.json',args.pilot/'protocol.json',args.pilot/'full64.log',args.audit/'report.json',args.quality/'report.json',args.oldstudy/'report.json',args.meanstudy/'report.json',binary,build/'libfootball_engine.so',dump,cases]
    files.extend(Path(row[k]) for row in baselines for k in ('policy','reference_log'))
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,environment=runtime_identity(sys.executable),frozen=frozen,budget=budget,baselines=baselines,
        pilot=str(args.pilot.resolve()),pilot_audit=str(args.audit.resolve()),quality=str(args.quality.resolve()),build=str(build),old_study=str(args.oldstudy.resolve()),mean_study=str(args.meanstudy.resolve()),predecessor=str(args.predecessor.resolve()),budget_receipt=str(args.budget.resolve()),
        seeds=list(SEEDS),training_order=[['reweighted_mean4',s] for s in SEEDS],scenario='2v1_broad_reweighted',payload_schema=6,initialization='Supported native initialization from each fixed seed;not old or pilot FPPO',
        updates_per_chunk=256,chunks=32,final_version=8192,lr='0.0003*max(0.1,1-global_version_before_update/8192)',
        selection='Fixed within-seed equal mean of7424,7680,7936,8192;no raw-final validation or window search',validation_gates=dict(total=970,seed=180,group=180,passes=40,joint=40),confirmation_opened=False)
    write(out/'protocol.json',protocol);shutil.copyfile(cases,out/'cases.txt')
    for p in (Path(__file__),here/'audit_o23_reweighted_study.py',draft):shutil.copyfile(p,out/p.name)
    commands=[];records=[];started=time.monotonic();training_seconds=0.;resources=out/'resources.jsonl'
    report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=verified,commands=commands,models=records,regressions=[],validation=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def unchanged():assert source_fingerprint()==before and all(sha(Path(p))==h for p,h in frozen.items()),'Frozen source/tool/model changed'
    def run(name,argv,cap,training=False):
        nonlocal training_seconds
        print(name,flush=True);begin=time.monotonic();peak=0;reason=None;last_sample=0
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resources.open('a') as samples:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                elapsed=time.monotonic()-begin
                if elapsed>cap:reason='Wall budget'
                try:
                    rss=proc.memory_info().rss;peak=max(peak,rss)
                    if rss>512*1024*1024:reason='RSS budget'
                    if elapsed-last_sample>=2:
                        cpu=proc.cpu_times();samples.write(json.dumps(dict(command=name,seconds=elapsed,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');samples.flush();last_sample=elapsed
                        if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>2*1024**3:reason='Output budget'
                except psutil.NoSuchProcess:pass
                if reason:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    break
                time.sleep(.2)
        seconds=time.monotonic()-begin
        if training:training_seconds+=seconds
        commands.append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
        write(out/'progress.json',dict(report,active_command=name,training_seconds=training_seconds));assert reason is None and child.returncode==0,(name,reason)
    try:
        for item in baselines:
            unchanged();name=f'regression-{item["label"]}-{item["seed"]}';run(name,[binary,'--inference-mode','balanced','--policy',item['policy'],'--inference-cases',cases],300)
            actual=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=actual.pop()
            expected=[json.loads(s) for s in Path(item['reference_log']).read_text().splitlines()];expected.pop()
            assert summary['complete'] and len(actual)==200 and actual==expected,'Portable inference changed under current source'
            report['regressions'].append(dict(label=item['label'],seed=item['seed'],episodes=200,rows_equal=True))
        report['portable_regression_passed']=True;pilot_iterations=read(args.pilot/'full64.log')['iterations']
        for seed in SEEDS:
            unchanged();begin=time.monotonic();last=None;completed=0;record=dict(configuration='reweighted_mean4',seed=seed,chunks=[],initial_version=0,final_version=8192)
            for target in range(256,8193,256):
                checkpoint=models/f'reweighted-{seed}-u{target}.fppo';policy=models/f'reweighted-{seed}-u{target}.fpol'
                argv=[binary,'--scenario','2v1_broad_reweighted','--seed',seed,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0,'--updates',256,'--save',checkpoint]
                if last is not None:argv+=['--load',last]
                if target in (7424,7680,7936,8192):argv+=['--export-policy',policy]
                cap=min(budget['max_wall_seconds_per_training_run']-(time.monotonic()-begin),budget['max_total_training_wall_seconds']-training_seconds);assert cap>0
                name=f'train-reweighted-{seed}-u{target}';run(name,argv,cap,True);data=read(out/(name+'.log'))
                assert data['start_version']==target-256 and data['version']==target and data['total_transitions']==target*256 and len(data['iterations'])==256
                assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']==sha(checkpoint)
                for row in data['iterations']:
                    assert row['learning_rate']==.0003*max(.1,(8193-row['version'])/8192)
                    assert row['optimizer_steps']==16 and row['transitions']==256 and all(math.isfinite(row[k]) for k in ('loss','entropy','gradient_norm','parameter_delta'))
                if seed==42 and target==256:
                    assert data['iterations'][:64]==pilot_iterations;report['known_pilot_prefix_matches']=True
                completed+=sum(row['completed_episodes'] for row in data['iterations']);record['chunks'].append(dict(version=target,checkpoint_sha256=sha(checkpoint)));last=checkpoint;unchanged()
            remaining=budget['max_wall_seconds_per_training_run']-(time.monotonic()-begin);assert remaining>0
            run(f'starts-reweighted_mean4-{seed}',[dump,6,seed,completed+1],min(120,remaining))
            starts=out/f'starts-reweighted_mean4-{seed}.log';rows=[json.loads(s) for s in starts.read_text().splitlines()];assert len(rows)==completed+1
            actual=native_start(last,seed,6,8192);assert all(actual[k]==rows[actual['episode']][k] for k in ('engine_seed','geometry','ball'))
            members=[];weights=[];headers=[]
            for version in (7424,7680,7936,8192):
                cp=models/f'reweighted-{seed}-u{version}.fppo';fp=models/f'reweighted-{seed}-u{version}.fpol';h,w=decode_policy(fp)
                assert int(h[3])==seed and int(h[4])==64 and h[6]==sha(cp)
                headers.append(h);weights.append(w);members.append(dict(version=version,weight=.25,checkpoint=str(cp),checkpoint_sha256=sha(cp),policy=str(fp),policy_sha256=sha(fp)))
            assert len({h[5] for h in headers})==1
            manifest=models/f'{seed}-provenance.json';write(manifest,dict(schema='within_seed_mean4_v1',seed=seed,members=members,derived_inference_only=True,algorithm='Binary64 fsum,ascending versions,divide by4'))
            averaged=[math.fsum(column)/4 for column in zip(*weights)];assert len(averaged)==8724
            header=headers[0].copy();header[6]=sha(manifest);payload=' '.join(header)+'\n'+''.join(format(x,'.17g')+'\n' for x in averaged)
            derived=models/f'reweighted-mean4-{seed}.fpol';derived.write_text('FPOL1\n'+hashlib.sha256(payload.encode()).hexdigest()+'\n'+payload)
            assert decode_policy(derived)[1]==averaged
            record.update(path=str(last),sha256=sha(last),raw_policy=str(policy),raw_policy_sha256=sha(policy),policy=str(derived),policy_sha256=sha(derived),policy_kind='within_seed_mean4_v1',members=members,provenance_manifest=str(manifest),provenance_sha256=sha(manifest),conservative_episode_starts=completed+1,starts_sha256=sha(starts),training_seconds=time.monotonic()-begin)
            assert record['training_seconds']<=budget['max_wall_seconds_per_training_run']
            records.append(record);write(out/'progress.json',dict(report,training_seconds=training_seconds))
        ids=[tuple(map(int,s.split()[:2]+[s.split()[3]])) for s in cases.read_text().splitlines()]
        for model in records:
            seed=model['seed'];name=f'validation-reweighted_mean4-{seed}';run(name,[binary,'--inference-mode','balanced','--policy',model['policy'],'--inference-cases',cases],300)
            rows=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200 and [(r['index'],r['group'],r['engine_seed']) for r in rows]==ids
            report['validation'].append(dict(seed=seed,goals=sum(r['controlled_score_delta']>0 for r in rows),passes=sum(r['completed_passes']>0 for r in rows),joint=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in rows),groups=[sum(r['controlled_score_delta']>0 for r in rows if r['group']==g) for g in range(5)]));write(out/'progress.json',report)
        cells=report['validation'];total=sum(c['goals'] for c in cells);groups=[sum(c['groups'][g] for c in cells) for g in range(5)]
        gates=dict(mean=total>=970,every_seed=all(c['goals']>=180 for c in cells),groups=all(n>=180 for n in groups),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in cells),original_legacy_improvement=total>=sum(v['legacy']['success_count'] for v in old['validation'])+20)
        report.update(passed=True,validation_passed=all(gates.values()),candidate_mean=total/1000,candidate_group_means=[n/200 for n in groups],gates=gates,selected='reweighted_mean4' if all(gates.values()) else None,confirmation_opened=False)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        try:unchanged()
        except BaseException as error:report.update(passed=False,validation_passed=False,error=str(error))
        report.update(source_after=source_fingerprint(),training_seconds=training_seconds,total_seconds=time.monotonic()-started)
        if resources.exists():report['resources_sha256']=sha(resources)
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','validation_passed','candidate_mean','error')}),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
