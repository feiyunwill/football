#!/usr/bin/env python3
"""gprofng target: sample actual native stepping, excluding resets and snapshot IO."""
import argparse
import hashlib
import json
import os
import signal
from gfootball.gymnasium import FootballEnv


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--steps', type=int, default=4096)
  parser.add_argument('--players', type=int, default=1)
  parser.add_argument('--cadence', type=int, default=10)
  parser.add_argument('--collector', action='store_true')
  args = parser.parse_args()
  if not 256 <= args.steps <= 16384 or not 1 <= args.players <= 11 or not 1 <= args.cadence <= 1000:
    parser.error('Invalid sampling workload budget')
  env = FootballEnv(backend='native', env_name='11_vs_11_easy_stochastic',
                    number_of_left_players_agent_controls=args.players,
                    other_config_options={'game_engine_random_seed':42, 'render_resolution_x':160,
                                          'render_resolution_y':90, 'physics_steps_per_frame':args.cadence})
  try:
    env.reset(seed=42)
    core = env._env._native
    for _ in range(20): core.step([0] * args.players)
    if args.collector: os.kill(os.getpid(), signal.SIGUSR1)
    resets = 0
    for frame in range(args.steps):
      result = core.step([(frame + player) % 19 for player in range(args.players)])
      if result[2]:
        if args.collector: os.kill(os.getpid(), signal.SIGUSR1)
        env.reset(seed=42)
        resets += 1
        if args.collector: os.kill(os.getpid(), signal.SIGUSR1)
    if args.collector: os.kill(os.getpid(), signal.SIGUSR1)
    print(json.dumps({'steps':args.steps, 'players':args.players, 'cadence':args.cadence, 'resets':resets,
                      'sha256':hashlib.sha256(core.get_state_digest()).hexdigest()}))
  finally:
    env.close()


if __name__ == '__main__': main()
