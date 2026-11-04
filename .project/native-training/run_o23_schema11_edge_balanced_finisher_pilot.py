"""Schema11 edge-balanced-finisher 64-update/resume pilot, capped at 30 minutes."""
import argparse,json,math,os,psutil,shlex,subprocess,sys,time
from pathlib import Path
import quality
from audit_o23_study import native_start
from validate import ROOT,sha,source_fingerprint,runtime_identity

def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('quality','build','output'):parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();verified=quality.verify(args.quality/'report.json');before=source_fingerprint();build=args.build.resolve();binary=build/'bin/native_ppo_train';out=args.output.resolve()
  assert out!=ROOT and ROOT not in out.parents;out.mkdir(parents=True,exist_ok=False)
  helper=Path(__file__).with_name('dump_o23_schema11_finisher_starts.cpp');draft=ROOT/'.project/optimization/o23-schema11-edge-balanced-finisher-preregistration-20261028.md'
  schema9=Path('/root/work_space/football-artifacts/work-o23-schema9-finisher-pilot-20261027-a/full.fppo')
  files=[Path(__file__),helper,Path(__file__).with_name('audit_o23_study.py'),Path(__file__).with_name('audit_o23_schema11_finisher_pilot.py'),draft,args.quality/'report.json',binary,build/'libfootball_engine.so',schema9]
  frozen={str(path.resolve()):sha(path) for path in files};protocol=dict(source=before,environment=runtime_identity(sys.executable),frozen=frozen,scenario='2v1_broad_edge_balanced_finisher',schema=11,seed=42,hidden=64,epochs=4,minibatch=64,rollout=256,cadence=10,episode_limit=256,updates=64,split=[32,32],lr='.0003*max(.1,1-global_version_before_update/8192)',wall_cap_seconds=1800,rss_cap_bytes=512*1024*1024,output_cap_bytes=256*1024*1024,scope='Infrastructure/cost pilot only; no validation or confirmation cases.')
  write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=verified,commands=[]);started=time.monotonic();resources=out/'resources.jsonl';env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  def run(name,argv,expected_failure=False):
    print(name,flush=True);begin=time.monotonic();peak=0;reason=None
    with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resources.open('a') as sample:
      child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
      while child.poll() is None:
        elapsed=time.monotonic()-begin
        try:
          rss=proc.memory_info().rss;peak=max(peak,rss);cpu=proc.cpu_times();sample.write(json.dumps(dict(command=name,seconds=elapsed,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');sample.flush()
          if rss>protocol['rss_cap_bytes']:reason='RSS budget'
        except psutil.NoSuchProcess:pass
        if time.monotonic()-started>protocol['wall_cap_seconds']:reason='30-minute budget'
        if sum(path.stat().st_size for path in out.rglob('*') if path.is_file())>protocol['output_cap_bytes']:reason='Output budget'
        if reason:child.kill();child.wait();break
        time.sleep(.2)
    seconds=time.monotonic()-begin;report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,expected_failure=expected_failure,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert reason is None and (child.returncode!=0 if expected_failure else child.returncode==0),(name,reason);return seconds
  try:
    common=[binary,'--scenario','2v1_broad_edge_balanced_finisher','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval']
    full_seconds=run('full64',[*common,'--eval-episodes',0,'--updates',64,'--save',out/'full.fppo','--export-policy',out/'full.fpol']);run('prefix32',[*common,'--eval-episodes',0,'--updates',32,'--save',out/'prefix.fppo']);run('resume32',[*common,'--eval-episodes',0,'--updates',32,'--load',out/'prefix.fppo','--save',out/'resumed.fppo','--export-policy',out/'resumed.fpol'])
    full,prefix,resumed=[read(out/(name+'.log')) for name in ('full64','prefix32','resume32')];assert (out/'full.fppo').read_bytes()==(out/'resumed.fppo').read_bytes() and (out/'full.fpol').read_bytes()==(out/'resumed.fpol').read_bytes();assert full['iterations'][:32]==prefix['iterations'] and full['iterations'][32:]==resumed['iterations'];assert full['version']==resumed['version']==64 and resumed['start_version']==32 and full['total_transitions']==16384
    for data in (full,prefix,resumed):
      assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']
      for row in data['iterations']:assert row['learning_rate']==.0003*max(.1,1-(row['version']-1)/8192) and all(math.isfinite(row[key]) for key in ('loss','entropy','gradient_norm','parameter_delta'))
    assert full['state_sha256']==sha(out/'full.fppo') and int.from_bytes((out/'full.fppo').read_bytes()[44:48],'little')==11
    run('reject-schema9',[*common,'--eval-episodes',0,'--updates',0,'--load',schema9],True);assert 'variation/schema mismatch' in (out/'reject-schema9.stderr').read_text()
    run('pilot-holdout-eval',[*common,'--updates',0,'--load',out/'full.fppo','--eval-partition','holdout','--eval-seed',904729,'--eval-episodes',64,'--eval-steps',256]);pilot_eval=read(out/'pilot-holdout-eval.log');assert pilot_eval['evaluation']['isolated'] and pilot_eval['state_before_evaluation_sha256']==pilot_eval['state_sha256'];pilot_cases={row['name']:row['episodes'] for row in pilot_eval['evaluation']['strategies']};assert all(len(pilot_cases[name])==64 for name in ('sample','argmax'));write(out/'pilot-holdout-cases.json',dict(partition='holdout',evaluation_seed=904729,episodes=64,case_set='schema11-pilot-only-holdout-v1',strategies=pilot_cases))
    flags={}
    for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
      if ' = ' in line:key,value=line.split(' = ',1);flags[key]=shlex.split(value)
    link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text());run('compile-starts',[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',helper,'-o',out/'starts.o']);positions=[i for i,arg in enumerate(link) if arg.endswith('native_ppo_train.cpp.o')];assert len(positions)==1;link[positions[0]]=str(out/'starts.o');link[link.index('-o')+1]=str(out/'starts');run('link-starts',link)
    count=1+sum(row['completed_episodes'] for row in full['iterations']);run('pilot-starts',[out/'starts',11,42,count]);starts=[json.loads(line) for line in (out/'pilot-starts.log').read_text().splitlines()];actual=native_start(out/'full.fppo',42,11,64);assert len(starts)==count and all(actual[key]==starts[actual['episode']][key] for key in ('engine_seed','geometry','ball'))
    report.update(pilot_holdout_case_set_sha256=sha(out/'pilot-holdout-cases.json'),pilot_holdout_case_set='schema11-pilot-only-holdout-v1',pilot_holdout_partition='holdout',pilot_holdout_metrics={name:dict(episodes=len(rows),goals=sum(row['controlled_score_delta'] for row in rows),completed_passes=sum(row['completed_passes'] for row in rows),joint=sum(row['completed_passes']>0 and row['controlled_score_delta']>0 for row in rows)) for name,rows in pilot_cases.items()});
    report.update(passed=True,resume_bytes_equal=True,policy_bytes_equal=True,iterations_equal=True,global_lr_verified=True,schema9_rejected=True,native_start_reconstructed=True,conservative_starts=count,full_seconds=full_seconds,transitions_per_second=16384/full_seconds,projected8192_seconds=full_seconds*128,checkpoint_sha256=sha(out/'full.fppo'),policy_sha256=sha(out/'full.fpol'),starts_binary_sha256=sha(out/'starts'))
  except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
  finally:
    report['source_after']=source_fingerprint();report['total_seconds']=time.monotonic()-started
    if before!=report['source_after'] or any(sha(Path(path))!=digest for path,digest in frozen.items()):report.update(passed=False,error='Frozen source or evidence changed')
    if resources.exists():report['resources_sha256']=sha(resources)
    write(out/'report.json',report)
  print(json.dumps({key:report.get(key) for key in ('passed','full_seconds','projected8192_seconds','error')}),flush=True);return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
