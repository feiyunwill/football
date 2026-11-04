"""Gated <=30-minute schema5 pilot:64 vs32+32,global LR and strict rejection."""
import argparse,json,math,os,shlex,subprocess,sys,time
from pathlib import Path
import psutil
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity
from audit_o23_study import native_start
def read(p):return json.loads(p.read_text())
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('quality','build','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();verified=quality.verify(args.quality/'report.json');before=source_fingerprint();build=args.build.resolve();binary=build/'bin/native_ppo_train'
    out=args.output.resolve();assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
    helper=Path(__file__).with_name('dump_o23_annealed_starts.cpp');draft=ROOT/'.project/optimization/o23-annealed-training-protocol-20261020.md'
    historical=Path('/root/work_space/football-artifacts/work-o23-study-20261020-a/models/broad80-42-u2048.fppo')
    files=[Path(__file__),helper,Path(__file__).with_name('audit_o23_study.py'),draft,args.quality/'report.json',binary,build/'libfootball_engine.so',historical]
    frozen={str(p.resolve()):sha(p) for p in files}
    protocol=dict(source=before,environment=runtime_identity(sys.executable),frozen=frozen,scenario='2v1_broad_annealed',schema=5,seed=42,
        hidden=64,epochs=4,minibatch=64,rollout=256,cadence=10,episode_limit=256,updates=64,split=[32,32],
        lr='0.0003*max(0.1,1-global_update_version_before_step/8192)',wall_cap_seconds=1800,observed_child_rss_cap_bytes=512*1024*1024,output_cap_bytes=256*1024*1024,
        full_study_registered_per_seed_seconds=5113,scope='Infrastructure and cost pilot,no learning-performance acceptance and no validation cases opened.')
    write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=verified,commands=[])
    env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    started=time.monotonic();resource=out/'resources.jsonl'
    def run(name,argv,expected_failure=False):
        print(name,flush=True);begin=time.monotonic();peak=0;reason=None
        with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resource.open('a') as samples:
            child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
            while child.poll() is None:
                try:
                    rss=proc.memory_info().rss;peak=max(peak,rss);cpu=proc.cpu_times();samples.write(json.dumps(dict(command=name,seconds=time.monotonic()-begin,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');samples.flush()
                    if rss>512*1024*1024:reason='RSS budget'
                except psutil.NoSuchProcess:pass
                if time.monotonic()-started>1800:reason='30-minute budget'
                if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>256*1024*1024:reason='Output budget'
                if reason:child.kill();child.wait();break
                time.sleep(.2)
        seconds=time.monotonic()-begin;report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,expected_failure=expected_failure,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))))
        assert reason is None and ((child.returncode!=0) if expected_failure else child.returncode==0),(name,reason)
        return seconds
    try:
        common=[binary,'--scenario','2v1_broad_annealed','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0]
        full_seconds=run('full64',[*common,'--updates',64,'--save',out/'full.fppo','--export-policy',out/'full.fpol'])
        run('prefix32',[*common,'--updates',32,'--save',out/'prefix.fppo'])
        run('resume32',[*common,'--updates',32,'--load',out/'prefix.fppo','--save',out/'resumed.fppo','--export-policy',out/'resumed.fpol'])
        full,prefix,resumed=[read(out/(name+'.log')) for name in ('full64','prefix32','resume32')]
        assert (out/'full.fppo').read_bytes()==(out/'resumed.fppo').read_bytes() and (out/'full.fpol').read_bytes()==(out/'resumed.fpol').read_bytes()
        assert full['iterations'][:32]==prefix['iterations'] and full['iterations'][32:]==resumed['iterations']
        assert full['version']==resumed['version']==64 and resumed['start_version']==32 and full['total_transitions']==16384
        for data in (full,prefix,resumed):
            assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']
            for row in data['iterations']:
                assert row['learning_rate']==.0003*max(.1,1-(row['version']-1)/8192)
                assert all(math.isfinite(row[k]) for k in ('loss','entropy','gradient_norm','parameter_delta'))
        assert full['state_sha256']==sha(out/'full.fppo') and int.from_bytes((out/'full.fppo').read_bytes()[44:48],'little')==5
        constant=common.copy();constant[2]='2v1_broad'
        run('reject-new-task-as-constant',[*constant,'--updates',0,'--load',out/'full.fppo'],True)
        assert report['commands'][-1]['exit_code']==1
        assert 'variation/schema mismatch' in (out/'reject-new-task-as-constant.stderr').read_text()
        run('reject-historical-source',[*constant,'--updates',0,'--load',historical],True)
        historical_error=(out/'reject-historical-source.stderr').read_text()
        assert report['commands'][-1]['exit_code']==1 and 'Incompatible training build or runtime dimensions' in historical_error
        flags={}
        for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
            if ' = ' in line:k,v=line.split(' = ',1);flags[k]=shlex.split(v)
        link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text())
        run('compile-starts',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',helper,'-o',out/'starts.o'])
        positions=[i for i,a in enumerate(link) if a.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
        link[positions[0]]=str(out/'starts.o');link[link.index('-o')+1]=str(out/'starts');run('link-starts',link)
        count=1+sum(row['completed_episodes'] for row in full['iterations']);run('pilot-starts',[out/'starts',5,42,count])
        starts=[json.loads(s) for s in (out/'pilot-starts.log').read_text().splitlines()];assert len(starts)==count
        actual=native_start(out/'full.fppo',42,5,64);expected=starts[actual['episode']];assert all(actual[k]==expected[k] for k in ('engine_seed','geometry','ball'))
        projected=full_seconds*128;assert projected<=5113,'Short measured cost exceeds registered full-study per-seed cap'
        report.update(passed=True,resume_bytes_equal=True,policy_bytes_equal=True,iterations_equal=True,global_lr_verified=True,task_schema_rejected=True,historical_source_rejected=True,
            historical_rejection=historical_error.strip(),native_start_reconstructed=True,conservative_starts=count,full_seconds=full_seconds,transitions_per_second=16384/full_seconds,projected8192_seconds=projected,
            checkpoint_sha256=sha(out/'full.fppo'),policy_sha256=sha(out/'full.fpol'),starts_binary_sha256=sha(out/'starts'))
    except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint();report['total_seconds']=time.monotonic()-started
        if before!=report['source_after'] or any(sha(Path(p))!=h for p,h in frozen.items()):report.update(passed=False,error='Frozen source or evidence changed')
        if resource.exists():report['resources_sha256']=sha(resource)
        write(out/'report.json',report)
    print(json.dumps({k:report.get(k) for k in ('passed','full_seconds','projected8192_seconds','error')}),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
