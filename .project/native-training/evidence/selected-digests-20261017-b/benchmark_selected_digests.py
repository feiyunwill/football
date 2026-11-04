"""Paired real-worker digest cost and partial-batch collector equivalence."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import random
import statistics
import time
from unittest import mock

import validate
from gfootball.training_workers import NativeWorkerPool
from gfootball.training_sampler import collect_episodes

def worker_cpu(pids):
    ticks=0
    for pid in pids:
        # Fields after comm start at stat field 3; utime/stime are fields 14/15.
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        ticks+=int(fields[11])+int(fields[12])
    return ticks/os.sysconf('SC_CLK_TCK')

def interval(ratios):
    rng=random.Random(20261017)
    values=sorted(statistics.median(rng.choices(ratios,k=len(ratios))) for _ in range(10000))
    return [values[249],values[9749]]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,source_before=validate.source_fingerprint(),
        environment=validate.runtime_identity(os.sys.executable),
        protocol=dict(workers=4,pairs=8,digest_rounds=512,
            criterion='single-selected digest median total parent+worker CPU reduction >=50%, paired bootstrap lower speedup >1',
            scope='digest IPC phase with one required worker; no whole-training speedup claim',
            collector='5 episodes x 8 steps x 4 workers; paired previous all-worker digest behavior',
            simulation='identical steps, resets, observations, rewards and required final state hashes'),
        tooling={Path(__file__).name:validate.sha(Path(__file__))})
    kwargs=dict(env_name='11_vs_11_easy_stochastic',representation='simple115v2',
        number_of_left_players_agent_controls=11,
        other_config_options=dict(render_resolution_x=160,render_resolution_y=90,
                                  physics_steps_per_frame=2,game_engine_random_seed=0))
    import gfootball_engine
    module=Path(gfootball_engine._gameplayfootball.__file__)
    report['engine']={str(p):validate.sha(p) for p in (module,module.with_name('libfootball_engine.so'))}
    with NativeWorkerPool(kwargs,workers=4,base_seed=42) as pool:
        pool.reset({i:i for i in range(4)}); reference=pool.digests()
        original=pool.digests; pairs=[]
        def phase(selected):
            child=worker_cpu(pool.worker_pids); parent=time.process_time(); wall=time.perf_counter()
            for _ in range(512):
                result=original([0]) if selected else original()
                expected_result={0:reference[0]} if selected else reference
                if result!=expected_result:
                    raise RuntimeError('Digest changed without any engine work')
            return dict(parent_cpu_seconds=time.process_time()-parent,
                        worker_cpu_seconds=worker_cpu(pool.worker_pids)-child,
                        wall_seconds=time.perf_counter()-wall,
                        worker_requests=512*(1 if selected else 4))
        for pair in range(8):
            row={}
            for name in (('baseline','candidate') if pair%2==0 else ('candidate','baseline')):
                row[name]=phase(name=='candidate')
            pairs.append(row); print('digest-pair',pair,flush=True)
        ratios=[(r['baseline']['parent_cpu_seconds']+r['baseline']['worker_cpu_seconds'])/
                (r['candidate']['parent_cpu_seconds']+r['candidate']['worker_cpu_seconds']) for r in pairs]
        ci=interval(ratios); reduction=1-statistics.median(1/r for r in ratios)
        report['digest']=dict(pairs=pairs,median_cpu_reduction=reduction,speedup_ci95=ci,
                             accepted=reduction>=.5 and ci[0]>1,worker_requests_reduction=.75)
        collected=[]; expected=None
        for pair in range(8):
            row={}
            for name in (('baseline','candidate') if pair%2==0 else ('candidate','baseline')):
                def all_workers(selected): return original()
                child=worker_cpu(pool.worker_pids); parent=time.process_time(); wall=time.perf_counter()
                with mock.patch.object(pool,'digests',side_effect=all_workers if name=='baseline' else original):
                    result=collect_episodes(pool,range(5),lambda obs,ctx:[0]*11,max_steps=8)
                identity=[asdict(episode) for episode in result.episodes]
                if expected is not None and identity!=expected: raise RuntimeError('Collector replay diverged')
                expected=identity
                row[name]=dict(wall_seconds=time.perf_counter()-wall,
                               parent_cpu_seconds=time.process_time()-parent,
                               worker_cpu_seconds=worker_cpu(pool.worker_pids)-child,
                               digest_ns=result.digest_ns,transitions=result.transitions)
            collected.append(row)
        report['collector']=dict(pairs=collected,episodes=expected,exact_replay=True,
            baseline_digest_worker_requests=8,candidate_digest_worker_requests=5,
            note='Short partial-batch diagnostic; no aggregate throughput acceptance claim')
    report['exit_codes']=pool.exit_codes
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    report['source_after']=validate.source_fingerprint()
    report['passed']=report['digest']['accepted'] and report['source_before']==report['source_after'] and pool.exit_codes==(0,)*4
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],digest=report['digest'])))
    return 0 if report['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
