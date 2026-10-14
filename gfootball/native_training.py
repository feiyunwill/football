"""Thin scenario/ownership adapter for the headless C++ training backend.

The four-result interface is consumed by the existing Gymnasium adapter. Only
simple115v2/scoring with single-team control is supported; no silent fallback.
"""
import numpy as np
from gymnasium import spaces

from gfootball.engine_pool import EngineKey
from gfootball.owned_engine import create_owned_engine


class NativeEnvironment:
  def __init__(self, *, env_name, representation='simple115v2', rewards='scoring',
               stacked=False, render=False, number_of_left_players_agent_controls=1,
               number_of_right_players_agent_controls=0, other_config_options=None,
               **unsupported):
    if unsupported:
      raise ValueError('Unsupported native training options: ' + ', '.join(sorted(unsupported)))
    if representation != 'simple115v2' or rewards != 'scoring' or stacked or render:
      raise ValueError('Native training requires headless simple115v2/scoring without stacking')
    left, right = number_of_left_players_agent_controls, number_of_right_players_agent_controls
    if (type(left) is not int or type(right) is not int or
        not 0 <= left <= 11 or not 0 <= right <= 11 or (left == 0) == (right == 0)):
      raise ValueError('Native training must control 1..11 players on one team')
    options = dict(other_config_options or {})
    allowed = {'game_engine_random_seed', 'episode_number', 'reverse_team_processing',
               'physics_steps_per_frame', 'render_resolution_x', 'render_resolution_y',
               'action_set', 'display_game_stats', 'tracesdir', 'real_time'}
    unknown = set(options) - allowed
    if unknown:
      raise ValueError('Unsupported native configuration: ' + ', '.join(sorted(unknown)))
    if options.get('real_time', False):
      raise ValueError('Native training does not support real_time')
    action_set = options.get('action_set', 'default')
    if action_set not in ('default', 'v2'):
      raise ValueError('Native training supports only default and v2 action sets')
    from gfootball.env.config import Config
    import gfootball_engine
    self._native = None
    self._closed = False
    self._count = left + right
    values = dict(options, level=env_name,
                  players=['agent:left_players=%d,right_players=%d' % (left, right)])
    self._config = Config(values)
    self._validate_scenario()
    actions = 20 if action_set == 'v2' else 19
    self.action_space = (spaces.Discrete(actions) if self._count == 1 else
                         spaces.MultiDiscrete([actions] * self._count))
    self.observation_space = spaces.Box(
        -np.inf, np.inf, shape=(115,) if self._count == 1 else (self._count, 115),
        dtype=np.float32)
    key = EngineKey.current(self._config['render_resolution_x'], self._config['render_resolution_y'])
    try:
      self._native = create_owned_engine(key, lambda: gfootball_engine.NativeTrainingEnv(
          key.width, key.height, action_set == 'v2'))
      # Match FootballEnvCore's constructor reset, which does not increment the episode.
      self._config.NewScenario(inc=0)
      self._validate_scenario()
      self._native.reset(self._config.ScenarioConfig(), self._cadence())
    except BaseException as error:
      try:
        self.close(finalize=False)
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Native training construction cleanup also failed.')
      raise

  @property
  def unwrapped(self):
    return self

  def _validate_scenario(self):
    scenario = self._config.ScenarioConfig()
    if scenario.control_all_players or scenario.real_time:
      raise ValueError('Native training does not support control_all_players or real_time scenarios')

  def _cadence(self):
    value = self._config['physics_steps_per_frame']
    if type(value) is not int or not 1 <= value <= 1000:
      raise ValueError('physics_steps_per_frame must be an integer in [1, 1000]')
    return value

  def _check_open(self):
    if self._closed:
      raise RuntimeError('Native training environment is closed')
    self._native._resource()  # Check process/thread ownership before scenario mutation.

  def _observation(self, rows):
    return rows[0] if self._count == 1 else rows

  def reset(self):
    self._check_open()
    self._config.NewScenario()
    self._validate_scenario()
    return self._observation(self._native.reset(self._config.ScenarioConfig(), self._cadence()))

  def step(self, action):
    self._check_open()
    if not self.action_space.contains(action):
      raise ValueError('Action is outside the football action space')
    actions = [int(action)] if self._count == 1 else [int(value) for value in action]
    rows, rewards, terminated, score_reward = self._native.step(actions)
    reward = rewards[0] if self._count == 1 else rewards
    return self._observation(rows), reward, terminated, {'score_reward': score_reward}

  def render(self, mode=None):
    self._check_open()
    return None

  def validate_batch_actions(self, actions):
    self._check_open()
    values = np.asarray(actions)
    if self._count == 1 and values.ndim == 1:
      values = values.reshape(-1, 1)
    if (values.ndim != 2 or values.shape[1] != self._count or
        not 1 <= values.shape[0] <= 256 or values.dtype.kind not in ('i', 'u')):
      raise ValueError('Expected 1..256 integer joint actions with one column per player')
    limit = int(self.action_space.n) if self._count == 1 else int(self.action_space.nvec[0])
    if np.any(values < 0) or np.any(values >= limit):
      raise ValueError('Action is outside the football action space')
    return np.ascontiguousarray(values, dtype=np.int64)

  def step_many(self, actions):
    values = self.validate_batch_actions(actions)
    observations, rewards, terminated, scores = self._native.step_many(values)
    if self._count == 1:
      observations = observations[:, 0, :]
    return observations, rewards, terminated, scores

  def close(self, finalize=True):
    if self._closed:
      return
    # OwnedEngine checks the creating thread and process before native cleanup.
    if self._native is not None:
      self._native.close()
    self._closed = True
