"""Linux-only same-process, interleaved production PPO comparison; no fast-math."""
import argparse
import ctypes
import hashlib
import json
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
    args=parser.parse_args(); work=args.work_root.resolve(); output=args.output.resolve()
    if work==ROOT or ROOT in work.parents: parser.error('external work-root required')
    output.mkdir(parents=True,exist_ok=False)
    cpu=min(os.sched_getaffinity(0)); os.sched_setaffinity(0,{cpu})
    report=dict(passed=False,source_before=validate.source_fingerprint(),workloads=[],
        protocol=dict(pairs=24,repeats=8,samples=128,warmup=True,pinned_cpu=cpu,
        criterion='all four median update CPU reductions >=10%, paired bootstrap lower speedup >1',
        timing='UpdatePpo only, process CPU, baseline/candidate alternating in one process',
        scope='isolated PPO update; no end-to-end engine throughput claim',
        loading='RTLD_LOCAL|RTLD_DEEPBIND isolates identical C++ production symbols'))
    probe=Path(__file__).with_name('ppo_paired_probe.cpp')
    inputs=[Path(__file__),probe,ROOT/'engine/src/training/ppo_math.hpp',ROOT/'engine/src/training/categorical_policy.hpp']
    report['inputs']={str(p.relative_to(ROOT)):sha(p) for p in inputs}
    report['compiler']=subprocess.check_output(['c++','--version'],text=True)
    report['cpu']=Path('/proc/cpuinfo').read_text().split('\n\n')[0]
    cores={}; report['artifacts']={}
    for name in ('baseline','candidate'):
        policy=work/'baseline-policy.cpp' if name=='baseline' else ROOT/'engine/src/training/categorical_policy.cpp'
        math=work/'baseline.cpp' if name=='baseline' else ROOT/'engine/src/training/ppo_math.cpp'
        for label,path in [('policy',policy),('math',math)]:
            (output/f'{name}-{label}.cpp').write_bytes(path.read_bytes())
            report['artifacts'][f'{name}-{label}']=sha(path)
        library=work/f'{name}-paired.so'
        command=['c++','-std=c++23','-O3','-shared','-fPIC','-I'+str(ROOT/'engine/src'),
                 str(probe),str(policy),str(math),'-o',str(library)]
        result=subprocess.run(command,capture_output=True,text=True)
        (output/f'{name}-build.log').write_text(result.stdout+result.stderr); result.check_returncode()
        report['artifacts'][name+'-binary']=sha(library)
        lib=ctypes.CDLL(str(library),mode=os.RTLD_LOCAL|os.RTLD_DEEPBIND)
        run=lib.run_probe; run.argtypes=[ctypes.c_size_t]*4+[ctypes.c_char_p]; run.restype=ctypes.c_double
        cores[name]=(lib,run)
    for p in inputs[:2]: (output/p.name).write_bytes(p.read_bytes())
    for players in (1,11):
        for hidden in (16,64):
            rows=[]; reference=None
            for pair in range(-1,24):
                times={}
                for name in (('baseline','candidate') if pair%2==0 else ('candidate','baseline')):
                    state=work/'paired-state.bin'
                    value=cores[name][1](players,hidden,128,8,os.fsencode(state))
                    if value<=0: raise RuntimeError('Native probe failed')
                    digest=sha(state)
                    if reference is not None and reference!=digest: raise RuntimeError('Numerical divergence')
                    reference=digest; times[name]=value
                if pair>=0: rows.append(times)
            ratios=[r['baseline']/r['candidate'] for r in rows]
            rng=random.Random(20261015)
            boot=sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
            reduction=1-statistics.median(r['candidate']/r['baseline'] for r in rows)
            row=dict(players=players,hidden=hidden,pairs=rows,state_sha256=reference,
                     median_cpu_reduction=reduction,speedup_ci95=[boot[249],boot[9749]],
                     accepted=reduction>=.10 and boot[249]>1)
            report['workloads'].append(row); print(json.dumps(row),flush=True)
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    report['source_after']=validate.source_fingerprint()
    report['passed']=all(r['accepted'] for r in report['workloads']) and report['source_before']==report['source_after']
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0
if __name__=='__main__': raise SystemExit(main())
