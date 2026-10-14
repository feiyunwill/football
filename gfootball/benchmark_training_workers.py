"""Rotating 1/2/4-worker feedback workloads with replay and Linux resource evidence."""
import argparse
from dataclasses import asdict
import json
import multiprocessing
import os
from pathlib import Path
import statistics
import time

from gfootball.profile_native_training import policy
from gfootball.training_sampler import collect_episodes
from gfootball.training_workers import NativeWorkerPool


def _resources(pid):
  root = Path('/proc') / str(pid)
  # comm may contain spaces/parentheses; fields after the closing ')' start at state.
  fields = (root / 'stat').read_text().rpartition(') ')[2].split()
  status = dict(line.split(':', 1) for line in (root / 'status').read_text().splitlines() if ':' in line)
  return {'cpu_ticks': int(fields[11]) + int(fields[12]),
          'rss_bytes': int(status['VmRSS'].split()[0]) * 1024,
          'hwm_bytes': int(status['VmHWM'].split()[0]) * 1024,
          'fds': len(list((root / 'fd').iterdir()))}


def benchmark(steps, repeats, episodes):
  if not Path('/proc/self/stat').is_file():
    raise RuntimeError('Resource benchmark requires Linux /proc')
  import gfootball_engine
  results = []
  reference = {}
  counts = (1, 2, 4)
  ticks_per_second = os.sysconf('SC_CLK_TCK')
  kwargs = {'env_name': '11_vs_11_easy_stochastic', 'representation': 'simple115v2',
            'other_config_options': {'render_resolution_x': 160, 'render_resolution_y': 90,
                                     'game_engine_random_seed': 0}}
  # Initialize the persistent multiprocessing resource tracker before FD baselines.
  with NativeWorkerPool(kwargs) as warmup:
    collect_episodes(warmup, (0,), lambda obs, context: policy(obs), max_steps=20)
  child_baseline = {child.pid for child in multiprocessing.active_children()}
  for players in (1, 11):
    kwargs['number_of_left_players_agent_controls'] = players
    for cadence in (2, 10):
      kwargs['other_config_options']['physics_steps_per_frame'] = cadence
      samples = {count: [] for count in counts}
      for repeat in range(repeats):
        order = counts[repeat % 3:] + counts[:repeat % 3]
        for count in order:
          print(f'players={players} cadence={cadence} workers={count} repeat={repeat}', flush=True)
          parent_before = _resources(os.getpid())
          tick = time.perf_counter_ns()
          pool = NativeWorkerPool(kwargs, workers=count, base_seed=42)
          startup_ns = time.perf_counter_ns() - tick
          try:
            collect_episodes(pool, range(count), lambda obs, context: policy(obs), max_steps=20)
            cpu_before = {pid: _resources(pid)['cpu_ticks'] for pid in pool.worker_pids}
            observed = {'parent_rss_bytes': 0, 'worker_rss_sum_bytes': 0,
                        'worker_hwm_sum_bytes': 0, 'worker_fds': 0}
            def observe():
              parent = _resources(os.getpid())
              children = [_resources(pid) for pid in pool.worker_pids]
              observed['parent_rss_bytes'] = max(observed['parent_rss_bytes'], parent['rss_bytes'])
              for name, key in (('worker_rss_sum_bytes', 'rss_bytes'),
                                ('worker_hwm_sum_bytes', 'hwm_bytes'), ('worker_fds', 'fds')):
                observed[name] = max(observed[name], sum(child[key] for child in children))
            observe()
            streamed = 0
            def consume(event):
              nonlocal streamed
              streamed += 1
              if streamed % 32 == 0: observe()
            parent_cpu = time.process_time_ns()
            collected = collect_episodes(pool, range(episodes), lambda obs, context: policy(obs),
                                         max_steps=steps, on_transition=consume)
            parent_cpu = time.process_time_ns() - parent_cpu
            observe()
            children_after = {pid: _resources(pid) for pid in pool.worker_pids}
            worker_cpu_seconds = sum(children_after[pid]['cpu_ticks'] - cpu_before[pid]
                                     for pid in pool.worker_pids) / ticks_per_second
            replay = [asdict(row) for row in collected.episodes]
            key = (players, cadence)
            if key not in reference: reference[key] = replay
            if replay != reference[key]: raise RuntimeError('Worker count/repeat changed episode replay')
            if streamed != collected.transitions: raise RuntimeError('Missing streamed transitions')
            sample = {'repeat': repeat, 'startup_ns': startup_ns, 'collection': asdict(collected),
                      'parent_cpu_ns': parent_cpu, 'worker_cpu_seconds': worker_cpu_seconds,
                      'observed_resources': observed, 'worker_pids': list(pool.worker_pids),
                      'cpu_affinity': sorted(os.sched_getaffinity(0))}
          finally:
            tick = time.perf_counter_ns()
            pool.close()
            close_ns = time.perf_counter_ns() - tick
          parent_after = _resources(os.getpid())
          if (pool.exit_codes != (0,) * count or parent_after['fds'] != parent_before['fds']
              or {child.pid for child in multiprocessing.active_children()} != child_baseline
              or any(Path('/proc', str(pid)).exists() for pid in pool.worker_pids)):
            raise RuntimeError('Worker process/FD cleanup mismatch')
          sample.update(close_ns=close_ns, exit_codes=list(pool.exit_codes),
                        parent_fds_before=parent_before['fds'], parent_fds_after=parent_after['fds'])
          samples[count].append(sample)
      for count, rows in samples.items():
        walls = [row['collection']['wall_ns'] for row in rows]
        throughput = [row['collection']['transitions'] * 1e9 / row['collection']['wall_ns'] for row in rows]
        results.append({'players': players, 'cadence': cadence, 'workers': count,
                        'median_wall_ns': statistics.median(walls),
                        'median_transitions_per_second': statistics.median(throughput),
                        'min_transitions_per_second': min(throughput),
                        'max_transitions_per_second': max(throughput), 'samples': rows})
  return {'loaded_module': str(Path(gfootball_engine._gameplayfootball.__file__).resolve()),
          'policy': 'fixed deterministic simple115v2 observation feedback heuristic',
          'steps': steps, 'episode_ids': list(range(episodes)), 'repeats': repeats,
          'resources': 'Linux /proc; sampled RSS sums double-count shared pages; HWM sums are per-process lifetime maxima',
          'timing': 'collection includes resets, IPC, policy/callback copies, resource observations, trajectory/kernel hashing; excludes startup, warmup and close',
          'workloads': results}


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--steps', type=int, default=128)
  parser.add_argument('--episodes', type=int, default=4)
  parser.add_argument('--repeats', type=int, default=3)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  if not 32 <= args.steps <= 1024 or not 4 <= args.episodes <= 64 or not 3 <= args.repeats <= 10:
    parser.error('Use steps=32..1024, episodes=4..64, repeats=3..10')
  if args.output.exists(): parser.error('Use a new output file')
  args.output.write_text(json.dumps(benchmark(args.steps, args.repeats, args.episodes), indent=2) + '\n')


if __name__ == '__main__': main()
