"""Gated one-hour persistent native learner/resource run; selected models immutable."""
import argparse,json,os,shlex,subprocess,time
from pathlib import Path
import numpy as np
import psutil
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity

BUILD_NAMES={'cc1','cc1plus','clang','clang++','g++','c++','gcc','ld','ld.lld','ninja','make','cmake'}
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('study','confirmation','audit','quality','build','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();confirmation=read(args.confirmation/'report.json');audit=read(args.audit/'report.json');study=read(args.study/'report.json')
    assert confirmation['passed'] and confirmation['confirmation_passed'] and audit['passed'] and audit['confirmation_passed']
    assert audit['report_sha256']==sha(args.confirmation/'report.json') and study['passed'] and study['validation_passed']
    before=source_fingerprint();assert before==confirmation['source_after']==study['source_after']
    verified=quality.verify(args.quality/'report.json');model=next(m for m in study['models'] if m['configuration']=='lowlr_mean4' and m['seed']==42)
    assert sha(Path(model['path']))==model['sha256']
    assert study['selected']=='lowlr_mean4' and model['policy_kind']=='within_seed_mean4_v1'
    assert model['final_version']==8192 and sha(Path(model['policy']))==model['policy_sha256']
    confirmation_protocol=read(args.confirmation/'protocol.json')
    assert confirmation_protocol['study_report_sha256']==sha(args.study/'report.json')
    assert confirmation_protocol['models']['42']['candidate']['sha256']==model['policy_sha256']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();source=Path(__file__).with_name('o24_lowlr_continuous_training.cpp')
    files=[Path(__file__),Path(__file__).with_name('audit_o24_lowlr_stability.py'),source,args.study/'report.json',args.confirmation/'report.json',args.audit/'report.json',args.quality/'report.json',Path(model['path']),build/'libfootball_engine.so']
    files.extend(Path(m[k]) for m in study['models'] for k in ('path','policy'))
    for selected in study['models']:
        files.extend(Path(selected[k]) for k in ('raw_policy','provenance_manifest'))
        files.extend(Path(member[k]) for member in selected['members'] for k in ('checkpoint','policy'))
    files.append(args.confirmation/'protocol.json')
    files.extend(Path(m['candidate']['path']) for m in confirmation_protocol['models'].values())
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,environment=runtime_identity(os.sys.executable),frozen=frozen,model_sha256=model['sha256'],
        derived_inference_policy_sha256=model['policy_sha256'],training_resume_scope='Original schema7 FPPO only;derived mean4 weights are inference-only and remain immutable',duration_seconds=3600,process_wall_cap_seconds=4000,peak_rss_cap_bytes=512*1024*1024,
        warm_window_seconds=[300,600],final_window_seconds=[3300,3600],median_rss_growth_cap_bytes=32*1024*1024,
        final_median_fd_growth_cap=2,absolute_fd_cap=64,minimum_restore_checks=50,
        build_competition='Every second observe process names for build tools outside the training process tree; any observation fails this quiet-run gate.',
        worker_scope='One persistent native learner,no sampler workers; verify no descendants and child reaped.',
        scope='Copy-only stability training. No new policy selection or learning claim; accepted model file remains immutable.')
    write(out/'protocol.json',protocol);env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    commands=[];report=dict(passed=False,protocol_sha256=sha(out/'protocol.json'),source_before=before,quality=verified,commands=commands)
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        def compile_command(name,argv):
            print(name,flush=True)
            with (out/(name+'.log')).open('w') as stream:r=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
            commands.append(dict(name=name,exit_code=r.returncode,sha256=sha(out/(name+'.log'))));assert r.returncode==0,name
        compile_command('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',out/'continuous.o'])
        index=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(index)==1
        link[index[0]]=str(out/'continuous.o');link[link.index('-o')+1]=str(out/'continuous');compile_command('link',link)
        report['binary_sha256']=sha(out/'continuous')
        samples=[];competitors=[];descendants=[];started=time.monotonic();reason=None
        print('persistent-one-hour-training',flush=True)
        with (out/'training.log').open('w') as stream,(out/'training.stderr').open('w') as errors,(out/'resources.jsonl').open('w') as resource:
            child=subprocess.Popen([str(out/'continuous'),'42',model['path'],str(out/'learner-states'),'3600'],cwd=out,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while True:
                pid,status,usage=os.wait4(child.pid,os.WNOHANG)
                if pid:child.returncode=os.waitstatus_to_exitcode(status);break
                elapsed=time.monotonic()-started
                if elapsed>4000:reason='process wall cap exceeded'
                try:
                    children=proc.children(recursive=True);own={child.pid,*[p.pid for p in children]}
                    if children:descendants.extend(p.pid for p in children)
                    builds=[dict(pid=p.pid,name=p.info['name']) for p in psutil.process_iter(['name','status']) if p.pid not in own and p.info['name'] in BUILD_NAMES and p.info['status'] not in (psutil.STATUS_ZOMBIE,psutil.STATUS_DEAD)]
                    if builds:competitors.append(dict(seconds=elapsed,processes=builds))
                    cpu=proc.cpu_times();row=dict(seconds=elapsed,rss=proc.memory_info().rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system)
                    samples.append(row);resource.write(json.dumps(row)+'\n');resource.flush()
                    if row['rss']>protocol['peak_rss_cap_bytes']:reason='RSS cap exceeded'
                    if row['fds']>64:reason='FD cap exceeded'
                except psutil.NoSuchProcess:pass
                if reason:
                    child.kill();pid,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status);break
                time.sleep(1)
        report.update(exit_code=child.returncode,wall_seconds=time.monotonic()-started,peak_rss_bytes=usage.ru_maxrss*1024,
            cpu_seconds=usage.ru_utime+usage.ru_stime,build_observations=competitors,descendant_pids=sorted(set(descendants)),child_reaped=True,
            training_log_sha256=sha(out/'training.log'),resource_log_sha256=sha(out/'resources.jsonl'))
        assert child.returncode==0 and reason is None,(child.returncode,reason,(out/'training.stderr').read_text())
        lines=[json.loads(s) for s in (out/'training.log').read_text().splitlines()];summary=lines.pop()
        assert summary['passed'] and summary['duration_gate'] and summary['seconds']>=3600 and summary['restore_checks']>=50
        assert summary['optimizer_steps']>0 and summary['transitions']>0
        assert all(b['transitions']>a['transitions'] and b['version']>a['version'] for a,b in zip(lines,lines[1:]))
        warm=[r for r in samples if 300<=r['seconds']<=600];late=[r for r in samples if 3300<=r['seconds']<=3600]
        assert len(warm)>=250 and len(late)>=250
        rss_growth=float(np.median([r['rss'] for r in late])-np.median([r['rss'] for r in warm]))
        fd_growth=float(np.median([r['fds'] for r in late])-np.median([r['fds'] for r in warm]))
        gates=dict(duration=True,restore=True,global_lr_floor=summary['learning_rate_floor_verified'],quiet_no_observed_builds=not competitors,no_sampler_workers=not descendants,
            peak_rss=report['peak_rss_bytes']<=512*1024*1024,rss_growth=rss_growth<=32*1024*1024,fd_growth=fd_growth<=2)
        checkpoint_files=sorted((out/'learner-states').glob('*.fppo'));assert len(checkpoint_files)==summary['restore_checks']+1
        report['checkpoint_manifest']={str(path.relative_to(out)):sha(path) for path in checkpoint_files}
        report.update(passed=all(gates.values()),gates=gates,native=summary,median_rss_growth_bytes=rss_growth,median_fd_growth=fd_growth)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen source/tool/model changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','gates','wall_seconds','error')}),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
