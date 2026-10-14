#!/usr/bin/env python3
"""One isolated rollout; correctness digest is separate from timed stepping."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import os
import numpy as np
from gfootball.gymnasium import FootballEnv
from gfootball.profile_native_training import policy
import gfootball_engine

parser = argparse.ArgumentParser()
parser.add_argument('--players', type=int, required=True)
parser.add_argument('--cadence', type=int, required=True)
parser.add_argument('--steps', type=int, required=True)
parser.add_argument('--feedback', action='store_true')
parser.add_argument('--verify', action='store_true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
affinity = sorted(os.sched_getaffinity(0))
os.sched_setaffinity(0, {affinity[0]})
env = FootballEnv(backend='native', env_name='11_vs_11_easy_stochastic',
                  number_of_left_players_agent_controls=args.players,
                  other_config_options={'render_resolution_x':160, 'render_resolution_y':90,
                                        'physics_steps_per_frame':args.cadence, 'game_engine_random_seed':42})
try:
  observation = env.reset(seed=42)[0]
  core = env._env._native
  for _ in range(20):
    observation = env.step(0 if args.players == 1 else np.zeros(args.players, dtype=np.int64))[0]
  elapsed = 0
  cpu_elapsed = 0
  trajectory = hashlib.sha256()
  for frame in range(args.steps):
    if args.feedback:
      action = policy(observation)
      joint = [action] if args.players == 1 else action.tolist()
    else:
      joint = [(frame + player) % 19 for player in range(args.players)]
    cpu_start = time.process_time_ns()
    start = time.perf_counter_ns()
    rows, rewards, terminated, score = core.step(joint)
    elapsed += time.perf_counter_ns() - start
    cpu_elapsed += time.process_time_ns() - cpu_start
    observation = rows[0] if args.players == 1 else rows
    if args.verify:
      trajectory.update(rows.tobytes()); trajectory.update(rewards.tobytes())
      trajectory.update(str((terminated, score)).encode())
      trajectory.update(core.get_state_digest())
    if terminated: raise RuntimeError('Comparison rollout ended early')
  args.output.write_text(json.dumps({'elapsed_ns':elapsed, 'cpu_ns':cpu_elapsed, 'cpu_affinity':affinity[0], 'steps':args.steps,
      'final_sha256':hashlib.sha256(core.get_state_digest()).hexdigest(),
      'trajectory_sha256':trajectory.hexdigest() if args.verify else None,
      'loaded_module':str(Path(gfootball_engine._gameplayfootball.__file__).resolve())}) + '\n')
finally:
  env.close()
