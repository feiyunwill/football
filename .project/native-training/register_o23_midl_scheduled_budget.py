"""Register the unchanged schema8 per-seed limit for scheduled checkpoints."""
import argparse,json
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint
def read(path):return json.loads(path.read_text())
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('pilot','audit','quality','output'):parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();quality.verify(args.quality/'report.json');pilot=read(args.pilot/'report.json');audit=read(args.audit/'report.json');protocol=read(args.pilot/'protocol.json');source=source_fingerprint()
  assert pilot['passed'] and audit['passed'] and protocol['schema']==8 and protocol['candidate_schedule']==[1024] and source==pilot['source_before']==pilot['source_after']==protocol['source'] and source['sha256']==audit['source_sha256'];assert sha(args.pilot/'report.json')==audit['report_sha256'] and all(sha(Path(path))==digest for path,digest in protocol['frozen'].items())
  assert pilot['checkpoint_bytes_equal'] and pilot['policy_bytes_equal'] and pilot['iterations_equal'] and pilot['continuous_projected8192_seconds']<=2400
  notes=[ROOT/'.project/optimization/o23-midl-budget-rejection-20261027.md',ROOT/'.project/optimization/o23-midl-scheduled-starts-rejection-20261027.md',ROOT/'.project/optimization/o23-midl-scheduled-retry-budget-rejection-20261027.md'];files=[Path(__file__),args.pilot/'report.json',args.pilot/'protocol.json',args.audit/'report.json',args.quality/'report.json',*notes];frozen={str(path.resolve()):sha(path) for path in files}
  receipt=dict(passed=True,source_sha256=source['sha256'],pilot_report_sha256=sha(args.pilot/'report.json'),pilot_audit_sha256=sha(args.audit/'report.json'),projected8192_seconds=pilot['continuous_projected8192_seconds'],budget=dict(max_wall_seconds_per_training_run=2520,max_total_training_wall_seconds=12600,max_child_rss_bytes=512*1024**2,max_study_output_bytes=2*1024**3),frozen=frozen,prior_rejections=[str(note.resolve()) for note in notes],optimizer_updates_per_seed=8192,seeds=[42,123,2026,31415,271828],checkpoint_schedule=[1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192],confirmation_opened=False)
  args.output.parent.mkdir(parents=True,exist_ok=True)
  with args.output.open('x') as stream:stream.write(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
if __name__=='__main__':raise SystemExit(main())
