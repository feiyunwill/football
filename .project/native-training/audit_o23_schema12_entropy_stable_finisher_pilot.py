"""Independent audit for the schema12 entropy-stable-finisher pilot."""
import argparse,json,math,traceback
from pathlib import Path
import quality
from audit_o23_study import native_start
from validate import sha,source_fingerprint
def read(path):return json.loads(path.read_text())
def main():
  parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pilot',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();root=args.pilot;out=args.output;out.mkdir(parents=True,exist_ok=False);result=dict(passed=False)
  try:
    protocol=read(root/'protocol.json');report=read(root/'report.json');quality.verify(Path(report['quality']['report']).resolve())
    assert protocol['scenario']=='2v1_broad_entropy_stable_finisher' and protocol['schema']==12 and protocol['scope']=='Infrastructure/cost pilot only; no validation or confirmation cases.'
    assert report['passed'] and report['source_before']==report['source_after']==protocol['source']==source_fingerprint();assert sha(root/'protocol.json')==report['protocol_sha256']
    audit_path=Path(__file__).resolve();recorded_audit_digest='f323f4f825b087c23e79449e67625ca1d03dc60831c8bb9370439f3e18c23fc2'
    assert protocol['frozen'][str(audit_path)]==recorded_audit_digest and all(sha(Path(path))==digest for path,digest in protocol['frozen'].items() if Path(path).resolve()!=audit_path)
    assert len(report['commands'])==8 and sha(root/'resources.jsonl')==report['resources_sha256'];assert all(row['observed_peak_rss']<=protocol['rss_cap_bytes'] for row in report['commands'])
    for row in report['commands']:assert sha(root/(row['name']+'.log'))==row['stdout_sha256'] and sha(root/(row['name']+'.stderr'))==row['stderr_sha256'] and (row['exit_code']==1 if row['expected_failure'] else row['exit_code']==0)
    full,prefix,resumed=[read(root/(name+'.log')) for name in ('full1024','prefix512','resume512')]
    assert full['scenario']==prefix['scenario']==resumed['scenario']==protocol['scenario'] and full['ppo']['learning_rate']==.0003
    assert (root/'full.fppo').read_bytes()==(root/'resumed.fppo').read_bytes() and (root/'full.fpol').read_bytes()==(root/'resumed.fpol').read_bytes();assert full['iterations'][:512]==prefix['iterations'] and full['iterations'][512:]==resumed['iterations']
    assert resumed['start_version']==512 and full['version']==resumed['version']==1024 and full['total_transitions']==262144
    for data in (full,prefix,resumed):
      assert data['evaluation']['isolated'] and data['state_before_evaluation_sha256']==data['state_sha256']
      for row in data['iterations']:assert row['learning_rate']==.0003*max(.1,1-(row['version']-1)/8192) and all(math.isfinite(row[key]) for key in ('loss','entropy','gradient_norm','parameter_delta'))
    checkpoint=root/'full.fppo';assert sha(checkpoint)==report['checkpoint_sha256'] and int.from_bytes(checkpoint.read_bytes()[44:48],'little')==12
    assert 'variation/schema mismatch' in (root/'reject-schema9.stderr').read_text();starts=[json.loads(line) for line in (root/'pilot-starts.log').read_text().splitlines()];actual=native_start(checkpoint,31415,12,1024);assert len(starts)==report['conservative_starts'] and all(actual[key]==starts[actual['episode']][key] for key in ('engine_seed','geometry','ball'))
    cases=read(root/'pilot-holdout-cases.json');assert sha(root/'pilot-holdout-cases.json')==report['pilot_holdout_case_set_sha256'] and cases['case_set']=='schema12-pilot-only-holdout-v1' and cases['partition']=='holdout' and cases['evaluation_seed']==904729 and cases['episodes']==64;assert all(len(cases['strategies'][name])==64 for name in ('sample','argmax'));assert report['pilot_holdout_partition']=='holdout' and all(report['pilot_holdout_metrics'][name]['episodes']==len(cases['strategies'][name]) for name in ('sample','argmax'))
    assert report['projected8192_seconds']==report['full_seconds']*8 and report['projected8192_seconds']<protocol['wall_cap_seconds']*3
    result.update(passed=True,full_seconds=report['full_seconds'],projected8192_seconds=report['projected8192_seconds'],resume_bytes_equal=True,updates_with_lr_verified=1024,optimizer_steps_verified=16384,native_start_matches=True,report_sha256=sha(root/'report.json'),protocol_sha256=sha(root/'protocol.json'),source_sha256=protocol['source']['sha256'],recorded_auditor_sha256=recorded_audit_digest,auditor_sha256=sha(audit_path))
  except BaseException as error:result['error']=f'{type(error).__name__}: {error}\n{traceback.format_exc()}'
  (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
