"""Read-only context-credit shadow trace; no intervention or training."""
import argparse,json,os,shlex,subprocess,sys,time
from pathlib import Path
import psutil
from validate import ROOT,sha,source_fingerprint
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('study','confirmation','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();study=read(args.study/'report.json');confirmation=read(args.confirmation/'report.json')
    assert study['passed'] and study['validation_passed'] and confirmation['passed'] and not confirmation['confirmation_passed']
    before=source_fingerprint();assert before==study['source_after']==confirmation['source_after']
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    build=args.build.resolve();source=Path(__file__).with_suffix('.cpp').with_name('audit_o23_context_credit.cpp');cases=args.study/'cases.txt'
    files=[Path(__file__),source,cases,args.study/'report.json',args.confirmation/'report.json',build/'libfootball_engine.so']+[Path(m['policy']) for m in study['models']]
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,frozen=frozen,models=5,indices=[40*g+i for g in range(5) for i in range(4)],
        mode='balanced_shadow_reset',maximum_decisions_per_episode=256,wall_seconds_per_command=300,rss_cap_bytes=512*1024*1024,
        comparison='Carried balanced credit versus a fresh shadow action on the same probabilities; trace phase/owner changes and probabilities. No shadow action is executed.',
        scope='100 fixed old-validation episodes; zero updates,zero intervention. Action differences alone are not evidence of harm or a bug.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],results=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    def run(name,argv):
        print(name,flush=True);started=time.monotonic();peak=0;reason=None
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                try:peak=max(peak,proc.memory_info().rss)
                except psutil.NoSuchProcess:pass
                if peak>512*1024*1024:reason='RSS cap'
                if time.monotonic()-started>300:reason='Wall cap'
                if reason:child.kill();child.wait();break
                time.sleep(.2)
        report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=time.monotonic()-started,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
        assert child.returncode==0 and reason is None,(name,reason)
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        run('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',out/'audit.o'])
        positions=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
        link[positions[0]]=str(out/'audit.o');link[link.index('-o')+1]=str(out/'audit');run('link',link)
        report['binary_sha256']=sha(out/'audit')
        for model in study['models']:
            assert sha(Path(model['policy']))==model['policy_sha256'];name=f'parity-{model["seed"]}'
            run(name,[out/'audit',model['policy'],cases,out/f'trace-{model["seed"]}.jsonl']);result=read(out/(name+'.log'))
            assert result['passed'] and result['episodes']==20 and not result['updated_weights'];report['results'].append(dict(seed=model['seed'],**result))
        report.update(passed=True,total_episodes=100,total_decisions=sum(r['decisions'] for r in report['results']),scope=protocol['scope'])
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen source or evidence changed')
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','total_episodes','total_decisions','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
