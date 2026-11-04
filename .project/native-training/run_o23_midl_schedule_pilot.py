"""Bounded schema8 checkpoint-schedule equivalence and cost pilot."""
import argparse,json,math,os,psutil,subprocess,time
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint,runtime_identity

def read(path): return json.loads(path.read_text())
def write(path,value): path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('quality','build','output'): parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();verified=quality.verify(args.quality/'report.json');before=source_fingerprint();build=args.build.resolve();binary=build/'bin/native_ppo_train';out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
  files=[Path(__file__),args.quality/'report.json',binary,build/'libfootball_engine.so'];frozen={str(path.resolve()):sha(path) for path in files}
  protocol=dict(source=before,environment=runtime_identity(__import__('sys').executable),scenario='2v1_broad_reweighted_midl',schema=8,seed=42,updates=1024,reference_schedule=[256,256,256,256],candidate_schedule=[1024],wall_cap_seconds=1800,rss_cap_bytes=512*1024*1024,scope='Operational-equivalence and cost pilot only; no validation, selection, confirmation, stability, or delivery authority.',frozen=frozen)
  write(out/'protocol.json',protocol);report=dict(passed=False,source_before=before,protocol_sha256=sha(out/'protocol.json'),quality=verified,commands=[]);started=time.monotonic();resources=out/'resources.jsonl';env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
  def run(name,argv):
    begin=time.monotonic();peak=0;reason=None;print(name,flush=True)
    with (out/(name+'.log')).open('w') as stream,(out/(name+'.stderr')).open('w') as errors,resources.open('a') as samples:
      child=subprocess.Popen(list(map(str,argv)),cwd=build,env=env,stdout=stream,stderr=errors);proc=psutil.Process(child.pid)
      while child.poll() is None:
        try:
          rss=proc.memory_info().rss;peak=max(peak,rss);samples.write(json.dumps(dict(command=name,seconds=time.monotonic()-begin,rss=rss))+'\n');samples.flush()
          if rss>protocol['rss_cap_bytes']:reason='RSS budget'
        except psutil.NoSuchProcess: pass
        if time.monotonic()-started>protocol['wall_cap_seconds']: reason='30-minute budget'
        if reason: child.terminate();child.wait(timeout=5);break
        time.sleep(.2)
    seconds=time.monotonic()-begin;report['commands'].append(dict(name=name,argv=list(map(str,argv)),exit_code=child.returncode,seconds=seconds,observed_peak_rss=peak,stdout_sha256=sha(out/(name+'.log')),stderr_sha256=sha(out/(name+'.stderr'))));assert reason is None and child.returncode==0,(name,reason);return seconds
  try:
    common=[binary,'--scenario','2v1_broad_reweighted_midl','--seed',42,'--hidden',64,'--epochs',4,'--minibatch',64,'--rollout',256,'--cadence',10,'--episode-limit',256,'--no-initial-eval','--eval-episodes',0]
    continuous_seconds=run('continuous1024',[*common,'--updates',1024,'--save',out/'continuous.fppo','--export-policy',out/'continuous.fpol'])
    checkpoint=None;parts=[]
    for target in range(256,1025,256):
      argv=[*common,'--updates',256,'--save',out/f'split-u{target}.fppo']
      if checkpoint: argv+=['--load',checkpoint]
      if target==1024: argv+=['--export-policy',out/'split.fpol']
      run(f'split-u{target}',argv);parts.append(read(out/f'split-u{target}.log'));checkpoint=out/f'split-u{target}.fppo'
    continuous=read(out/'continuous1024.log');assert (out/'continuous.fppo').read_bytes()==checkpoint.read_bytes() and (out/'continuous.fpol').read_bytes()==(out/'split.fpol').read_bytes()
    assert continuous['iterations']==[item for part in parts for item in part['iterations']] and continuous['version']==1024 and continuous['total_transitions']==1024*256
    for data in [continuous,*parts]:
      assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']
      for row in data['iterations']: assert row['learning_rate']==.00025*max(.1,(8193-row['version'])/8192) and all(math.isfinite(row[key]) for key in ('loss','entropy','gradient_norm','parameter_delta'))
    report.update(passed=True,checkpoint_bytes_equal=True,policy_bytes_equal=True,iterations_equal=True,continuous_seconds=continuous_seconds,split_seconds=sum(row['seconds'] for row in report['commands'] if row['name'].startswith('split-')),continuous_projected8192_seconds=continuous_seconds*8,peak_child_rss=max(row['observed_peak_rss'] for row in report['commands']))
  except BaseException as error: report['error']=f'{type(error).__name__}: {error}'
  finally:
    report['source_after']=source_fingerprint();report['total_seconds']=time.monotonic()-started
    if before!=report['source_after'] or any(sha(Path(path))!=digest for path,digest in frozen.items()): report.update(passed=False,error='Frozen source or evidence changed')
    if resources.exists():report['resources_sha256']=sha(resources)
    write(out/'report.json',report)
  print(json.dumps({key:report.get(key) for key in ('passed','continuous_seconds','split_seconds','error')}),flush=True);return 0 if report['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
