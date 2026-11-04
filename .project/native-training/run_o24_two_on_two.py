"""Gated, bounded five-seed exploratory fixed-geometry two-learner 2v2 study."""
import argparse,json,os,random,shlex,subprocess,time
from pathlib import Path
import numpy as np
import psutil
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity

SEEDS=(42,123,2026,31415,271828)
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('confirmation','audit','quality','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();confirmation=read(args.confirmation/'report.json');audit=read(args.audit/'report.json')
    assert confirmation['passed'] and confirmation['confirmation_passed'] and audit['passed'] and audit['confirmation_passed']
    assert audit['report_sha256']==sha(args.confirmation/'report.json')
    before=source_fingerprint();assert before==confirmation['source_after']
    quality.verify(args.quality/'report.json')
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).with_name('o24_two_on_two.cpp');build=args.build.resolve()
    corpus=args.confirmation/'forbidden-engine-seeds.u32le'
    cp=read(args.confirmation/'protocol.json');assert cp['frozen'][str(corpus.resolve())]==sha(corpus)
    excluded=np.fromfile(corpus,dtype='<u4');assert np.all(excluded[:-1]<excluded[1:])
    used={c['engine_seed'] for c in read(args.confirmation/'cases.json')}
    rng=random.Random(20261020026);cases=[]
    while len(cases)<50:
        candidate=rng.randrange(1,2000000001);i=np.searchsorted(excluded,candidate)
        if candidate in used or (i<excluded.size and int(excluded[i])==candidate):continue
        used.add(candidate);cases.append(candidate)
    (out/'cases.txt').write_text(''.join(str(s)+'\n' for s in cases))
    files=[Path(__file__),source,corpus,args.confirmation/'report.json',args.confirmation/'protocol.json',args.confirmation/'cases.json',args.audit/'report.json',args.quality/'report.json',build/'libfootball_engine.so',out/'cases.txt']
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,environment=runtime_identity(os.sys.executable),frozen=frozen,seeds=list(SEEDS),
        updates_per_seed=512,rollout=256,players=2,features_per_player=115,hidden=64,epochs=4,minibatch=64,
        scenario='Fixed geometry,two jointly learned outfield players vs two AI defenders,plus goalkeepers.',
        holdout='50 common new engine seeds; excluded historical/training prefixes and primary confirmation seeds. Geometry fixed,not a geometry generalization test.',
        generation_seed=20261020026,max_wall_seconds_per_seed=900,max_total_child_seconds=4500,max_rss_bytes=512*1024*1024,
        evaluation_modes=['initial_sample','sample','argmax','uniform_random','builtin_ai'],
        analysis='Report every seed and raw case scores,goal rate,truncations,and final sampled minus initial sampled rate. No candidate selection or primary2v1 acceptance inference.',
        limitation='Exploratory512-update budget; failure is retained. A positive difference alone does not establish robust2v2 capability.')
    write(out/'protocol.json',protocol);report=dict(passed=False,learning_claim=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),commands=[],results=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    total=0.
    def unchanged():
        assert source_fingerprint()==before and all(sha(Path(p))==h for p,h in frozen.items())
    def compile_command(name,argv):
        with (out/(name+'.log')).open('w') as stream:r=subprocess.run(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        report['commands'].append(dict(name=name,exit_code=r.returncode,sha256=sha(out/(name+'.log'))));assert r.returncode==0,name
    try:
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        compile_command('compile',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',source,'-o',out/'study.o'])
        positions=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
        link[positions[0]]=str(out/'study.o');link[link.index('-o')+1]=str(out/'study');compile_command('link',link)
        report['binary_sha256']=sha(out/'study')
        with (out/'resources.jsonl').open('w') as resource:
            for seed in SEEDS:
                unchanged();print(f'exploratory-2v2-{seed}',flush=True);started=time.monotonic();peak=0;reason=None
                with (out/f'{seed}.log').open('w') as stream,(out/f'{seed}.stderr').open('w') as errors:
                    child=subprocess.Popen([str(out/'study'),str(seed),str(out/f'model-{seed}'),str(out/'cases.txt')],cwd=out,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
                    while child.poll() is None:
                        elapsed=time.monotonic()-started
                        try:
                            rss=proc.memory_info().rss;peak=max(peak,rss);resource.write(json.dumps(dict(seed=seed,seconds=elapsed,rss=rss,fds=proc.num_fds()))+'\n');resource.flush()
                            if rss>512*1024*1024:reason='RSS budget'
                        except psutil.NoSuchProcess:pass
                        if elapsed>900 or total+elapsed>4500:reason='Wall budget'
                        if reason:child.kill();child.wait();break
                        time.sleep(.5)
                seconds=time.monotonic()-started;total+=seconds
                report['commands'].append(dict(name=f'model-{seed}',exit_code=child.returncode,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/f'{seed}.log'),stderr_sha256=sha(out/f'{seed}.stderr')))
                assert child.returncode==0 and reason is None,(seed,reason)
                native=read(out/f'{seed}.log');assert native['passed'] and native['version']==512 and native['transitions']==131072
                rows={};folder=out/f'model-{seed}'
                for mode in protocol['evaluation_modes']:
                    path=folder/f'{mode}.jsonl';data=[json.loads(s) for s in path.read_text().splitlines()]
                    assert len(data)==50 and [x['engine_seed'] for x in data]==cases
                    rows[mode]=dict(goals=sum(x['score']>0 for x in data),goal_rate=sum(x['score']>0 for x in data)/50,truncated=sum(x['truncated'] for x in data),sha256=sha(path))
                iterations=[json.loads(s) for s in (folder/'iterations.jsonl').read_text().splitlines()]
                assert len(iterations)==512 and [r['version'] for r in iterations]==list(range(1,513))
                report['results'].append(dict(seed=seed,modes=rows,sampled_goal_rate_change=rows['sample']['goal_rate']-rows['initial_sample']['goal_rate'],checkpoint_sha256=sha(folder/'model.fppo'),iterations_sha256=sha(folder/'iterations.jsonl')))
                write(out/'progress.json',report);unchanged()
        report.update(passed=True,total_child_seconds=total,mean_sampled_goal_rate_change=sum(r['sampled_goal_rate_change'] for r in report['results'])/5,
            conclusion='Completed exploratory experiment; assess recorded per-seed rates and limitations. Does not establish general2v2 capability.')
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        try:unchanged()
        except BaseException as error:report.update(passed=False,error=str(error))
        report['source_after']=source_fingerprint();write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','mean_sampled_goal_rate_change','error')}),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
