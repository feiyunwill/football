"""Rotating real-engine sampling profile; predetermined and feedback workloads separate."""
import argparse
import hashlib
import json
import statistics
import time
import numpy as np
from gfootball.gymnasium import FootballEnv


def policy(observation):
  """Small deterministic feedback policy; not PPO/model inference."""
  rows = np.asarray(observation).reshape(-1, 115)
  active = rows[:, 97:108].argmax(axis=1)
  player_x = rows[np.arange(len(rows)), active * 2]
  actions = np.where(rows[:, 88] >= player_x, 5, 1)
  actions = np.where((rows[:, 95] == 1) & (rows[:, 88] > .7), 12, actions).astype(np.int64)
  return int(actions[0]) if len(rows) == 1 else actions


def measure(steps, repeats, players, cadence, batch_size, instrument):
  modes = ('python', 'raw_native', 'native', 'native_batch', 'closed_python', 'closed_native')
  samples = {mode: [] for mode in modes}
  digests = {}
  environments = {}
  actions = np.arange(steps * players, dtype=np.int64).reshape(steps, players) % 19
  try:
    for mode in modes:
      environments[mode] = FootballEnv(
          backend='python' if mode in ('python', 'closed_python') else 'native',
          number_of_left_players_agent_controls=players, env_name='11_vs_11_easy_stochastic',
          representation='simple115v2', other_config_options={
              'render_resolution_x':160, 'render_resolution_y':90, 'physics_steps_per_frame':cadence,
              'game_engine_random_seed':42, 'display_game_stats':False})
    for repeat in range(repeats):
      order = modes[repeat % len(modes):] + modes[:repeat % len(modes)]
      for mode in order:
        env = environments[mode]
        observation = env.reset(seed=42)[0]
        for _ in range(20):
          observation = env.step(0 if players == 1 else np.zeros(players, dtype=np.int64))[0]
        native = None if mode in ('python', 'closed_python') else env._env._native
        if native is not None:
          native.enable_profiling(instrument)
        policy_ns = 0
        start = time.perf_counter_ns()
        if mode == 'native_batch':
          for offset in range(0, steps, batch_size):
            chunk = actions[offset:offset + batch_size]
            result = env.step_many(chunk)
            if len(result[0]) != len(chunk) or result[2].any():
              raise RuntimeError('Profile episode ended early')
        elif mode == 'raw_native':
          for action in actions:
            if native.step(action.tolist())[2]:
              raise RuntimeError('Profile episode ended early')
        else:
          for frame in range(steps):
            if mode.startswith('closed_'):
              tick = time.perf_counter_ns()
              action = policy(observation)
              policy_ns += time.perf_counter_ns() - tick
            else:
              action = int(actions[frame, 0]) if players == 1 else actions[frame]
            row = env.step(action)
            observation = row[0]
            if row[2]:
              raise RuntimeError('Profile episode ended early')
        wall_ns = time.perf_counter_ns() - start
        profile = native.get_profile() if native is not None else None
        if native is not None and instrument and profile['transitions'] != steps:
          raise RuntimeError('Native timing count does not match actual rollout')
        core = native if native is not None else env._env.unwrapped._env._env
        digest = hashlib.sha256(core.get_state_digest()).hexdigest()
        group = 'feedback' if mode.startswith('closed_') else 'predetermined'
        if group in digests and digests[group] != digest:
          raise RuntimeError('Profile rollouts diverged within the same action/feedback workload')
        digests[group] = digest
        samples[mode].append({'wall_ns':wall_ns, 'policy_ns':policy_ns, 'profile':profile})
    result = {}
    for mode, rows in samples.items():
      walls = [row['wall_ns'] for row in rows]
      summary = {'median_ns':statistics.median(walls), 'min_ns':min(walls), 'max_ns':max(walls),
                 'median_steps_per_second':steps * 1e9 / statistics.median(walls), 'samples':rows}
      if rows[0]['profile'] is not None and instrument:
        summary['median_phase_ns'] = {key:statistics.median(row['profile'][key] for row in rows)
                                     for key in rows[0]['profile'] if key.endswith('_ns')}
        summary['unattributed_ns'] = statistics.median(
            row['wall_ns'] - row['policy_ns'] - sum(value for key, value in row['profile'].items() if key.endswith('_ns'))
            for row in rows)
      result[mode] = summary
    return {'players':players, 'cadence':cadence, 'steps':steps, 'repeats':repeats,
            'instrumented':instrument, 'digests':digests, 'results':result}
  finally:
    for env in environments.values():
      env.close()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--steps', type=int, default=256)
  parser.add_argument('--repeats', type=int, default=6)
  parser.add_argument('--batch-size', type=int, default=32)
  parser.add_argument('--output', required=True)
  args = parser.parse_args()
  if not 32 <= args.steps <= 1024 or not 3 <= args.repeats <= 20 or not 1 <= args.batch_size <= 256:
    parser.error('steps=32..1024, repeats=3..20, batch-size=1..256')
  from pathlib import Path
  output = Path(args.output)
  if output.exists(): parser.error('Use a new output file')
  results = []
  for players in (1, 11):
    for cadence in (2, 10):
      # Instrumented versus uninstrumented measurements are independently rotated.
      for instrument in (False, True):
        print(f'profile players={players} cadence={cadence} instrument={instrument}', flush=True)
        results.append(measure(args.steps, args.repeats, players, cadence, args.batch_size, instrument))
  output.write_text(json.dumps({'policy':'deterministic observation feedback heuristic',
                               'batch_size':args.batch_size, 'workloads':results}, indent=2) + '\n')


if __name__ == '__main__': main()
