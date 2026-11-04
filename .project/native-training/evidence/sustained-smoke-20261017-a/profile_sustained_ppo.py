"""Bounded sustained on-policy PPO baseline with streamed costs and resources."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import time

import numpy as np
from validate import ROOT, sha, source_fingerprint, runtime_identity

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def write_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(canonical(value)+b'\n'); os.replace(temporary,path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=1800)
    args=parser.parse_args()
    if not math.isfinite(args.seconds) or not 5<=args.seconds<=7200: parser.error('seconds must be in [5,7200]')
    work=args.work_root.resolve(); output=args.output.resolve(); stage=args.build_root.resolve()/'validation-stage'
    if work==ROOT or ROOT in work.parents: parser.error('work-root must be external')
    work.mkdir(parents=True,exist_ok=False); output.mkdir(parents=True,exist_ok=False)
    sys.path[:0]=[str(work),str(stage),str(ROOT)]
    os.environ.update(PYTHONPATH=os.pathsep.join((str(work),str(stage),str(ROOT))),
        PYGAME_HIDE_SUPPORT_PROMPT='1',GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),
        GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    bridge=Path(__file__).with_name('ppo_worker_core.cpp')
    report=dict(passed=False,status='preparing',source_before=source_fingerprint(),
        environment_before=runtime_identity(sys.executable),
        tooling={p.name:sha(p) for p in (Path(__file__),bridge)},
        protocol=dict(requested_seconds=args.seconds,players=11,cadence=2,workers=4,
            episodes_per_update=4,horizon=64,hidden=16,epochs=4,minibatch=64,
            scope='duration baseline with short complete episodes; not 11v11 competence or worker scaling proof',
            sampling='episode-keyed sampling; sorted production C++ PPO updates',
            timings='wall stages are disjoint; step RPC includes engine, IPC and scheduling',
            resources='RSS sum double-counts shared pages; HWM is process lifetime; diagnostics not formal product memory gates',
            checkpoint='diagnostic learner JSON at complete episode/update boundaries, not FPPO'))
    extension=work/('_ppo_worker_core'+sysconfig.get_config_var('EXT_SUFFIX'))
    includes=subprocess.check_output([sys.executable,'-m','pybind11','--includes'],text=True).split()
    command=['c++','-std=c++23','-O3','-shared','-fPIC',*includes,'-I'+str(ROOT/'engine/src'),
             str(bridge),str(ROOT/'engine/src/training/categorical_policy.cpp'),
             str(ROOT/'engine/src/training/ppo_math.cpp'),'-o',str(extension)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    (output/'build-core.log').write_text(result.stdout+result.stderr)
    report['build']=dict(argv=command,exit_code=result.returncode,log_sha256=sha(output/'build-core.log'))
    result.check_returncode()
    import _ppo_worker_core
    import gfootball_engine
    from gfootball.training_workers import NativeWorkerPool
    from gfootball.training_sampler import collect_episodes
    from gfootball.benchmark_training_workers import _resources
    module=Path(gfootball_engine._gameplayfootball.__file__).resolve()
    if module!=stage/'gfootball_engine/_gameplayfootball.so': raise RuntimeError('Wrong staged engine')
    report['artifacts']={str(p):sha(p) for p in (extension,module,module.with_name('libfootball_engine.so'))}
    for p in (Path(__file__),bridge): (output/p.name).write_bytes(p.read_bytes())
    identity=dict(source=report['source_before']['sha256'],core=sha(extension),runner=sha(Path(__file__)),
                  engine=sha(module),players=11,cadence=2,seed=42)
    core=_ppo_worker_core.Core(11,42)
    kwargs=dict(env_name='11_vs_11_easy_stochastic',representation='simple115v2',
        number_of_left_players_agent_controls=11,
        other_config_options=dict(render_resolution_x=160,render_resolution_y=90,
                                  physics_steps_per_frame=2,game_engine_random_seed=0))
    def policy(observation,context): return core.decide(observation,context.seed,context.step)
    def consume(event):
        core.add(event.observation,list(event.actions),event.following.observation,
                 float(np.mean(event.following.agent_rewards,dtype=np.float64)),
                 event.following.terminated,event.following.truncated,event.context.episode_id,event.context.step)
    with NativeWorkerPool(kwargs,workers=1,base_seed=42) as warm:
        collect_episodes(warm,[999999],policy,max_steps=2)
    parent_before=_resources(os.getpid())
    tick=time.perf_counter_ns(); pool=NativeWorkerPool(kwargs,workers=4,base_seed=42)
    report['startup_ns']=time.perf_counter_ns()-tick
    version=transitions=0; totals={}; replay=hashlib.sha256(); samples=[]
    checkpoint_ns=resource_ns=0
    def observe(elapsed):
        return dict(elapsed_seconds=elapsed,parent=_resources(os.getpid()),
                    workers={str(pid):_resources(pid) for pid in pool.worker_pids})
    def checkpoint():
        state=core.state(); saved=dict(identity=identity,next_update=version,state=state)
        # A second instance verifies the complete learner payload at every save.
        restored=_ppo_worker_core.Core(11,1); restored.restore(state)
        if canonical(restored.state())!=canonical(state): raise RuntimeError('Checkpoint restore diverged')
        write_json(output/'latest-checkpoint.json',saved)
    try:
        collect_episodes(pool,range(4),policy,max_steps=20)
        reset_original,step_original=pool.reset,pool.step
        counters=dict(reset_ns=0,step_rpc_ns=0)
        def timed(name,method):
            def call(*values,**keywords):
                tick=time.perf_counter_ns()
                try: return method(*values,**keywords)
                finally: counters[name]+=time.perf_counter_ns()-tick
            return call
        pool.reset=timed('reset_ns',reset_original); pool.step=timed('step_rpc_ns',step_original)
        started=time.perf_counter_ns(); parent_cpu=time.process_time_ns()
        samples.append(observe(0)); last_observed=last_checkpoint=0.0
        report['status']='running'; write_json(output/'report.json',report)
        with (output/'iterations.jsonl').open('w') as stream, (output/'resources.jsonl').open('w') as resources:
            resources.write(canonical(samples[-1]).decode()+'\n'); resources.flush()
            while (time.perf_counter_ns()-started)/1e9<args.seconds:
                tick=time.perf_counter_ns(); counters.update(reset_ns=0,step_rpc_ns=0)
                collected=collect_episodes(pool,range(version*4,version*4+4),policy,max_steps=64,on_transition=consume)
                update_tick=time.perf_counter_ns(); update=core.update(); update_wall=time.perf_counter_ns()-update_tick
                inner=update.pop('native_update_ns'); diagnostic=update.pop('diagnostic_ns')
                if update['transitions']!=collected.transitions or update['optimizer_steps']<=0:
                    raise RuntimeError('Missing real PPO update')
                if not all(math.isfinite(v) for v in update.values()): raise RuntimeError('Nonfinite metrics')
                version+=1; transitions+=collected.transitions
                stages=dict(reset_ns=counters['reset_ns'],step_rpc_ns=counters['step_rpc_ns'],
                    policy_ns=collected.policy_ns,callback_ns=collected.callback_ns,digest_ns=collected.digest_ns,
                    native_update_ns=inner,diagnostic_ns=diagnostic,
                    update_bridge_ns=update_wall-inner-diagnostic,
                    collection_other_ns=collected.wall_ns-sum(counters.values())-collected.policy_ns-collected.callback_ns-collected.digest_ns)
                if min(stages.values())<0: raise RuntimeError('Overlapping stage accounting')
                for name,value in stages.items(): totals[name]=totals.get(name,0)+value
                loop_ns=time.perf_counter_ns()-tick
                totals['iteration_ns']=totals.get('iteration_ns',0)+loop_ns
                replay.update(canonical(dict(episodes=[asdict(e) for e in collected.episodes],update=update)))
                elapsed=(time.perf_counter_ns()-started)/1e9
                stream.write(canonical(dict(version=version,elapsed_seconds=elapsed,transitions=collected.transitions,
                    iteration_ns=loop_ns,stages=stages,update=update)).decode()+'\n')
                if elapsed-last_observed>=10:
                    stream.flush(); tick=time.perf_counter_ns(); snapshot=observe(elapsed)
                    samples.append(snapshot); resources.write(canonical(snapshot).decode()+'\n'); resources.flush()
                    resource_ns+=time.perf_counter_ns()-tick; last_observed=elapsed
                    progress=dict(status='running',elapsed_seconds=elapsed,updates=version,transitions=transitions,
                        transitions_per_second=transitions/elapsed,stage_fractions={k:v/totals['iteration_ns'] for k,v in totals.items() if k!='iteration_ns'},
                        parent_rss_bytes=snapshot['parent']['rss_bytes'],
                        worker_rss_sum_bytes=sum(r['rss_bytes'] for r in snapshot['workers'].values()))
                    write_json(output/'progress.json',progress)
                    print(json.dumps(progress),flush=True)
                if elapsed-last_checkpoint>=60:
                    tick=time.perf_counter_ns(); checkpoint(); checkpoint_ns+=time.perf_counter_ns()-tick
                    last_checkpoint=elapsed
            elapsed=(time.perf_counter_ns()-started)/1e9
            report.update(duration_seconds=elapsed,updates=version,transitions=transitions,
                transitions_per_second=transitions/elapsed,parent_cpu_ns=time.process_time_ns()-parent_cpu,
                stage_totals_ns=totals,checkpoint_ns=checkpoint_ns,resource_sampling_ns=resource_ns,
                replay_sha256=replay.hexdigest())
        samples.append(observe(elapsed)); report['resources']=samples
        checkpoint(); report['checkpoint_sha256']=sha(output/'latest-checkpoint.json')
        report['status']='completed'
    except BaseException as error:
        report.update(status='failed',error=f'{type(error).__name__}: {error}')
    finally:
        pool.close(); report['exit_codes']=pool.exit_codes
        report['parent_after_close']=_resources(os.getpid())
        report['parent_before']=parent_before
        report['workers_reaped']=all(not Path('/proc',str(pid)).exists() for pid in pool.worker_pids)
        report['source_after']=source_fingerprint(); report['environment_after']=runtime_identity(sys.executable)
        report['artifacts_after']={p:sha(Path(p)) for p in report['artifacts']}
        report['tooling_after']={p.name:sha(p) for p in (Path(__file__),bridge)}
        report['passed']=(report['status']=='completed' and report['duration_seconds']>=args.seconds and version>0
            and report['source_before']==report['source_after'] and report['environment_before']==report['environment_after']
            and report['artifacts']==report['artifacts_after'] and report['tooling']==report['tooling_after']
            and pool.exit_codes==(0,)*4 and report['workers_reaped']
            and report['parent_after_close']['fds']==parent_before['fds'])
        for name in ('iterations.jsonl','resources.jsonl'): report[name+'_sha256']=sha(output/name)
        write_json(output/'report.json',report)
    print(json.dumps(dict(passed=report['passed'],status=report['status'],updates=version,transitions=transitions)))
    return 0 if report['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
