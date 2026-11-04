"""Second bounded candidate: all five broad80 models,2048 to8192,no interim eval."""
import argparse,json,math,os,shutil,subprocess,sys,time
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
    for key in ('study','audit','diagnosis','quality','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();previous=read(args.study/'report.json');audit=read(args.audit/'report.json');diagnosis=read(args.diagnosis/'report.json')
    assert previous['passed'] and not previous['validation_passed'] and audit['passed'] and not audit['validation_passed'] and diagnosis['passed']
    assert audit['report_sha256']==sha(args.study/'report.json') and not previous['confirmation_opened']
    before=source_fingerprint();assert before==previous['source_after']==diagnosis['source_after']
    verified=quality.verify(args.quality/'report.json');old_protocol=read(args.study/'protocol.json')
    assert all(sha(Path(p))==h for p,h in old_protocol['frozen'].items())
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();binary=build/'bin/native_ppo_train';dump=args.study/'starts';here=Path(__file__).parent
    cases=args.study/'cases.txt';draft=ROOT/'.project/optimization/o23-extended-budget-protocol-20261020.md'
    files=[Path(__file__),here/'audit_o23_extended.py',here/'audit_o23_study.py',draft,args.study/'report.json',args.study/'protocol.json',args.audit/'report.json',args.diagnosis/'report.json',args.quality/'report.json',binary,build/'libfootball_engine.so',dump,cases]
    files.extend(Path(m[k]) for m in previous['models'] for k in ('path','policy'))
    frozen={str(p.resolve()):sha(p) for p in files}
    budget=dict(max_wall_seconds_per_training_run=4200,max_total_training_wall_seconds=21000,max_child_rss_bytes=512*1024*1024,max_study_output_bytes=2*1024**3)
    protocol=dict(schema=2,source=before,environment=runtime_identity(sys.executable),frozen=frozen,budget=budget,predecessor=str(args.study.resolve()),predecessor_audit=str(args.audit.resolve()),diagnosis=str(args.diagnosis.resolve()),
        training_order=[['broad80',s] for s in SEEDS],initial_version=2048,final_version=8192,updates_per_chunk=256,chunks=24,
        selected_checkpoint='Final8192 only;all five seeds,no intermediate evaluation',candidate='broad80 extended budget;unchanged distribution,reward,PPO,network,and balanced inference',
        comparator='Audited legacy2048;unequal compute,not an efficiency claim',validation_gates=dict(mean_min=.92,seed_min=.83,group_mean_min=.82,cooperation_min=.2,joint_min=.2,mean_vs_legacy_min=.02),confirmation_opened=False)
    write(out/'protocol.json',protocol)
    for p in (Path(__file__),here/'audit_o23_extended.py',draft):shutil.copyfile(p,out/p.name)
    shutil.copyfile(cases,out/'cases.txt');models=out/'models';models.mkdir()
    commands=[];records=[];training_seconds=0.;started=time.monotonic();resources=out/'resources.jsonl'
    report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=commands,models=records,predecessor_report_sha256=sha(args.study/'report.json'))
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def unchanged():assert source_fingerprint()==before and all(sha(Path(p))==h for p,h in frozen.items()),'Frozen source or evidence changed'
    def run(name,argv,cap,training=False):
        nonlocal training_seconds
        print(name,flush=True);start=time.monotonic();peak=0;reason=None;last_sample=0
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resources.open('a') as samples:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                elapsed=time.monotonic()-start
                if elapsed>cap:reason='Wall budget'
                try:
                    rss=proc.memory_info().rss;peak=max(peak,rss)
                    if rss>budget['max_child_rss_bytes']:reason='RSS budget'
                    if elapsed-last_sample>=2:
                        cpu=proc.cpu_times();samples.write(json.dumps(dict(command=name,seconds=elapsed,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');samples.flush();last_sample=elapsed
                        if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>budget['max_study_output_bytes']:reason='Output budget'
                except psutil.NoSuchProcess:pass
                if reason:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    break
                time.sleep(.2)
        seconds=time.monotonic()-start
        if training:training_seconds+=seconds
        commands.append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=seconds,peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
        write(out/'progress.json',dict(report,active_command=name,training_seconds=training_seconds))
        assert reason is None and child.returncode==0,(name,reason)
    try:
        for seed in SEEDS:
            unchanged();old=next(m for m in previous['models'] if m['seed']==seed and m['configuration']=='broad80')
            last=Path(old['path']);iterations=[];run_start=time.monotonic();record=dict(configuration='broad80',seed=seed,chunks=[],initial_model_sha256=old['sha256'],initial_version=2048,final_version=8192)
            for target in range(2304,8193,256):
                checkpoint=models/f'broad80-{seed}-u{target}.fppo';policy=models/f'broad80-{seed}.fpol'
                argv=[binary,'--scenario','2v1_broad','--seed',seed,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0,'--updates',256,'--load',last,'--save',checkpoint]
                if target==8192:argv+=['--export-policy',policy]
                cap=min(4200-(time.monotonic()-run_start),21000-training_seconds);assert cap>0
                name=f'train-broad80-{seed}-u{target}';run(name,argv,cap,True);d=read(out/(name+'.log'))
                assert d['start_version']==target-256 and d['version']==target and d['total_transitions']==target*256 and len(d['iterations'])==256
                assert d['evaluation']['isolated'] and d['state_before_evaluation_sha256']==d['state_sha256']==sha(checkpoint)
                assert all(math.isfinite(r[k]) for r in d['iterations'] for k in ('loss','entropy','clip_fraction','gradient_norm','parameter_delta'))
                iterations.extend(d['iterations']);record['chunks'].append(dict(version=target,checkpoint_sha256=sha(checkpoint)));last=checkpoint;unchanged()
            episode_bound=old['conservative_episode_starts']+sum(r['completed_episodes'] for r in iterations)
            run(f'starts-broad80-{seed}',[dump,4,seed,episode_bound],120)
            actual=native_start(last,seed,4,8192);rows=[json.loads(s) for s in (out/f'starts-broad80-{seed}.log').read_text().splitlines()]
            assert len(rows)==episode_bound and all(actual[k]==rows[actual['episode']][k] for k in ('engine_seed','geometry','ball'))
            record.update(path=str(last),sha256=sha(last),policy=str(policy),policy_sha256=sha(policy),conservative_episode_starts=episode_bound,starts_sha256=sha(out/f'starts-broad80-{seed}.log'),training_seconds=time.monotonic()-run_start)
            records.append(record);write(out/'progress.json',dict(report,training_seconds=training_seconds))
        validation=[]
        for seed in SEEDS:
            old_row=next(r for r in previous['validation'] if r['seed']==seed);model=next(m for m in records if m['seed']==seed)
            name=f'validation-broad80-{seed}';run(name,[binary,'--inference-mode','balanced','--policy',model['policy'],'--inference-cases',cases],300)
            rows=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200
            success=sum(r['controlled_score_delta']>0 for r in rows);passes=sum(r['completed_passes']>0 for r in rows);joint=sum(r['controlled_score_delta']>0 and r['completed_passes']>0 for r in rows)
            groups=[sum(r['controlled_score_delta']>0 for r in rows if r['group']==g) for g in range(5)]
            validation.append(dict(seed=seed,legacy=old_row['legacy'],broad80=dict(success=success/200,cooperation=passes/200,joint=joint/200,groups=[n/40 for n in groups],success_count=success,pass_count=passes,joint_count=joint,group_success_counts=groups)))
            report['validation']=validation;write(out/'progress.json',report)
        a=sum(r['legacy']['success_count'] for r in validation);b=sum(r['broad80']['success_count'] for r in validation);g=[sum(r['broad80']['group_success_counts'][i] for r in validation) for i in range(5)]
        eligible=b>=920 and b>=a+20 and all(r['broad80']['success_count']>=166 and r['broad80']['pass_count']>=40 and r['broad80']['joint_count']>=40 for r in validation) and all(n>=164 for n in g)
        report.update(passed=True,validation_passed=eligible,legacy_mean=a/1000,candidate_mean=b/1000,candidate_group_means=[n/200 for n in g],selected='broad80' if eligible else None,confirmation_opened=False)
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
