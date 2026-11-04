"""Preregistered legacy/broad80 five-seed training and validation, no confirmation."""
import argparse,json,math,os,shlex,shutil,subprocess,sys,time
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
    for name in ('build','quality','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    verified=quality.verify(args.quality/'report.json');before=source_fingerprint();build=args.build.resolve();binary=build/'bin/native_ppo_train'
    prior=ROOT/'.project/native-training/evidence/o22-execution-20261020-a';budget=read(prior/'o23-budget.json')
    assert read(prior/'report.json')['passed'] and budget['configurations']==['legacy','broad80']
    here=Path(__file__).parent;helper=here/'dump_o23_training_starts.cpp'
    cases=ROOT/'.project/native-training/evidence/two-on-one-broad-20261018-a/assessment/cases.txt'
    case_identities=[tuple(map(int,line.split()[:2]+[line.split()[3]])) for line in cases.read_text().splitlines()]
    assert len(case_identities)==200
    draft=ROOT/'.project/optimization/o23-broad-start-protocol-20261020.md'
    files=[Path(__file__),here/'audit_o23_study.py',helper,binary,build/'libfootball_engine.so',args.quality/'report.json',prior/'o23-budget.json',prior/'pilot/full.fppo',prior/'pilot/full.log',cases,draft,
        *[build/n for n in ('libfootball_ppo_evaluation.a','libfootball_ppo_learner.a','libfootball_ppo_math.a','libfootball_native_policy.a','libfootball_categorical_policy.a')],
        build/'CMakeFiles/native_ppo_train.dir/flags.make',build/'CMakeFiles/native_ppo_train.dir/link.txt']
    frozen={str(p.resolve()):sha(p) for p in files};order=[]
    for i,seed in enumerate(SEEDS):
        order.extend((label,seed) for label in (('legacy','broad80') if i%2==0 else ('broad80','legacy')))
    protocol=dict(schema=1,source=before,environment=runtime_identity(sys.executable),frozen=frozen,budget=budget,
        training_order=order,updates_per_chunk=256,chunks=8,selected_checkpoint='Final2048 only; no intermediate validation',
        candidate='20%legacy /80%continuous five uniform geometry families; unchanged reward/network/PPO',
        validation_gates=dict(mean_min=.92,seed_min=.83,group_mean_min=.82,cooperation_min=.2,joint_min=.2,mean_vs_legacy_min=.02),
        confirmation_opened=False,statistics='Validation descriptive point gates only; fresh confirmation occurs separately after selection',
        training_geometry_reconstruction='Episode RNG seed xor0x589965cc75374cc3; completed_episodes+1,possibly one unused final start; native C++ sampler')
    write(out/'protocol.json',protocol)
    for p in (Path(__file__),here/'audit_o23_study.py',helper,draft):shutil.copyfile(p,out/p.name)
    shutil.copyfile(cases,out/'cases.txt');models=out/'models';models.mkdir()
    commands=[];records=[];resource_path=out/'resources.jsonl';training_seconds=0.;started=time.monotonic()
    report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=commands,models=records)
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def unchanged():
        assert source_fingerprint()==before and all(sha(Path(p))==h for p,h in frozen.items()),'Frozen source/tool/artifact changed'
    def disk():return sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    def run(name,argv,remaining,training=False):
        nonlocal training_seconds
        print(name,flush=True);start=time.monotonic();peak=0;reason=None;last_progress=0
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resource_path.open('a') as samples:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                elapsed=time.monotonic()-start
                if elapsed>remaining:reason='wall budget exceeded'
                try:
                    rss=proc.memory_info().rss;peak=max(peak,rss)
                    if rss>budget['max_child_rss_bytes']:reason='RSS budget exceeded'
                    if elapsed-last_progress>=2:
                        cpu=proc.cpu_times();samples.write(json.dumps(dict(command=name,seconds=elapsed,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');samples.flush()
                        last_progress=elapsed
                        if disk()>budget['max_study_output_bytes']:reason='study output budget exceeded'
                except psutil.NoSuchProcess:pass
                if reason:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    break
                time.sleep(.2)
        seconds=time.monotonic()-start
        if training:training_seconds+=seconds
        command=dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=seconds,peak_rss=peak,
            stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr')))
        commands.append(command);write(out/'progress.json',dict(report,training_seconds=training_seconds,active_command=name))
        if reason:raise RuntimeError(name+': '+reason)
        assert child.returncode==0,(name,(out/(name+'.stderr')).read_text())
        return command
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text());obj=out/'starts.o';dump=out/'starts'
        run('compile-starts',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',helper,'-o',obj],120)
        positions=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
        link[positions[0]]=str(obj);link[link.index('-o')+1]=str(dump);run('link-starts',link,120)
        report['starts_binary_sha256']=sha(dump)
        pilot=read(prior/'pilot/full.log');pilot_episodes=1+sum(r['completed_episodes'] for r in pilot['iterations'])
        run('known-pilot-starts',[dump,3,42,pilot_episodes],120)
        known=[json.loads(s) for s in (out/'known-pilot-starts.log').read_text().splitlines()]
        actual=native_start(prior/'pilot/full.fppo',42,3,64);expected=known[actual['episode']]
        assert all(actual[k]==expected[k] for k in ('engine_seed','geometry','ball'))
        report['known_pilot_reconstruction_gate']=True
        for label,seed in order:
            unchanged();run_start=time.monotonic();last=None;iterations=[];record=dict(configuration=label,seed=seed,chunks=[])
            scenario='2v1' if label=='legacy' else '2v1_broad'
            for chunk in range(1,9):
                target=chunk*256;checkpoint=models/f'{label}-{seed}-u{target}.fppo';policy=models/f'{label}-{seed}.fpol'
                argv=[binary,'--scenario',scenario,'--seed',seed,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,
                    '--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0,'--updates',256,'--save',checkpoint]
                if last is not None:argv+=['--load',last]
                if chunk==8:argv+=['--export-policy',policy]
                remaining=min(budget['max_wall_seconds_per_training_run']-(time.monotonic()-run_start),budget['max_total_training_wall_seconds']-training_seconds)
                assert remaining>0,'Registered training budget exhausted'
                name=f'train-{label}-{seed}-u{target}';run(name,argv,remaining,True);data=read(out/(name+'.log'))
                assert data['version']==target and data['total_transitions']==target*256 and data['start_version']==target-256
                assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']==sha(checkpoint)
                assert len(data['iterations'])==256 and all(math.isfinite(r[k]) for r in data['iterations'] for k in ('loss','entropy','clip_fraction','gradient_norm','parameter_delta'))
                iterations.extend(data['iterations']);record['chunks'].append(dict(version=target,checkpoint_sha256=sha(checkpoint)))
                last=checkpoint;unchanged()
            episode_bound=1+sum(r['completed_episodes'] for r in iterations)
            assert sha(dump)==report['starts_binary_sha256']
            name=f'starts-{label}-{seed}';run(name,[dump,3 if label=='legacy' else 4,seed,episode_bound],120)
            rows=[json.loads(line) for line in (out/(name+'.log')).read_text().splitlines()];assert len(rows)==episode_bound
            record.update(path=str(last),sha256=sha(last),policy=str(policy),policy_sha256=sha(policy),
                conservative_episode_starts=episode_bound,starts_sha256=sha(out/(name+'.log')),training_seconds=time.monotonic()-run_start)
            records.append(record);write(out/'progress.json',dict(report,training_seconds=training_seconds))
        validation=[]
        for seed in SEEDS:
            seed_record=dict(seed=seed)
            for label in ('legacy','broad80'):
                model=next(m for m in records if m['seed']==seed and m['configuration']==label)
                name=f'validation-{label}-{seed}';run(name,[binary,'--inference-mode','balanced','--policy',model['policy'],'--inference-cases',cases],300)
                rows=[json.loads(line) for line in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200
                assert [(r['index'],r['group'],r['engine_seed']) for r in rows]==case_identities
                successes=sum(r['controlled_score_delta']>0 for r in rows);passes=sum(r['completed_passes']>0 for r in rows)
                joint=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in rows)
                group_counts=[sum(r['controlled_score_delta']>0 for r in rows if r['group']==g) for g in range(5)]
                seed_record[label]=dict(success=successes/200,cooperation=passes/200,joint=joint/200,
                    groups=[n/40 for n in group_counts],success_count=successes,pass_count=passes,joint_count=joint,group_success_counts=group_counts)
            validation.append(seed_record);report['validation']=validation;write(out/'progress.json',report)
        legacy_count=sum(r['legacy']['success_count'] for r in validation);candidate_count=sum(r['broad80']['success_count'] for r in validation)
        legacy=legacy_count/1000;candidate=candidate_count/1000
        group_counts=[sum(r['broad80']['group_success_counts'][g] for r in validation) for g in range(5)];groups=[n/200 for n in group_counts]
        eligible=(candidate_count>=920 and candidate_count>=legacy_count+20 and all(r['broad80']['success_count']>=166 and r['broad80']['pass_count']>=40 and r['broad80']['joint_count']>=40 for r in validation) and all(n>=164 for n in group_counts))
        report.update(passed=True,validation_passed=eligible,legacy_mean=legacy,candidate_mean=candidate,candidate_group_means=groups,
            selected='broad80' if eligible else None,confirmation_opened=False)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        try:unchanged()
        except BaseException as error:report.update(passed=False,validation_passed=False,error=str(error))
        if 'starts_binary_sha256' in report and sha(dump)!=report['starts_binary_sha256']:report.update(passed=False,validation_passed=False,error='Geometry reconstruction binary changed')
        report.update(source_after=source_fingerprint(),training_seconds=training_seconds,total_seconds=time.monotonic()-started,output_bytes=disk())
        if resource_path.exists():report['resources_sha256']=sha(resource_path)
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','validation_passed','candidate_mean','legacy_mean','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
