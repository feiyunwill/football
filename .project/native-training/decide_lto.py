"""Apply predeclared LTO CPU thresholds to retained paired measurements."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report',type=Path,required=True)
args=parser.parse_args()
run=json.loads(args.report.read_text())
assert run['passed'] and run['source_before']==run['source_after']
rng=random.Random(42)
rows=[]
for w in run['workloads']:
    ratios=w['paired_cpu_speedups']
    assert len(ratios)==8
    values=sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(20000))
    median=statistics.median(ratios)
    primary=(w['players'],w['cadence'],w['feedback'])==(11,2,False)
    ci=[values[int(.025*len(values))],values[int(.975*len(values))]]
    reduction=1-1/median
    passed=(reduction>=.10 and ci[0]>1) if primary else (1/median-1<=.03)
    rows.append(dict(players=w['players'],cadence=w['cadence'],feedback=w['feedback'],
        primary=primary,median_cpu_speedup=median,cpu_reduction=reduction,paired_ci95=ci,passed=passed))
assert sum(row['primary'] for row in rows)==1
complete=run['scope']=='full_matrix' and len(rows)==8
result=dict(accepted=complete and all(row['passed'] for row in rows),
    primary_passed=next(row['passed'] for row in rows if row['primary']),
    complete_matrix=complete,workloads=rows,
    report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
    note='Engine-step CPU only. Bootstrap paired ratios; 8 pairs, 20000 draws, fixed seed42. No end-to-end training speedup claim.')
args.report.with_name('decision.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
