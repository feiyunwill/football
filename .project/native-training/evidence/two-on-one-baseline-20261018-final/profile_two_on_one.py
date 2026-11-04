"""Thirty-minute actual 2v1 learner soak, observed-load gates and FPPO resume."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import shutil
import subprocess
import sys
import time
import numpy as np
import quality
from profile_quiet_ppo import HostMonitor
from validate import ROOT,sha,source_fingerprint

def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def quiet(value):
    return not value['compiler_seen'] and all(value[k]<=.25 for k in
        ('foreign_mean_cores','foreign_p95_cores','index_mean_cores','index_p95_cores'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('build-root','work-root','output','quality','study'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--smoke',action='store_true',help='Two-second tooling check; never a duration acceptance')
    args=parser.parse_args();build=args.build_root.resolve();work=args.work_root.resolve();output=args.output.resolve()
    assert ROOT not in work.parents and work!=ROOT
    accepted=quality.verify(args.quality);study=read(args.study/'report.json')
    assert study['passed'] and study['learning_passed'] and study['source_before']==study['source_after']==source_fingerprint()
    selected=study['tasks']['2v1']['selected'];assert selected in ('sparse64','checkpoints64')
    work.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    here=Path(__file__).resolve().parent;source=here/'soak_two_on_one.cpp'
    tools=[Path(__file__),source,here/'profile_quiet_ppo.py',here/'validate.py',here/'quality.py']
    requested=2 if args.smoke else 1800
    protocol=dict(minimum_seconds=requested,smoke_only=args.smoke,preflight_seconds=10,
        task='2v1',learned_players=1,native_agents=2,fixed_teammate_action=19,seed=424242,hidden=64,
        rollout=256,epochs=4,minibatch=64,cadence=10,episode_limit=256,selected=selected,
        maximum_foreign_mean_cores=.25,maximum_foreign_p95_cores=.25,maximum_index_mean_cores=.25,
        maximum_index_p95_cores=.25,foreign_compilers_allowed=0,maximum_steady_rss_growth_bytes=32*1024*1024,maximum_fd_range=4,
        fd_gate='After actual learner destruction equals process-global-cache-primed baseline; priming1024 transitions excluded from duration',
        snapshot_gate='Actual final FPPO fresh-process frozen evaluation and resumed update bytes equal reference continuation',
        source_sha256=source_fingerprint()['sha256'],quality=accepted,study_report_sha256=sha(args.study/'report.json'),
        tooling={p.name:sha(p) for p in tools})
    write(output/'protocol.json',protocol)
    for tool in tools:(output/tool.name).write_bytes(tool.read_bytes())
    report=dict(passed=False,smoke_passed=False,source_before=source_fingerprint(),commands=[],environment_passed=False,
        binary_sha256=sha(build/'bin/native_ppo_train'),core_sha256=sha(build/'libfootball_engine.so'),
        protocol_sha256=sha(output/'protocol.json'),scope='One actual2v1 PpoLearner with one learned player and fixed builtin-AI teammate; observed WSL load, not physical host isolation; no worker-scaling inference')
    env=dict(os.environ,GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'),LD_LIBRARY_PATH=str(build))
    process=None
    def run(name,argv,timeout=300):
        print(name,flush=True)
        with (output/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=result.returncode,sha256=sha(output/(name+'.log'))))
        if result.returncode:raise RuntimeError(name+' failed; raw evidence retained')
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:
                key,value=line.split(' = ',1);flags[key]=shlex.split(value)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        obj=work/'soak.o';binary=work/'soak'
        run('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',obj])
        indexes=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(indexes)==1
        link[indexes[0]]=str(obj);link[link.index('-o')+1]=str(binary);run('link',link)
        run('linkage',['ldd',binary]);linkage=(output/'linkage.log').read_text()
        assert all(s not in linkage for s in ('libpython','libgame.so','_gameplayfootball','not found'))
        report['soak_binary_sha256']=sha(binary)
        print('preflight',flush=True)
        with HostMonitor() as preflight:time.sleep(10)
        initial=preflight.report();write(output/'preflight.json',initial)
        if not quiet(initial):raise RuntimeError('Preflight foreign-load gate failed')
        print('actual-two-on-one-soak',flush=True)
        with HostMonitor() as monitor,(output/'soak.log').open('w') as log:
            process=subprocess.Popen([str(binary),str(requested),str(work),str(int(selected=='checkpoints64'))],cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT)
            interrupted=False
            while process.poll() is None:
                if monitor.compiler_seen and not interrupted:
                    process.send_signal(signal.SIGINT);interrupted=True
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:pass
        host=monitor.report();write(output/'host-load.json',host)
        report['commands'].append(dict(name='soak',argv=[str(binary),str(requested),str(work),str(int(selected=='checkpoints64'))],exit_code=process.returncode,sha256=sha(output/'soak.log')))
        report.update(process_exit=process.returncode,process_reaped=True,environment_passed=quiet(host))
        assert process.returncode==0 and quiet(host)
        native=read(work/'native.json');assert native['passed'] and native['duration_seconds']>=requested
        assert native['players']==1 and native['native_agents']==2 and native['hidden']==64
        assert native['transitions']==native['updates']*256 and native['fd_before']==native['fd_after']
        assert args.smoke or (native['practice_episodes']==0 and native['cooperative_episodes']>0)
        rows=[json.loads(line) for line in (work/'minute.jsonl').read_text().splitlines()]
        assert rows and all(r['elapsed']>0 and r['transitions']==r['updates']*256 for r in rows)
        assert args.smoke or len(rows)>=30
        growth=rows[-1]['rss']-rows[0]['rss'];assert growth<=protocol['maximum_steady_rss_growth_bytes']
        assert max(r['fds'] for r in rows)-min(r['fds'] for r in rows)<=protocol['maximum_fd_range']
        write(output/'native.json',native);(output/'minute.jsonl').write_bytes((work/'minute.jsonl').read_bytes())
        parameters=['--scenario','2v1','--seed','424242','--hidden','64','--epochs','4','--minibatch','64',
                    '--rollout','256','--cadence','10','--episode-limit','256','--no-initial-eval']
        if selected=='checkpoints64':parameters+=['--checkpoints']
        cli=build/'bin/native_ppo_train';saved=work/'final.fppo';resumed=work/'cli-resume.fppo'
        run('fresh-frozen',[cli,*parameters,'--updates','0','--eval-partition','validation','--eval-seed','99173','--eval-episodes','2','--eval-steps','256','--load',saved])
        frozen=read(output/'fresh-frozen.log')
        assert frozen['evaluation']['isolated'] and frozen['state_before_evaluation_sha256']==frozen['state_sha256']==sha(saved)
        run('fresh-resume',[cli,*parameters,'--updates','1','--eval-episodes','0','--load',saved,'--save',resumed])
        continuation=read(output/'fresh-resume.log')
        assert len(continuation['iterations'])==1 and continuation['version']==native['updates']+1
        assert resumed.read_bytes()==(work/'expected-resume.fppo').read_bytes()
        checkpoint_files={}
        for path in (saved,resumed,work/'expected-resume.fppo'):
            shutil.copyfile(path,output/path.name);assert sha(path)==sha(output/path.name)
            checkpoint_files[path.name]=sha(path)
        report.update(smoke_passed=True,passed=not args.smoke,native=native,
            memory=dict(first=rows[0]['rss'],last=rows[-1]['rss'],peak=max(r['rss'] for r in rows),steady_growth=growth),
            fds=dict(before=native['fd_before'],after=native['fd_after'],minimum=min(r['fds'] for r in rows),maximum=max(r['fds'] for r in rows)),
            minute_tps=dict(zip(('p10','median','p90'),map(float,np.percentile([r['tps'] for r in rows],[10,50,90])))),
            final_checkpoint=str(saved),final_checkpoint_sha256=sha(saved),resumed_checkpoint=str(resumed),resumed_checkpoint_sha256=sha(resumed),
            expected_resume=str(work/'expected-resume.fppo'),frozen_isolated=True,resumed_bytes_equal=True,checkpoint_files=checkpoint_files)
    except BaseException as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
        report['source_after']=source_fingerprint()
        if report['source_after']!=report['source_before'] or any(sha(p)!=protocol['tooling'][p.name] for p in tools) or sha(build/'bin/native_ppo_train')!=report['binary_sha256'] or sha(build/'libfootball_engine.so')!=report['core_sha256']:
            report.update(passed=False,smoke_passed=False,error='Source, native artifacts or tooling changed')
        write(output/'report.json',report)
    print(json.dumps({k:report[k] for k in ('passed','smoke_passed','environment_passed','error') if k in report}),flush=True)
    return 0 if report['passed'] or (args.smoke and report['smoke_passed']) else 1

if __name__=='__main__':raise SystemExit(main())
