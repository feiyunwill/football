#!/usr/bin/env python3
"""Separate diagnostic latency run; never substitute for uninstrumented timing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from benchmark_next_baseline import summary
from validate import ROOT, sha, source_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    stage = args.build_root.resolve() / 'validation-stage'
    sys.path[:0] = [str(stage), str(ROOT)]
    os.environ.update(GFOOTBALL_DATA_DIR=str(ROOT / 'engine/data'),
                      GFOOTBALL_FONT=str(ROOT / 'engine/fonts/AlegreyaSansSC-ExtraBold.ttf'))
    import psutil
    from gfootball.gymnasium import FootballEnv
    from gfootball.profile_native_training import policy
    import gfootball_engine
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    process = psutil.Process()
    loaded = Path(gfootball_engine._gameplayfootball.__file__).resolve()
    report = dict(passed=False, source_before=source_fingerprint(), workloads=[],
                  cpu_affinity=sorted(os.sched_getaffinity(0)),
                  cpuinfo=Path('/proc/cpuinfo').read_text(),
                  memory_total=psutil.virtual_memory().total,
                  loaded_module=str(loaded), binary_sha256=sha(loaded),
                  limitation='Diagnostic per-step clocks/list writes add overhead; initialization/reset/RSS/digest excluded from step samples')
    try:
        if loaded != stage / 'gfootball_engine/_gameplayfootball.so':
            raise RuntimeError('Wrong extension loaded')
        for players in (1, 11):
            for cadence in (2, 10):
                for feedback in (False, True):
                    started = time.perf_counter_ns()
                    env = FootballEnv(backend='native', env_name='11_vs_11_easy_stochastic',
                        number_of_left_players_agent_controls=players,
                        other_config_options={'render_resolution_x':160, 'render_resolution_y':90,
                            'physics_steps_per_frame':cadence, 'game_engine_random_seed':42})
                    try:
                        construction = time.perf_counter_ns() - started
                        started = time.perf_counter_ns()
                        observation = env.reset(seed=42)[0]
                        reset = time.perf_counter_ns() - started
                        core = env._env._native
                        for _ in range(20):
                            observation = core.step([0] * players)[0]
                        rss_before = process.memory_info().rss
                        wall, cpu = [], []
                        for tick in range(1024):
                            if feedback:
                                action = policy(observation)
                                joint = [action] if players == 1 else action.tolist()
                            else:
                                joint = [(tick + player) % 19 for player in range(players)]
                            cpu_start = time.process_time_ns()
                            start = time.perf_counter_ns()
                            observation, _, terminal, _ = core.step(joint)
                            wall.append(time.perf_counter_ns() - start)
                            cpu.append(time.process_time_ns() - cpu_start)
                            if terminal:
                                raise RuntimeError('Latency workload ended early')
                        report['workloads'].append(dict(players=players, cadence=cadence, feedback=feedback,
                            construction_ns=construction, reset_ns=reset, wall_ns=summary(wall), cpu_ns=summary(cpu),
                            raw_wall_ns=wall, raw_cpu_ns=cpu, rss_before=rss_before,
                            rss_after=process.memory_info().rss,
                            digest=hashlib.sha256(core.get_state_digest()).hexdigest()))
                    finally:
                        env.close()
        report['passed'] = True
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        report['source_after'] = source_fingerprint()
        if report['source_before'] != report['source_after']:
            report.update(passed=False, error='Source/resources changed')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=report['passed'], error=report.get('error'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
