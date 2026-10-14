"""Compare Python, native scalar and bounded native batch stepping.

Reports medians from rotating measurement order, excluding reset/warmup. Actions
are predetermined; every measured rollout must finish with the same digest.
"""
import argparse
import json
import statistics
import time

import numpy as np

from gfootball.gymnasium import FootballEnv


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--steps', type=int, default=512)
  parser.add_argument('--repeats', type=int, default=3)
  parser.add_argument('--batch-size', type=int, default=32)
  parser.add_argument('--players', type=int, default=1)
  args = parser.parse_args()
  if (not 1 <= args.steps <= 2000 or not 1 <= args.repeats <= 20 or
      not 1 <= args.batch_size <= 256 or not 1 <= args.players <= 11):
    parser.error('steps must be 1..2000, repeats 1..20, batch-size 1..256, players 1..11')
  modes = ('python', 'native', 'native_batch')
  environments = {}
  seconds = {mode: [] for mode in modes}
  reference_digest = None
  # 2026-10-14: expose joint-action workload without changing the single-agent sequence.
  # actions = np.arange(args.steps, dtype=np.int64) % 19
  actions = np.arange(args.steps * args.players, dtype=np.int64).reshape(args.steps, args.players) % 19
  try:
    for mode in modes:
      environments[mode] = FootballEnv(
          backend='python' if mode == 'python' else 'native',
          number_of_left_players_agent_controls=args.players,
          env_name='11_vs_11_easy_stochastic', representation='simple115v2',
          other_config_options=dict(game_engine_random_seed=42, display_game_stats=False,
                                    render_resolution_x=160, render_resolution_y=90))
    for repeat in range(args.repeats):
      order = modes[repeat % 3:] + modes[:repeat % 3]
      for mode in order:
        env = environments[mode]
        env.reset(seed=42)
        for action in range(20):
          env.step(action % 19 if args.players == 1 else
                   np.full(args.players, action % 19, dtype=np.int64))
        start = time.perf_counter()
        if mode == 'native_batch':
          for offset in range(0, args.steps, args.batch_size):
            chunk = actions[offset:offset + args.batch_size]
            result = env.step_many(chunk)
            if len(result[0]) != len(chunk) or result[2].any():
              raise RuntimeError('Benchmark ended before the requested action sequence')
        else:
          for action in actions:
            if env.step(int(action[0]) if args.players == 1 else action)[2]:
              raise RuntimeError('Benchmark ended before the requested action sequence')
        seconds[mode].append(time.perf_counter() - start)
        core = env._env.unwrapped._env._env if mode == 'python' else env._env._native
        digest = core.get_state_digest()
        if reference_digest is None:
          reference_digest = digest
        elif digest != reference_digest:
          raise RuntimeError('Benchmark rollouts diverged')
    results = {mode: dict(seconds=seconds[mode],
                          median_steps_per_second=args.steps / statistics.median(seconds[mode]))
               for mode in modes}
    print(json.dumps(dict(steps=args.steps, repeats=args.repeats, batch_size=args.batch_size,
                          players=args.players,
                          final_digest_equal=True, results=results), indent=2))
  finally:
    for env in environments.values():
      env.close()


if __name__ == '__main__':
  main()
