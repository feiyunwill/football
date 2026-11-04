"""Separate instrumented worker-CPU run; never used as throughput evidence."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import time
import validate

def profiled_worker(channel,config):
    # Spawn imports a clean production worker module; the parent's patch is not
    # inherited. Use process CPU so parent-policy waits do not count as work.
    from gfootball.training_workers import _worker_main
    from gfootball.gymnasium import FootballEnv
    directory=Path(os.environ['FOOTBALL_DIAGNOSTIC_CPU_DIR'])
    directory.mkdir(parents=True,exist_ok=True)
    measured={name:dict(calls=0,wall_ns=0,cpu_ns=0) for name in ('step','reset')}
    def timed(name,method):
        def call(self,*args,**kwargs):
            wall=time.perf_counter_ns(); cpu=time.process_time_ns()
            try: return method(self,*args,**kwargs)
            finally:
                measured[name]['calls']+=1
                measured[name]['cpu_ns']+=time.process_time_ns()-cpu
                measured[name]['wall_ns']+=time.perf_counter_ns()-wall
        return call
    FootballEnv.step=timed('step',FootballEnv.step)
    FootballEnv.reset=timed('reset',FootballEnv.reset)
    def schedstat():
        path=Path('/proc/self/schedstat')
        return list(map(int,path.read_text().split())) if path.exists() else None
    before=schedstat()
    profiler=cProfile.Profile(timer=time.process_time)
    try: profiler.runcall(_worker_main,channel,config)
    finally:
        profiler.dump_stats(str(directory/f'worker-{os.getpid()}.pstats'))
        (directory/f'worker-{os.getpid()}-timings.json').write_text(json.dumps(dict(
            calls=measured,schedstat_before=before,schedstat_after=schedstat(),
            note='Process CPU and cumulative call wall are not additive to parent RPC wall; includes profiling/warmup. Zero schedstat wait may mean accounting disabled.'))+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--updates',type=int,default=128)
    args=parser.parse_args()
    if not 4<=args.updates<=512: parser.error('updates must be in [4,512]')
    output=args.output.resolve()
    os.environ['FOOTBALL_DIAGNOSTIC_CPU_DIR']=str(output/'worker-cpu')
    sys.path.insert(0,str(validate.ROOT))
    import gfootball.training_workers as workers
    workers._worker_main=profiled_worker
    import profile_matched_ppo
    sys.argv=[str(Path(profile_matched_ppo.__file__)), '--build-root',str(args.build_root),
        '--work-root',str(args.work_root),'--output',str(output),'--workers','4',
        '--updates',str(args.updates),'--seconds','600']
    code=profile_matched_ppo.main()
    if code: return code
    run=json.loads((output/'report.json').read_text())
    pids=run['resources'][0]['workers'].keys()
    files=[output/'worker-cpu'/f'worker-{pid}.pstats' for pid in pids]
    timing_files=[output/'worker-cpu'/f'worker-{pid}-timings.json' for pid in pids]
    worker_timings={str(pid):json.loads(path.read_text()) for pid,path in zip(pids,timing_files)}
    combined={}; total=0.
    for path in files:
        stats=pstats.Stats(str(path)); total+=stats.total_tt
        for key,(primitive,calls,self_cpu,inclusive_cpu,callers) in stats.stats.items():
            row=combined.setdefault(key,dict(calls=0,self_cpu_seconds=0.,inclusive_cpu_seconds=0.))
            row['calls']+=calls; row['self_cpu_seconds']+=self_cpu; row['inclusive_cpu_seconds']+=inclusive_cpu
    rows=[dict(file=key[0],line=key[1],function=key[2],**value) for key,value in combined.items()]
    rows.sort(key=lambda r:r['self_cpu_seconds'],reverse=True)
    summary=dict(passed=True,scope='Instrumented child process CPU; excludes blocked waits and includes profiling distortion; not throughput/scaling evidence',
        measured_worker_pids=list(pids),profiled_cpu_seconds=total,
        top_self_cpu=rows[:40],top_inclusive_cpu=sorted(rows,key=lambda r:r['inclusive_cpu_seconds'],reverse=True)[:40],
        step_reset_wrappers=[r for r in rows if r['file'].endswith('/gfootball/gymnasium.py') and r['function'] in ('step','reset')],
        profiles={str(p.relative_to(output)):validate.sha(p) for p in files},
        worker_call_timings=worker_timings,
        timing_files={str(p.relative_to(output)):validate.sha(p) for p in timing_files},
        run_report_sha256=validate.sha(output/'report.json'),runner_sha256=validate.sha(Path(__file__)),
        note='Environment construction, warmup and shutdown inside worker entry are included; pre-profiler imports and the separate warmup worker are excluded.')
    (output/'cpu-analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True,profiled_cpu_seconds=total)))
    return 0
if __name__=='__main__': raise SystemExit(main())
