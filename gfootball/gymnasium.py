"""Gymnasium entry point: gym.make('gfootball.gymnasium:GFootball-...').

Importing this module registers IDs without loading the native engine. The
existing gfootball.env.create_environment factory retains its four-result API.
"""
import gymnasium as gym
import numpy as np

from gfootball import register_gymnasium_envs

register_gymnasium_envs()


class FootballEnv(gym.Env):
  """Joint-action football environment with a scalar team reward.

For multiple controlled players on one team, reward is the mean of their
individual rewards, also exposed as info['agent_rewards']. Opposing teams
require separate policies and remain available through the legacy factory.
The football match clock ends the task (terminated); external Gymnasium
TimeLimit wrappers truncate a rollout without redefining the match outcome.
"""
  metadata = {'render_modes': ['human', 'rgb_array'], 'render_fps': 10}

  def __init__(self, *, render_mode=None, **kwargs):
    if render_mode not in (None, 'human', 'rgb_array'):
      raise ValueError('render_mode must be None, human or rgb_array')
    representation = kwargs.get('representation', 'extracted')
    if representation not in ('extracted', 'simple115', 'simple115v2',
                              'pixels', 'pixels_gray'):
      raise ValueError('Gymnasium requires a numeric observation representation')
    left = kwargs.get('number_of_left_players_agent_controls', 1)
    right = kwargs.get('number_of_right_players_agent_controls', 0)
    if (type(left) is not int or type(right) is not int or
        not 0 <= left <= 11 or not 0 <= right <= 11 or
        (left == 0) == (right == 0)):
      raise ValueError('A Gymnasium policy must control 1..11 players on one team')
    if 'render' in kwargs:
      raise ValueError('Use render_mode when creating a Gymnasium environment')
    if representation.startswith('pixels') and right:
      raise ValueError('Pixel observations require left-team control')
    options = dict(kwargs.get('other_config_options') or {})
    self._reverse_processing = options.get('reverse_team_processing')
    self.render_mode = render_mode
    self._env = None
    self._closed = False
    self._needs_reset = True
    self._has_reset = False
    # 2026-09-10: construction must use the environment RNG as well as reset;
    # otherwise scenario discovery consumes the caller's global random stream.
    if 'game_engine_random_seed' not in options:
      options['game_engine_random_seed'] = int(self.np_random.integers(0, 2000000001))
    kwargs = dict(kwargs, other_config_options=options)
    from gfootball.env import create_environment
    try:
      self._env = create_environment(
          render=render_mode is not None or representation.startswith('pixels'),
          **kwargs)
      self.action_space = self._env.action_space
      self.observation_space = self._env.observation_space
      cadence = self._env.unwrapped._config['physics_steps_per_frame']
      self.metadata = dict(type(self).metadata, render_fps=100 / cadence)
      if not isinstance(self.observation_space, gym.spaces.Box):
        raise TypeError('Football Gymnasium observations must have a Box space')
    # 2026-09-10: preserve the initiating error if cleanup also fails.
    # except BaseException:
    #   if self._env is not None:
    #     self._env.close(finalize=False)
    except BaseException as error:
      self._abort(error)
      raise

  def _abort(self, error):
    self._closed = True
    self._needs_reset = True
    if self._env is not None:
      try:
        self._env.close(finalize=False)
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Football Gymnasium cleanup also failed.')

  def reset(self, *, seed=None, options=None):
    if self._closed:
      raise RuntimeError('Cannot reset a closed football environment')
    if options is not None and (type(options) is not dict or options):
      raise ValueError('No per-reset options are supported; configure at creation')
    if seed is not None and (type(seed) is not int or seed < 0):
      raise ValueError('seed must be a nonnegative Python integer or None')
    super().reset(seed=seed)
    engine_seed = int(self.np_random.integers(0, 2000000001))
    values = {'game_engine_random_seed': engine_seed}
    if seed is not None:
      values['episode_number'] = 0
    values['reverse_team_processing'] = (
        bool(engine_seed % 2) if self._reverse_processing is None
        else self._reverse_processing)
    self._env.unwrapped._config.update(values)
    self._needs_reset = True
    # 2026-09-10: a partial reset must not leave a leased engine behind.
    # observation = self._env.reset()
    # self._needs_reset = False
    # if self.render_mode == 'human':
    #   self._env.render('human')
    try:
      observation = self._env.reset()
      if self.render_mode == 'human':
        self._env.render('human')
    except BaseException as error:
      self._abort(error)
      raise
    self._needs_reset = False
    self._has_reset = True
    return observation, {}

  def step(self, action):
    if self._closed or self._needs_reset:
      raise gym.error.ResetNeeded('Reset before stepping a new or finished match')
    if not self.action_space.contains(action):
      raise ValueError('Action is outside the football action space')
    # 2026-09-10: abort a failed transition or output transform atomically.
    # observation, reward, done, info = self._env.step(action)
    # self._needs_reset = bool(done)
    # rewards = np.asarray(reward, dtype=np.float32)
    # info = dict(info)
    # info['agent_rewards'] = rewards.reshape(-1).copy()
    # if self.render_mode == 'human':
    #   self._env.render('human')
    # return observation, float(rewards.mean()), bool(done), False, info
    try:
      observation, reward, done, info = self._env.step(action)
      self._needs_reset = bool(done)
      rewards = np.asarray(reward, dtype=np.float32)
      info = dict(info)
      info['agent_rewards'] = rewards.reshape(-1).copy()
      if self.render_mode == 'human':
        self._env.render('human')
      return observation, float(rewards.mean()), bool(done), False, info
    except BaseException as error:
      self._abort(error)
      raise

  def render(self):
    # 2026-09-10: the final match image remains renderable until close/reset.
    # if self._closed or self._needs_reset:
    if self._closed or not self._has_reset:
      raise gym.error.ResetNeeded('Reset before rendering a football environment')
    if self.render_mode is None:
      return None
    # 2026-09-10: human rendering returns None under the Gymnasium contract.
    # return self._env.render(self.render_mode)
    try:
      result = self._env.render(self.render_mode)
      return result if self.render_mode == 'rgb_array' else None
    except BaseException as error:
      self._abort(error)
      raise

  def close(self):
    if self._closed:
      return
    self._closed = True
    self._needs_reset = True
    if self._env is not None:
      self._env.close()
