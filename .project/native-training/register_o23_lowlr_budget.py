"""Register the schema7 full-study budget from the independently audited pilot."""
import argparse,json,math
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint
def read(path):return json.loads(path.read_text())
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('pilot','audit','quality','output'):parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args();quality.verify(args.quality/'report.json');pilot=read(args.pilot/'report.json');audit=read(args.audit/'report.json');protocol=read(args.pilot/'protocol.json');source=source_fingerprint()
  assert pilot['passed'] and audit['passed'] and protocol['schema']==7 and source==pilot['source_before']==pilot['source_after']==protocol['source'] and source['sha256']==audit['source_sha256'];assert sha(args.pilot/'report.json')==audit['report_sha256'] and sha(args.pilot/'protocol.json')==audit['protocol_sha256'];assert all(sha(Path(path))==digest for path,digest in protocol['frozen'].items())
  projected=pilot['projected8192_seconds'];per_seed=math.ceil((projected*1.05+120)/60)*60;assert 0<projected<per_seed<=5113
  budget_note=ROOT/'.project/optimization/o23-reweighted-lowlr-budget-20261026.md';files=[Path(__file__),args.pilot/'report.json',args.pilot/'protocol.json',args.audit/'report.json',args.quality/'report.json',budget_note];frozen={str(path.resolve()):sha(path) for path in files}
  receipt=dict(passed=True,source_sha256=source['sha256'],pilot_report_sha256=sha(args.pilot/'report.json'),pilot_audit_sha256=sha(args.audit/'report.json'),measured_full64_seconds=pilot['full_seconds'],projected8192_seconds=projected,formula='ceil((projected8192_seconds*1.05+120)/60)*60 per seed; maximum5113',budget=dict(max_wall_seconds_per_training_run=per_seed,max_total_training_wall_seconds=5*per_seed,max_child_rss_bytes=512*1024**2,max_study_output_bytes=2*1024**3),frozen=frozen,optimizer_updates_per_seed=8192,seeds=[42,123,2026,31415,271828],pilot_reused_as_training_state=False,primary_policy='Within-seed equal mean of7424,7680,7936,8192; fixed before training',confirmation_opened=False)
  args.output.parent.mkdir(parents=True,exist_ok=True)
  with args.output.open('x') as stream:stream.write(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
if __name__=='__main__':raise SystemExit(main())
