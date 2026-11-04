"""One controlled phase-reset intervention,old validation only,zero training."""
import argparse,json,os,shlex,subprocess,time
from pathlib import Path
import psutil
from validate import ROOT,sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('study','context','audit','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();study=read(args.study/'report.json');context=read(args.context/'report.json');audit=read(args.audit/'report.json')
    assert study['passed'] and study['validation_passed'] and context['passed'] and audit['passed'] and audit['report_sha256']==sha(args.context/'report.json')
    before=source_fingerprint();assert before==study['source_after']==context['source_after']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).with_name('o23_phase_reset.cpp');build=args.build.resolve();cases=args.study/'cases.txt'
    files=[Path(__file__),source,ROOT/'.project/optimization/o23-phase-reset-protocol-20261020.md',args.study/'report.json',args.context/'report.json',args.audit/'report.json',cases,build/'libfootball_engine.so']
    files.extend(Path(m['policy']) for m in study['models']);files.extend(args.study/f'validation-{m["seed"]}.log' for m in study['models'])
    frozen={str(p.resolve()):sha(p) for p in files};protocol=dict(source=before,frozen=frozen,study=str(args.study.resolve()),modes=['balanced','phase_reset'],optimizer_updates=0,
        rule='Reset balanced credit exactly once,on first observed completed_passes0->positive,before next decision.',
        total_goal_min=970,seed_and_group_goal_min=180,pass_and_joint_min=40,improvement_vs_mean4_min=10,max_child_seconds=300,max_total_seconds=3600,max_child_rss_bytes=512*1024*1024,max_output_bytes=128*1024*1024)
    write(out/'protocol.json',protocol);report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],cells=[],optimizer_updates=0)
    started=time.monotonic();env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def run(name,argv,cap=300):
        print(name,flush=True);begin=time.monotonic();peak=0;reason=None
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                try:peak=max(peak,proc.memory_info().rss)
                except psutil.NoSuchProcess:pass
                if peak>512*1024*1024:reason='RSS budget'
                if time.monotonic()-begin>cap or time.monotonic()-started>3600:reason='Wall budget'
                if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>128*1024*1024:reason='Output budget'
                if reason:child.kill();child.wait();break
                time.sleep(.2)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=time.monotonic()-begin,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert child.returncode==0 and reason is None,(name,reason)
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        run('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',out/'phase.o'],180)
        positions=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
        link[positions[0]]=str(out/'phase.o');link[link.index('-o')+1]=str(out/'phase');run('link',link,180);report['binary_sha256']=sha(out/'phase')
        for model in study['models']:
            seed=model['seed'];assert sha(Path(model['policy']))==model['policy_sha256']
            original=[json.loads(s) for s in (args.study/f'validation-{seed}.log').read_text().splitlines()][:-1]
            for mode in ('balanced','phase_reset'):
                name=f'{seed}-{mode}';run(name,[out/'phase',model['policy'],cases,mode]);rows=[json.loads(s) for s in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop()
                assert summary['complete'] and len(rows)==200 and summary['policy_sha256']==model['policy_sha256']
                assert [(r['index'],r['group'],r['engine_seed']) for r in rows]==[(r['index'],r['group'],r['engine_seed']) for r in original]
                if mode=='balanced':assert rows==original and summary['phase_resets']==0,'Baseline path changed'
                else:assert 0<=summary['phase_resets']<=200
                report['cells'].append(dict(seed=seed,mode=mode,goals=sum(r['controlled_score_delta']>0 for r in rows),passes=sum(r['completed_passes']>0 for r in rows),joint=sum(r['completed_passes']>0 and r['controlled_score_delta']>0 for r in rows),groups=[sum(r['controlled_score_delta']>0 for r in rows if r['group']==g) for g in range(5)],resets=summary['phase_resets']))
                write(out/'progress.json',report)
        base=[c for c in report['cells'] if c['mode']=='balanced'];candidate=[c for c in report['cells'] if c['mode']=='phase_reset'];a=sum(c['goals'] for c in base);b=sum(c['goals'] for c in candidate);groups=[sum(c['groups'][g] for c in candidate) for g in range(5)]
        gates=dict(mean=b>=970,every_seed=all(c['goals']>=180 for c in candidate),groups=all(n>=180 for n in groups),cooperation=all(c['passes']>=40 and c['joint']>=40 for c in candidate),improvement=b>=a+10)
        report.update(passed=True,validation_passed=all(gates.values()),baseline_mean=a/1000,candidate_mean=b/1000,gates=gates,confirmation_opened=False)
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint();report['total_seconds']=time.monotonic()-started
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,validation_passed=False,error='Frozen source or evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','validation_passed','baseline_mean','candidate_mean','gates','error')}),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
