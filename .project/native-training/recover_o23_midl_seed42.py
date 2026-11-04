"""Recover only the completed schema8 seed-42 training chain; never accepts a candidate."""
import argparse,hashlib,json,math,os,subprocess
from pathlib import Path
from run_o23_averaging import policy as decode_policy
from audit_o23_study import native_start
from validate import sha,source_fingerprint

TARGETS=(1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192)
def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def lines(path):return [json.loads(row) for row in path.read_text().splitlines()]
def main():
  p=argparse.ArgumentParser(description=__doc__)
  for key in ('study','build','output'):p.add_argument('--'+key,type=Path,required=True)
  a=p.parse_args();root=a.study.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
  report=read(root/'report.json');protocol=read(root/'protocol.json');result={'passed':False,'candidate_accepted':False}
  try:
    assert not report['passed'] and report['error']=="AssertionError: ('starts-midl_mean4-42', None)"
    assert protocol['payload_schema']==8 and protocol['checkpoint_targets']==list(TARGETS)
    assert report['source_before']==report['source_after']==protocol['source']==source_fingerprint()
    commands={row['name']:row for row in report['commands']};assert len(report['regressions'])==10 and all(x['rows_equal'] for x in report['regressions'])
    completed=0;chunks=[];models=root/'models'
    for previous,target in zip((0,*TARGETS[:-1]),TARGETS):
      name=f'train-midl-42-u{target}';row=commands[name];log=root/(name+'.log');err=root/(name+'.stderr');checkpoint=models/f'midl-42-u{target}.fppo'
      assert row['exit_code']==0 and sha(log)==row['stdout_sha256'] and sha(err)==row['stderr_sha256'] and row['observed_peak_rss']<=512*1024**2
      data=read(log);assert data['start_version']==previous and data['version']==target and data['total_transitions']==target*256 and sha(checkpoint)==data['state_sha256']
      assert [x['version'] for x in data['iterations']]==list(range(previous+1,target+1))
      completed+=sum(x['completed_episodes'] for x in data['iterations']);chunks.append({'version':target,'checkpoint':str(checkpoint),'checkpoint_sha256':sha(checkpoint)})
    helper=root/'starts';assert sha(helper)==protocol['helper_build']['output_sha256'];frozen=[Path(__file__),root/'report.json',root/'protocol.json',helper]
    for chunk in chunks:frozen.append(Path(chunk['checkpoint']))
    for version in TARGETS[-4:]:frozen.append(models/f'midl-42-u{version}.fpol')
    frozen={str(x.resolve()):sha(x) for x in frozen};recovery=dict(source=protocol['source'],original_study=str(root),original_report_sha256=sha(root/'report.json'),frozen=frozen,seed=42,payload_schema=8,targets=list(TARGETS),training_seconds=report['training_seconds'],scope='Recovery of a completed within-budget seed only; no candidate selection, validation, confirmation, stability, or delivery.')
    write(out/'protocol.json',recovery)
    env=dict(os.environ,LD_LIBRARY_PATH=str(a.build.resolve()),GFOOTBALL_DATA_DIR=str(Path(__file__).parents[2]/'engine/data'))
    starts=out/'starts-midl_mean4-42.log'
    with starts.open('w') as stream:subprocess.run([str(helper),'8','42',str(completed+1)],env=env,check=True,stdout=stream)
    reconstructed=lines(starts);actual=native_start(models/'midl-42-u8192.fppo',42,8,8192)
    assert len(reconstructed)==completed+1 and all(actual[k]==reconstructed[actual['episode']][k] for k in ('engine_seed','geometry','ball'))
    members=[];weights=[];header=None
    for version in TARGETS[-4:]:
      checkpoint=models/f'midl-42-u{version}.fppo';policy=models/f'midl-42-u{version}.fpol';fields,values=decode_policy(policy);assert int(fields[3])==42 and fields[6]==sha(checkpoint)
      header=fields;weights.append(values);members.append({'version':version,'weight':.25,'checkpoint':str(checkpoint),'checkpoint_sha256':sha(checkpoint),'policy':str(policy),'policy_sha256':sha(policy)})
    manifest=out/'42-provenance.json';write(manifest,{'schema':'within_seed_mean4_v1','seed':42,'members':members,'derived_inference_only':True,'algorithm':'Binary64 fsum,ascending versions,divide by4'})
    mean=[math.fsum(col)/4 for col in zip(*weights)];header=header.copy();header[6]=sha(manifest);payload=' '.join(header)+'\n'+''.join(format(v,'.17g')+'\n' for v in mean);policy=out/'midl-mean4-42.fpol';policy.write_text('FPOL1\n'+hashlib.sha256(payload.encode()).hexdigest()+'\n'+payload);assert decode_policy(policy)[1]==mean
    result.update(passed=True,seed=42,training_seconds=report['training_seconds'],chunks=chunks,starts=str(starts),starts_sha256=sha(starts),conservative_episode_starts=len(reconstructed),raw_checkpoint=str(models/'midl-42-u8192.fppo'),raw_checkpoint_sha256=sha(models/'midl-42-u8192.fppo'),policy=str(policy),policy_sha256=sha(policy),provenance_manifest=str(manifest),provenance_sha256=sha(manifest),protocol_sha256=sha(out/'protocol.json'),source_sha256=protocol['source']['sha256'])
  except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
  write(out/'report.json',result);print(json.dumps(result),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
