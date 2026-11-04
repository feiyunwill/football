"""Freeze full five-seed budget only after an independently audited schema6 pilot."""
import argparse,json,math
from pathlib import Path
import quality
from validate import ROOT,sha,source_fingerprint

def read(p):return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('pilot','audit','quality','output'):ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args();quality.verify(a.quality/'report.json')
    p=read(a.pilot/'report.json');v=read(a.audit/'report.json');proto=read(a.pilot/'protocol.json');source=source_fingerprint()
    assert p['passed'] and v['passed'] and proto['schema']==6
    assert source==p['source_before']==p['source_after']==proto['source'] and source['sha256']==v['source_sha256']
    assert sha(a.pilot/'report.json')==v['report_sha256'] and sha(a.pilot/'protocol.json')==v['protocol_sha256']
    assert all(sha(Path(f))==h for f,h in proto['frozen'].items())
    projected=p['full_seconds']*128;assert 0<projected<=5113
    per_seed=math.ceil((projected*1.75+120)/60)*60
    assert per_seed<=5113,'Measured cost plus preregistered margin exceeds per-seed ceiling; do not start full training'
    files=[Path(__file__),a.pilot/'report.json',a.pilot/'protocol.json',a.audit/'report.json',a.quality/'report.json',ROOT/'.project/optimization/o23-reweighted-training-protocol-20261021.md']
    frozen={str(p.resolve()):sha(p) for p in files}
    report=dict(passed=True,source_sha256=source['sha256'],pilot_report_sha256=sha(a.pilot/'report.json'),pilot_audit_sha256=sha(a.audit/'report.json'),
        measured_full64_seconds=p['full_seconds'],projected8192_seconds=projected,
        formula='ceil((measured_full64_seconds*128*1.75+120)/60)*60 per seed; maximum5113',
        budget=dict(max_wall_seconds_per_training_run=per_seed,max_total_training_wall_seconds=5*per_seed,max_child_rss_bytes=512*1024**2,max_study_output_bytes=2*1024**3),
        frozen=frozen,optimizer_updates_per_seed=8192,seeds=[42,123,2026,31415,271828],pilot_reused_as_training_state=False,
        primary_policy='Within-seed equal mean of7424,7680,7936,8192; fixed before training',confirmation_opened=False)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
