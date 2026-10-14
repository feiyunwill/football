"""Run with installed Python -I, outside the repository, without resource overrides."""
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import numpy as np
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import gfootball
import gfootball_engine as engine
from gfootball.gymnasium import FootballEnv

prefix = Path(sys.prefix).resolve()
for module in (gfootball, engine, engine._gameplayfootball):
  if not Path(module.__file__).resolve().is_relative_to(prefix):
    raise RuntimeError('Loaded a development module instead of the installed wheel')
for name in ('GFOOTBALL_DATA_DIR', 'GFOOTBALL_FONT'):
  if not Path(os.environ[name]).resolve().is_relative_to(prefix):
    raise RuntimeError('Resource escaped the installed wheel')
env = FootballEnv(env_name='11_vs_11_easy_stochastic', representation='simple115v2',
                  rewards='scoring,checkpoints', stacked=True, backend='native',
                  number_of_left_players_agent_controls=2,
                  other_config_options=dict(render_resolution_x=160, render_resolution_y=90,
                                            display_game_stats=False))
try:
  observation, _ = env.reset(seed=42)
  state = env.get_state()
  first = env.step(np.array([1, 5]))
  env.set_state(state)
  second = env.step(np.array([1, 5]))
  np.testing.assert_array_equal(first[0], second[0])
  if first[1:4] != second[1:4]:
    raise RuntimeError('Installed environment restore diverged')
  print(json.dumps(dict(passed=True, python=sys.version, version=importlib.metadata.version('gfootball'),
                       binding=engine._gameplayfootball.__file__, observation_shape=list(observation.shape),
                       data=os.environ['GFOOTBALL_DATA_DIR'], font=os.environ['GFOOTBALL_FONT'])))
finally:
  env.close()
