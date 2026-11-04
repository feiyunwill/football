"""Frozen Schema12 entropy-stable-finisher scheduled-checkpoint five-seed study with independent acceptance cases."""
import argparse,hashlib,json,math,os,psutil,shlex,shutil,subprocess,sys,time
from pathlib import Path
import quality
from run_o23_averaging import policy as decode_policy
from audit_o23_study import native_start
from validate import ROOT,sha,source_fingerprint,runtime_identity
SEEDS=(42,123,2026,31415,271828)
def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('quality','pilot','audit','budget','build','oldstudy','meanstudy','cases','cases-report','output'):parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();quality_receipt=quality.verify(args.quality/'report.json');pilot=read(args.pilot/'report.json');pilot_audit=read(args.audit/'report.json');budget_receipt=read(args.budget/'report.json');before=source_fingerprint();build=args.build.resolve();binary=build/'bin/native_ppo_train';out=args.output.resolve()
  assert pilot['passed'] and pilot_audit['passed'] and pilot_audit['report_sha256']==sha(args.pilot/'report.json') and budget_receipt['passed'] and budget_receipt['pilot_report_sha256']==sha(args.pilot/'report.json') and budget_receipt['pilot_audit_sha256']==sha(args.audit/'report.json')
  assert before==pilot['source_before']==pilot['source_after'] and before['sha256']==budget_receipt['source_sha256'];assert all(sha(Path(path))==digest for path,digest in budget_receipt['frozen'].items());out.mkdir(parents=True,exist_ok=False);models=out/'models';models.mkdir()
  old,mean=read(args.oldstudy/'report.json'),read(args.meanstudy/'report.json');assert old['passed'] and mean['passed'] and old['validation_passed'] and mean['validation_passed']
  baseline_seeds=tuple(sorted(row['seed'] for row in old['models']));assert len(baseline_seeds)==5 and baseline_seeds==tuple(sorted(row['seed'] for row in mean['models']))
  old_cases=args.oldstudy/'cases.txt';cases=args.cases.resolve();case_receipt=read(args.cases_report/'report.json');assert cases.is_file() and len(cases.read_text().splitlines())==200 and case_receipt['passed'] and case_receipt['cases']==200 and case_receipt['groups']=={str(group):40 for group in range(5)} and case_receipt['case_sha256']==sha(cases) and Path(case_receipt['file']).resolve()==cases;here=Path(__file__).parent;helper=here/'dump_o23_schema12_entropy_stable_starts.cpp';auditor=here/'audit_o23_schema12_entropy_stable_finisher_study.py';draft=ROOT/'.project/optimization/o23-schema12-entropy-stable-finisher-budget-20261028.md'
  # This diagnostic helper is built once during setup.  It is frozen in the
  # protocol but deliberately excluded from the 75-command experiment ledger.
  flags={}
  for line in (build/'CMakeFiles/native_ppo_train.dir/flags.make').read_text().splitlines():
    if ' = ' in line:key,value=line.split(' = ',1);flags[key]=shlex.split(value)
  link=shlex.split((build/'CMakeFiles/native_ppo_train.dir/link.txt').read_text());starts_object=out/'starts.o';starts_binary=out/'starts'
  compile_starts=[link[0],*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS'],'-c',str(helper),'-o',str(starts_object)]
  subprocess.run(compile_starts,cwd=build,check=True)
  positions=[i for i,arg in enumerate(link) if arg.endswith('native_ppo_train.cpp.o')];assert len(positions)==1
  link[positions[0]]=str(starts_object);link[link.index('-o')+1]=str(starts_binary);subprocess.run(link,cwd=build,check=True)
  baselines=[]
  for label,study,report in (('constant8192',args.oldstudy,old),('mean4',args.meanstudy,mean)):
    for seed in baseline_seeds:
      model=next(row for row in report['models'] if row['seed']==seed);log=study/(f'validation-broad80-{seed}.log' if label=='constant8192' else f'validation-{seed}.log');baselines.append(dict(label=label,seed=seed,policy=str(Path(model['policy']).resolve()),policy_sha256=model['policy_sha256'],reference_log=str(log.resolve()),reference_sha256=sha(log)))
  files=[Path(__file__),auditor,helper,here/'audit_o23_study.py',here/'audit_o23_averaging.py',here/'run_o23_averaging.py',here/'quality.py',here/'validate.py',args.quality/'report.json',args.pilot/'report.json',args.pilot/'protocol.json',args.audit/'report.json',args.budget/'report.json',args.oldstudy/'report.json',args.meanstudy/'report.json',draft,binary,build/'libfootball_engine.so',starts_binary,cases,args.cases_report/'report.json',old_cases]
  files.extend(Path(row[key]) for row in baselines for key in ('policy','reference_log'));frozen={str(path.resolve()):sha(path) for path in files};budget=budget_receipt['budget']
  protocol=dict(source=before,environment=runtime_identity(sys.executable),frozen=frozen,budget=budget,quality=str(args.quality.resolve()),pilot=str(args.pilot.resolve()),pilot_audit=str(args.audit.resolve()),budget_receipt=str(args.budget.resolve()),build=str(build),old_study=str(args.oldstudy.resolve()),mean_study=str(args.meanstudy.resolve()),prospective_cases=str(cases),prospective_cases_sha256=sha(cases),prospective_case_receipt=str((args.cases_report/'report.json').resolve()),prospective_case_receipt_sha256=sha(args.cases_report/'report.json'),regression_cases=str(old_cases),regression_cases_sha256=sha(old_cases),baselines=baselines,baseline_seeds=list(baseline_seeds),seeds=list(SEEDS),scenario='2v1_broad_entropy_stable_finisher',payload_schema=12,updates_per_chunk='1024x7_then_256x4',chunks=11,checkpoint_targets=[1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192],final_version=8192,lr='.0003*max(.1,1-global_version_before_update/8192)',selection='Fixed within-seed equal mean of7424,7680,7936,8192; no alternative window',helper_build=dict(command_count=2,ledger='setup_only_not_counted_in_75',compile_argv=compile_starts,link_argv=link,output=str(starts_binary),output_sha256=sha(starts_binary)),validation_gates=dict(total=970,seed=180,group=180,passes=40,joint=40),confirmation_opened=False)
  write(out/'protocol.json',protocol);shutil.copyfile(cases,out/'cases.txt');commands=[];records=[];regressions=[];validation=[];resources=out/'resources.jsonl';started=time.monotonic();training_seconds=0.;env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  def unchanged():assert source_fingerprint()==before and all(sha(Path(path))==digest for path,digest in frozen.items())
  def run(name,argv,cap,training=False):
    nonlocal training_seconds
    print(name,flush=True);begin=time.monotonic();peak=0;reason=None;last=0
    with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resources.open('a') as samples:
      child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
      while child.poll() is None:
        elapsed=time.monotonic()-begin
        try:
          rss=proc.memory_info().rss;peak=max(peak,rss)
          if rss>budget['max_child_rss_bytes']:reason='RSS budget'
          if elapsed-last>=2:cpu=proc.cpu_times();samples.write(json.dumps(dict(command=name,seconds=elapsed,rss=rss,fds=proc.num_fds(),user=cpu.user,system=cpu.system))+'\n');samples.flush();last=elapsed
          if sum(path.stat().st_size for path in out.rglob('*') if path.is_file())>budget['max_study_output_bytes']:reason='Output budget'
        except psutil.NoSuchProcess:pass
        if elapsed>cap:reason='Wall budget'
        if reason:child.terminate();child.wait(timeout=5);break
        time.sleep(.2)
    seconds=time.monotonic()-begin
    if training:training_seconds+=seconds
    commands.append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert reason is None and child.returncode==0,(name,reason);return seconds
  report=dict(passed=False,validation_passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=quality_receipt,commands=commands,models=records,regressions=regressions,validation=validation)
  try:
    for item in baselines:
      unchanged();name=f'regression-{item["label"]}-{item["seed"]}';run(name,[binary,'--inference-mode','balanced','--policy',item['policy'],'--inference-cases',old_cases],300);actual=[json.loads(line) for line in (out/(name+'.log')).read_text().splitlines()];summary=actual.pop();expected=[json.loads(line) for line in Path(item['reference_log']).read_text().splitlines()];expected.pop();assert summary['complete'] and len(actual)==200 and actual==expected;regressions.append(dict(label=item['label'],seed=item['seed'],episodes=200,rows_equal=True))
    for seed in SEEDS:
      seed_start=time.monotonic();last_checkpoint=None;completed=0;chunks=[];previous=0
      for target in (1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192):
        checkpoint=models/f'entropy-stable-finisher-{seed}-u{target}.fppo';policy=models/f'entropy-stable-finisher-{seed}-u{target}.fpol';argv=[binary,'--scenario','2v1_broad_entropy_stable_finisher','--seed',seed,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0,'--updates',target-previous,'--save',checkpoint]
        if last_checkpoint:argv+=['--load',last_checkpoint]
        if target in (7424,7680,7936,8192):argv+=['--export-policy',policy]
        cap=min(budget['max_wall_seconds_per_training_run']-(time.monotonic()-seed_start),budget['max_total_training_wall_seconds']-training_seconds);assert cap>0;run(f'train-entropy-stable-finisher-{seed}-u{target}',argv,cap,True);data=read(out/f'train-entropy-stable-finisher-{seed}-u{target}.log');assert data['scenario']==protocol['scenario'] and data['start_version']==previous and data['version']==target and data['total_transitions']==target*256 and data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']==sha(checkpoint)
        for row in data['iterations']:assert row['learning_rate']==.0003*max(.1,(8193-row['version'])/8192) and row['optimizer_steps']==16 and row['transitions']==256 and all(math.isfinite(row[key]) for key in ('loss','entropy','gradient_norm','parameter_delta'))
        completed+=sum(row['completed_episodes'] for row in data['iterations']);chunks.append(dict(version=target,checkpoint_sha256=sha(checkpoint)));last_checkpoint=checkpoint;previous=target;unchanged()
      run(f'starts-entropy_stable_finisher_mean4-{seed}',[starts_binary,12,seed,completed+1],120);starts=out/f'starts-entropy_stable_finisher_mean4-{seed}.log'
      rows=[json.loads(line) for line in starts.read_text().splitlines()];actual=native_start(last_checkpoint,seed,12,8192);assert len(rows)==completed+1 and all(actual[key]==rows[actual['episode']][key] for key in ('engine_seed','geometry','ball'))
      members=[];weights=[];headers=[]
      for version in (7424,7680,7936,8192):
        checkpoint=models/f'entropy-stable-finisher-{seed}-u{version}.fppo';policy=models/f'entropy-stable-finisher-{seed}-u{version}.fpol';header,values=decode_policy(policy);assert int(header[3])==seed and int(header[4])==64 and header[6]==sha(checkpoint);headers.append(header);weights.append(values);members.append(dict(version=version,weight=.25,checkpoint=str(checkpoint),checkpoint_sha256=sha(checkpoint),policy=str(policy),policy_sha256=sha(policy)))
      manifest=models/f'{seed}-provenance.json';write(manifest,dict(schema='within_seed_mean4_v1',seed=seed,members=members,derived_inference_only=True,algorithm='Binary64 fsum,ascending versions,divide by4'));averaged=[math.fsum(column)/4 for column in zip(*weights)];header=headers[0].copy();header[6]=sha(manifest);payload=' '.join(header)+'\n'+''.join(format(value,'.17g')+'\n' for value in averaged);derived=models/f'entropy-stable-finisher-mean4-{seed}.fpol';derived.write_text('FPOL1\n'+hashlib.sha256(payload.encode()).hexdigest()+'\n'+payload);assert len(averaged)==8724 and decode_policy(derived)[1]==averaged
      if seed==31415:
        pilot_iterations=read(args.pilot/'full1024.log')['iterations'];first_chunk=read(out/'train-entropy-stable-finisher-31415-u1024.log')['iterations'];assert first_chunk==pilot_iterations;report['known_pilot_prefix_matches']=True
      records.append(dict(configuration='entropy_stable_finisher_mean4',seed=seed,chunks=chunks,initial_version=0,final_version=8192,path=str(last_checkpoint),sha256=sha(last_checkpoint),raw_policy=str(policy),raw_policy_sha256=sha(policy),policy=str(derived),policy_sha256=sha(derived),policy_kind='within_seed_mean4_v1',members=members,provenance_manifest=str(manifest),provenance_sha256=sha(manifest),conservative_episode_starts=completed+1,starts_sha256=sha(starts),training_seconds=time.monotonic()-seed_start))
    ids=[tuple(map(int,line.split()[:2]+[line.split()[3]])) for line in cases.read_text().splitlines()]
    for model in records:
      seed=model['seed'];name=f'validation-entropy_stable_finisher_mean4-{seed}';run(name,[binary,'--inference-mode','balanced','--policy',model['policy'],'--inference-cases',cases],300);rows=[json.loads(line) for line in (out/(name+'.log')).read_text().splitlines()];summary=rows.pop();assert summary['complete'] and len(rows)==200 and [(row['index'],row['group'],row['engine_seed']) for row in rows]==ids;validation.append(dict(seed=seed,goals=sum(row['controlled_score_delta']>0 for row in rows),passes=sum(row['completed_passes']>0 for row in rows),joint=sum(row['completed_passes']>0 and row['controlled_score_delta']>0 for row in rows),groups=[sum(row['controlled_score_delta']>0 for row in rows if row['group']==group) for group in range(5)]))
    total=sum(cell['goals'] for cell in validation);groups=[sum(cell['groups'][group] for cell in validation) for group in range(5)];gates=dict(mean=total>=970,every_seed=all(cell['goals']>=180 for cell in validation),groups=all(value>=180 for value in groups),cooperation=all(cell['passes']>=40 and cell['joint']>=40 for cell in validation));report.update(passed=True,portable_regression_passed=True,known_pilot_prefix_matches=True,validation_passed=all(gates.values()),candidate_mean=total/1000,candidate_group_means=[value/200 for value in groups],gates=gates,selected='entropy_stable_finisher_mean4' if all(gates.values()) else None,confirmation_opened=False)
  except BaseException as error:report['error']=f'{type(error).__name__}: {error}'
  finally:
    report.update(source_after=source_fingerprint(),training_seconds=training_seconds,total_seconds=time.monotonic()-started)
    if resources.exists():report['resources_sha256']=sha(resources)
    write(out/'report.json',report)
  print(json.dumps({key:report.get(key) for key in ('passed','validation_passed','candidate_mean','error')}),flush=True);return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())



