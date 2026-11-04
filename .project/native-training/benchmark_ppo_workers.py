#!/usr/bin/env python3
"""Real on-policy PPO through existing spawn workers and production C++ math.

Diagnostic only. Each update ends all four episodes (terminal or horizon), so
checkpoints at update boundaries have no live environment or rollout to save.
Episode-keyed sampling and sorted updates preserve replay across worker counts.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import sysconfig
import time

import numpy as np
from validate import ROOT, sha, source_fingerprint, runtime_identity


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def core_contract():
    import _ppo_worker_core
    core = _ppo_worker_core.Core(1,42)
    before = canonical(core.state())
    bad = core.state(); bad['first'][0] = float('nan')
    try:
        core.restore(bad)
        raise AssertionError('Nonfinite optimizer accepted')
    except ValueError:
        pass
    if canonical(core.state()) != before:
        raise AssertionError('Failed restore mutated learner')
    for invalid in (np.zeros(2,dtype=np.float32),np.full(115,np.nan,dtype=np.float32)):
        try:
            core.decide(invalid,42,0)
            raise AssertionError('Invalid observation accepted')
        except ValueError:
            pass
    observation = np.zeros(115,dtype=np.float32)
    core.add(observation,[0],observation,1.,False,True,0,0)
    try:
        core.state()
        raise AssertionError('Mid-rollout checkpoint accepted')
    except ValueError:
        pass
    update = core.update()
    if not update['parameter_delta']>0:
        raise AssertionError('Missing real update')
    restored = _ppo_worker_core.Core(1,1)
    restored.restore(core.state())
    if canonical(restored.state()) != canonical(core.state()) or restored.decide(observation,123,0)!=core.decide(observation,123,0):
        raise AssertionError('Core restore diverged')
    broken = _ppo_worker_core.Core(1,42)
    broken.add(observation,[0],observation,0.,False,False,0,0)
    try:
        broken.update()
        raise AssertionError('Incomplete episode accepted')
    except ValueError:
        pass
    print(json.dumps(dict(passed=True,checks=6)))


def child(args):
    import _ppo_worker_core
    import gfootball_engine
    from gfootball.training_workers import NativeWorkerPool
    from gfootball.training_sampler import collect_episodes
    from gfootball.benchmark_training_workers import _resources
    core = _ppo_worker_core.Core(args.players, 42)
    identity = dict(schema=1, players=args.players, cadence=args.cadence, seed=42,
        runner=sha(Path(__file__)),
        source=source_fingerprint()['sha256'], core=sha(Path(_ppo_worker_core.__file__)),
        engine=sha(Path(gfootball_engine._gameplayfootball.__file__)))
    start_update = 0
    if args.load:
        if args.load.stat().st_size > 4*1024*1024:
            raise ValueError('Checkpoint byte budget exceeded')
        saved = json.loads(args.load.read_text())
        if saved['identity'] != identity or saved['next_update'] != saved['state']['version']:
            raise ValueError('Checkpoint identity/counter mismatch')
        core.restore(saved['state'])
        start_update = saved['next_update']
    kwargs = dict(env_name='11_vs_11_easy_stochastic', representation='simple115v2',
        number_of_left_players_agent_controls=args.players,
        other_config_options=dict(render_resolution_x=160, render_resolution_y=90,
                                  physics_steps_per_frame=args.cadence, game_engine_random_seed=0))
    def policy(obs, context):
        actions = core.decide(obs, context.seed, context.step)
        return actions[0] if args.players == 1 else actions
    def consume(event):
        core.add(event.observation, list(event.actions), event.following.observation,
                 float(np.mean(event.following.agent_rewards, dtype=np.float64)),
                 event.following.terminated, event.following.truncated,
                 event.context.episode_id, event.context.step)
    # Start the persistent multiprocessing tracker before the FD baseline.
    with NativeWorkerPool(kwargs, workers=1, base_seed=42) as warm:
        collect_episodes(warm, [999999], policy, max_steps=2)
    parent_before = _resources(os.getpid())
    startup = time.monotonic_ns()
    pool = NativeWorkerPool(kwargs, workers=args.workers, base_seed=42)
    startup = time.monotonic_ns() - startup
    rows = []
    try:
        collect_episodes(pool, range(args.workers), policy, max_steps=20)
        before = {pid: _resources(pid) for pid in pool.worker_pids}
        parent_cpu = time.process_time_ns()
        started = time.perf_counter_ns()
        for version in range(start_update, start_update + args.updates):
            collected = collect_episodes(pool, range(version*4, version*4+4), policy,
                                         max_steps=32, on_transition=consume)
            tick = time.perf_counter_ns()
            update = core.update()
            update_ns = time.perf_counter_ns() - tick
            native_update_ns = update.pop('native_update_ns')
            diagnostic_ns = update.pop('diagnostic_ns')
            if update['transitions'] != collected.transitions or not update['parameter_delta'] > 0:
                raise RuntimeError('Real update missing or transition count differs')
            rows.append(dict(version=version+1, collection=asdict(collected),
                             update=update, update_ns=update_ns,
                             native_update_ns=native_update_ns, diagnostic_ns=diagnostic_ns))
        wall = time.perf_counter_ns() - started
        cpu = time.process_time_ns() - parent_cpu
        after = {pid: _resources(pid) for pid in pool.worker_pids}
        resources = dict(parent=_resources(os.getpid()), workers=after,
            worker_cpu_seconds=sum(after[pid]['cpu_ticks']-before[pid]['cpu_ticks'] for pid in after)/os.sysconf('SC_CLK_TCK'))
        pids = list(pool.worker_pids)
    finally:
        pool.close()
    if pool.exit_codes != (0,)*args.workers or any(Path('/proc', str(pid)).exists() for pid in pids):
        raise RuntimeError('Worker cleanup failed')
    if _resources(os.getpid())['fds'] != parent_before['fds']:
        raise RuntimeError('Parent file descriptors leaked')
    checkpoint = dict(identity=identity, next_update=start_update+args.updates, state=core.state())
    checkpoint_bytes = canonical(checkpoint)
    if len(checkpoint_bytes)>4*1024*1024:
        raise ValueError('Checkpoint byte budget exceeded')
    if args.save:
        if args.save.exists():
            raise ValueError('Checkpoint destination exists')
        temporary = args.save.with_suffix('.tmp')
        with temporary.open('xb') as stream:
            stream.write(checkpoint_bytes); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, args.save)
    # Timing is excluded from replay identities.
    replay = [dict(version=row['version'], episodes=row['collection']['episodes'], update=row['update']) for row in rows]
    print(json.dumps(dict(passed=True, players=args.players, cadence=args.cadence, workers=args.workers,
        loaded_module=str(Path(gfootball_engine._gameplayfootball.__file__).resolve()),
        wall_ns=wall, parent_cpu_ns=cpu, startup_ns=startup, resources=resources,
        transitions=sum(row['update']['transitions'] for row in rows), iterations=rows, replay=replay,
        checkpoint_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(), worker_pids=pids,
        checkpoint_bytes=len(checkpoint_bytes), next_update=checkpoint['next_update']), allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--core-contract', action='store_true')
    parser.add_argument('--players', type=int, choices=(1,11), default=1)
    parser.add_argument('--cadence', type=int, choices=(2,10), default=10)
    parser.add_argument('--workers', type=int, choices=(1,2,4), default=1)
    parser.add_argument('--updates', type=int, choices=(2,4), default=4)
    parser.add_argument('--load', type=Path)
    parser.add_argument('--save', type=Path)
    parser.add_argument('--build-root', type=Path)
    parser.add_argument('--work-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.core_contract:
        core_contract(); return 0
    if args.child:
        child(args); return 0
    if not all((args.build_root, args.work_root, args.output)):
        parser.error('build-root, work-root and output required')
    build, work, output = (p.resolve() for p in (args.build_root,args.work_root,args.output))
    if work == ROOT or ROOT in work.parents:
        parser.error('work-root must be outside the repository')
    work.mkdir(parents=True,exist_ok=False); output.mkdir(parents=True,exist_ok=False)
    stage = build / 'validation-stage'
    env = dict(os.environ, PYTHONPATH=str(work)+os.pathsep+str(stage)+os.pathsep+str(ROOT),
        PYGAME_HIDE_SUPPORT_PROMPT='1',
        GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'), GFOOTBALL_FONT=str(ROOT/'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    report = dict(passed=False, source_before=source_fingerprint(), commands=[], workloads=[],
        engine_sha256=sha(stage/'gfootball_engine/libfootball_engine.so'),
        extension_sha256=sha(stage/'gfootball_engine/_gameplayfootball.so'),
        environment=runtime_identity(sys.executable), protocol=dict(episodes_per_update=4,horizon=32,
        updates=4,repeats=3,hidden=16,epochs=4,policy='production C++ categorical sample',
        sampling='episode-keyed SplitMix64, not the native CLI sequential RNG stream',
        checkpoints='diagnostic JSON at full episode/update boundaries; not FPPO format',
        timing='reset+IPC+actual inference+callback+hashing+PPO updates; excludes startup/warmup/close/saving',
        scope='short reset-heavy episodes; not a sustained 11v11 learning-efficiency claim',
        diagnostics='exact categorical KL(old||new) on collected states; post-update value MSE against frozen rollout targets; included in wall, timed separately',
        resource_limits='RSS sums double-count shared pages; snapshots are end-of-run, HWM is lifetime'))
    def run(name, command, timeout=300):
        print(name,flush=True)
        log=output/(name+'.log'); tick=time.monotonic()
        with log.open('wb') as stream:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(); raise
        report['commands'].append(dict(name=name,argv=command,exit_code=code,seconds=time.monotonic()-tick,sha256=sha(log)))
        if code: raise RuntimeError(name+' failed')
        return log
    try:
        includes=subprocess.check_output([sys.executable,'-m','pybind11','--includes'],text=True).split()
        extension=work/('_ppo_worker_core'+sysconfig.get_config_var('EXT_SUFFIX'))
        run('build-core',[os.environ.get('CXX','c++'),'-std=c++23','-O3','-shared','-fPIC',*includes,
            '-I'+str(ROOT/'engine/src'),str(Path(__file__).with_name('ppo_worker_core.cpp')),
            str(ROOT/'engine/src/training/categorical_policy.cpp'),str(ROOT/'engine/src/training/ppo_math.cpp'),
            '-o',str(extension)])
        report['core_sha256']=sha(extension)
        report['tooling']={p.name:sha(p) for p in (Path(__file__),Path(__file__).with_name('ppo_worker_core.cpp'))}
        run('core-contract',[sys.executable,str(Path(__file__)),'--core-contract'])
        reference={}; samples={}
        for players in (1,11):
            for cadence in (2,10):
                for repeat in range(3):
                    counts=(1,2,4); order=counts[repeat:]+counts[:repeat]
                    for count in order:
                        name=f'p{players}-c{cadence}-w{count}-r{repeat}'
                        command=[sys.executable,str(Path(__file__)), '--child','--players',str(players),
                            '--cadence',str(cadence),'--workers',str(count)]
                        if (players,cadence,count,repeat)==(1,10,1,0):
                            command+=['--save',str(work/'full.json')]
                        data=json.loads(run(name,command).read_text())
                        if Path(data['loaded_module']) != stage/'gfootball_engine/_gameplayfootball.so':
                            raise RuntimeError('Wrong staged engine loaded')
                        key=(players,cadence)
                        replay=(data['replay'],data['checkpoint_sha256'])
                        if key in reference and reference[key]!=replay:
                            raise RuntimeError('Worker count/repeat changed actual PPO training')
                        reference[key]=replay
                        samples.setdefault((players,cadence,count),[]).append(data)
        for (players,cadence,count),rows in samples.items():
            report['workloads'].append(dict(players=players,cadence=cadence,workers=count,samples=rows,
                median_transitions_per_second=statistics.median(r['transitions']*1e9/r['wall_ns'] for r in rows),
                median_update_fraction=statistics.median(sum(i['update_ns'] for i in r['iterations'])/r['wall_ns'] for r in rows),
                median_native_update_fraction=statistics.median(sum(i['native_update_ns'] for i in r['iterations'])/r['wall_ns'] for r in rows),
                median_diagnostic_fraction=statistics.median(sum(i['diagnostic_ns'] for i in r['iterations'])/r['wall_ns'] for r in rows),
                median_policy_fraction=statistics.median(sum(i['collection']['policy_ns'] for i in r['iterations'])/r['wall_ns'] for r in rows),
                median_callback_fraction=statistics.median(sum(i['collection']['callback_ns'] for i in r['iterations'])/r['wall_ns'] for r in rows)))
        report['scaling'] = []
        for players in (1,11):
            for cadence in (2,10):
                pair={r['workers']:r for r in report['workloads'] if r['players']==players and r['cadence']==cadence}
                report['scaling'].append(dict(players=players,cadence=cadence,
                    speedup4=pair[4]['median_transitions_per_second']/pair[1]['median_transitions_per_second']))
        report['twofold_target_observed']=all(row['speedup4']>=2 for row in report['scaling'])
        prefix=json.loads(run('prefix',[sys.executable,str(Path(__file__)),'--child','--updates','2',
            '--save',str(work/'prefix.json')]).read_text())
        resumed=json.loads(run('resumed',[sys.executable,str(Path(__file__)),'--child','--updates','2','--workers','4',
            '--load',str(work/'prefix.json'),'--save',str(work/'resumed.json')]).read_text())
        full_replay,full_hash=reference[(1,10)]
        if (prefix['replay']!=full_replay[:2] or resumed['replay']!=full_replay[2:] or
            resumed['checkpoint_sha256']!=full_hash or (work/'full.json').read_bytes()!=(work/'resumed.json').read_bytes()):
            raise RuntimeError('Cross-process/count checkpoint resume diverged')
        report['resume_verified']=True
        report['passed']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        report['source_after']=source_fingerprint()
        if report['source_before']!=report['source_after']:
            report.update(passed=False,error='Source/resources changed during benchmark')
        if 'tooling' in report:
            report['tooling_after']={p.name:sha(p) for p in (Path(__file__),Path(__file__).with_name('ppo_worker_core.cpp'))}
            if report['tooling_after']!=report['tooling']:
                report.update(passed=False,error='Diagnostic tooling changed during benchmark')
        report['environment_after']=runtime_identity(sys.executable)
        if report['environment_after']!=report['environment']:
            report.update(passed=False,error='Benchmark environment changed')
        if (sha(stage/'gfootball_engine/libfootball_engine.so')!=report['engine_sha256'] or
            sha(stage/'gfootball_engine/_gameplayfootball.so')!=report['extension_sha256']):
            report.update(passed=False,error='Staged engine artifacts changed')
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
