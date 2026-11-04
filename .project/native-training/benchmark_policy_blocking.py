"""Paired production UpdatePpo experiment for blocked policy forward. Baseline source must be archived before editing."""
import argparse
import hashlib
import json
import platform
import os
from pathlib import Path
import random
import statistics
import subprocess
import validate

ROOT=Path(__file__).resolve().parents[2]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    work=args.work_root.resolve(); output=args.output.resolve()
    if work==ROOT or ROOT in work.parents: parser.error('work-root must be external')
    output.mkdir(parents=True,exist_ok=False)
    source=ROOT/'engine/src/training/categorical_policy.cpp'
    baseline=work/'baseline-policy.cpp'
    cpu=min(os.sched_getaffinity(0)); os.sched_setaffinity(0,{cpu})
    report=dict(passed=False,scope='isolated CPU UpdatePpo; not engine or end-to-end throughput',
        protocol=dict(pairs=8,repeats=48,pinned_cpu=cpu,minimum_median_reduction=.10,confidence=.95,
                      criterion='all four workload medians >=10% reduction and paired bootstrap lower speedup >1',
                      floating_point='exact raw bytes of model, Adam, RNG, update metrics and public gradients'),
        baseline_sha256=sha(baseline),candidate_sha256=sha(source),workloads=[],
        source_before=validate.source_fingerprint(),environment=dict(platform=platform.platform(),
            compiler=subprocess.check_output(['c++','--version'],text=True),
            cpu=Path('/proc/cpuinfo').read_text().split('\n\n')[0]),commands=[])
    (output/'baseline.cpp').write_bytes(baseline.read_bytes())
    (output/'candidate.cpp').write_bytes(source.read_bytes())
    for path in (Path(__file__),Path(__file__).with_name('ppo_fusion_probe.cpp')):
        (output/path.name).write_bytes(path.read_bytes())
    files=[Path(__file__),Path(__file__).with_name('ppo_fusion_probe.cpp'),
           ROOT/'engine/src/training/ppo_math.cpp',ROOT/'engine/src/training/ppo_math.hpp',
           ROOT/'engine/src/training/categorical_policy.hpp']
    report['inputs']={str(p.relative_to(ROOT)):sha(p) for p in files}
    for name,math in [('baseline',baseline),('candidate',source)]:
        command=['c++','-std=c++23','-O3','-I'+str(ROOT/'engine/src'),str(files[1]),
                 str(ROOT/'engine/src/training/ppo_math.cpp'),str(math),'-o',str(work/name)]
        result=subprocess.run(command,capture_output=True,text=True)
        report['commands'].append(command)
        (output/(name+'-build.log')).write_text(result.stdout+result.stderr)
        result.check_returncode()
    for players in (1,11):
        for hidden in (16,64):
            rows=[]; reference=None
            for pair in range(8):
                times={}
                for name in (('baseline','candidate') if pair%2==0 else ('candidate','baseline')):
                    command=[str(work/name),str(players),str(hidden),'128','48']
                    report['commands'].append(command)
                    result=subprocess.run(command,capture_output=True,check=True,timeout=120)
                    digest=hashlib.sha256(result.stdout).hexdigest()
                    if reference is not None and digest!=reference: raise RuntimeError('Numerical divergence')
                    reference=digest; times[name]=float(result.stderr)
                    (output/f'p{players}-h{hidden}-r{pair}-{name}.json').write_text(json.dumps(dict(cpu_seconds=times[name],state_sha256=digest)))
                rows.append(times)
            ratios=[r['baseline']/r['candidate'] for r in rows]
            rng=random.Random(20261015)
            bootstrap=sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
            reduction=1-statistics.median(r['candidate']/r['baseline'] for r in rows)
            ci=[bootstrap[249],bootstrap[9749]]
            row=dict(players=players,hidden=hidden,pairs=rows,state_sha256=reference,
                     median_cpu_reduction=reduction,median_speedup=statistics.median(ratios),speedup_ci95=ci,
                     accepted=reduction>=.10 and ci[0]>1)
            report['workloads'].append(row)
            print(json.dumps(row),flush=True)
    report['passed']=all(r['accepted'] for r in report['workloads'])
    report['candidate_unchanged']=sha(source)==report['candidate_sha256']
    report['source_after']=validate.source_fingerprint()
    report['binaries']={name:sha(work/name) for name in ('baseline','candidate')}
    report['passed'] &= report['candidate_unchanged'] and report['source_before']==report['source_after']
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0
if __name__=='__main__': raise SystemExit(main())
