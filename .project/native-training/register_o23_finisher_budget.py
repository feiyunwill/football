"""Register the schema9 five-seed budget from audited diagnostic pilots."""
import argparse,json,math
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint

def read(path): return json.loads(path.read_text())
def rate(metrics,key): return metrics[key]/metrics['episodes']
def main():
  parser=argparse.ArgumentParser(description=__doc__)
  for key in ('pilot','audit','control','control-audit','quality','output'): parser.add_argument('--'+key,type=Path,required=True)
  args=parser.parse_args(); quality.verify(args.quality/'report.json'); source=source_fingerprint()
  pilot,audit,control,control_audit=[read(path/'report.json') for path in (args.pilot,args.audit,args.control,args.control_audit)]
  protocol=read(args.pilot/'protocol.json'); control_protocol=read(args.control/'protocol.json')
  assert pilot['passed'] and audit['passed'] and control['passed'] and control_audit['passed']
  assert protocol['schema']==9 and control_protocol['schema']==6 and protocol['seed']==control_protocol['seed']==42
  assert source==pilot['source_before']==pilot['source_after']==control['source_before']==control['source_after']==protocol['source']==control_protocol['source']
  assert source['sha256']==audit['source_sha256']==control_audit['source_sha256']
  assert sha(args.pilot/'report.json')==audit['report_sha256'] and sha(args.control/'report.json')==control_audit['report_sha256']
  assert all(sha(Path(path))==digest for path,digest in protocol['frozen'].items()) and all(sha(Path(path))==digest for path,digest in control_protocol['frozen'].items())
  candidate,baseline=pilot['pilot_group5_metrics']['sample'],control['pilot_group5_metrics']['sample']
  assert all(rate(candidate,key)>=rate(baseline,key) for key in ('goals','completed_passes','joint'))
  projected=pilot['projected8192_seconds']; per_seed=math.ceil((projected*1.05+120)/60)*60
  assert 0<projected<per_seed<=2880
  note=ROOT/'.project/optimization/o23-schema9-finisher-budget-20261027.md'
  files=[Path(__file__),args.pilot/'report.json',args.pilot/'protocol.json',args.audit/'report.json',args.control/'report.json',args.control/'protocol.json',args.control_audit/'report.json',args.quality/'report.json',note]
  frozen={str(path.resolve()):sha(path) for path in files}
  receipt=dict(passed=True,source_sha256=source['sha256'],pilot_report_sha256=sha(args.pilot/'report.json'),pilot_audit_sha256=sha(args.audit/'report.json'),control_report_sha256=sha(args.control/'report.json'),control_audit_sha256=sha(args.control_audit/'report.json'),projected8192_seconds=projected,budget=dict(max_wall_seconds_per_training_run=per_seed,max_total_training_wall_seconds=5*per_seed,max_child_rss_bytes=512*1024**2,max_study_output_bytes=2*1024**3),frozen=frozen,optimizer_updates_per_seed=8192,seeds=[42,123,2026,31415,271828],checkpoint_schedule=[1024,2048,3072,4096,5120,6144,7168,7424,7680,7936,8192],acceptance_gates='existing frozen O23 gates; no relaxation',confirmation_opened=False)
  args.output.parent.mkdir(parents=True,exist_ok=True)
  with args.output.open('x') as stream: stream.write(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
if __name__=='__main__': raise SystemExit(main())