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

backend='native' selects headless C++ simple115/simple115v2 with scoring. It supports
single-team control and rejects unsupported wrappers/configuration explicitly.

For multiple controlled players on one team, reward is the mean of their
individual rewards, also exposed as info['agent_rewards']. Opposing teams
require separate policies and remain available through the legacy factory.
The football match clock ends the task (terminated); external Gymnasium
TimeLimit wrappers truncate a rollout without redefining the match outcome.
"""
  metadata = {'render_modes': ['human', 'rgb_array'], 'render_fps': 10}

  # 2026-10-14: opt-in C++ training keeps the established Python backend default.
  # def __init__(self, *, render_mode=None, **kwargs):
  def __init__(self, *, render_mode=None, backend='python', **kwargs):
    if backend not in ('python', 'native'):
      raise ValueError('backend must be python or native')
    self._backend = backend
    if backend == 'native':
      kwargs = dict(kwargs)
      kwargs.setdefault('representation', 'simple115v2')
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
    # 2026-10-14: both backends expose the same four-result internal protocol.
    # from gfootball.env import create_environment
    if backend == 'native':
      from gfootball.native_training import NativeEnvironment as create_environment
    else:
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
    self._check_backend_owner()
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
    self._check_backend_owner()
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

  def step_many(self, actions):
    """Execute up to 256 predetermined actions; stop at the first terminal step.

    Returns arrays of observations, mean rewards, terminated, truncated, and
    batched info. Call on the raw native FootballEnv, without external wrappers.
    """
    if self._backend != 'native':
      raise ValueError('step_many requires backend=native')
    if self._closed or self._needs_reset:
      raise gym.error.ResetNeeded('Reset before stepping a new or finished match')
    # Invalid batches preserve the live environment, including an invalid suffix.
    values = self._env.validate_batch_actions(actions)
    try:
      observations, agent_rewards, terminated, scores = self._env.step_many(values)
      self._needs_reset = bool(terminated[-1])
      return (observations, agent_rewards.mean(axis=1), terminated,
              np.zeros(terminated.shape, dtype=bool),
              {'agent_rewards': agent_rewards, 'score_reward': scores})
    except BaseException as error:
      self._abort(error)
      raise

  def render(self):
    # 2026-09-10: the final match image remains renderable until close/reset.
    # if self._closed or self._needs_reset:
    if self._closed or not self._has_reset:
      raise gym.error.ResetNeeded('Reset before rendering a football environment')
    self._check_backend_owner()
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
    self._check_backend_owner()
    self._closed = True
    self._needs_reset = True
    if self._env is not None:
      self._env.close()

  def _check_backend_owner(self):
    # 2026-10-14: reject wrong-thread/fork calls before RNG, config or lifetime changes.
    if self._backend == 'native' and self._env is not None:
      self._env._check_open()

  def _check_snapshot(self):
    if self._backend != 'native':
      raise ValueError('Training snapshots require backend=native')
    self._check_backend_owner()
    if self._closed or not self._has_reset:
      raise gym.error.ResetNeeded('Reset before saving/restoring training state')

  def get_state(self):
    """Snapshot the raw native Gym environment, including PCG64 RNG and episode state."""
    self._check_snapshot()
    from gfootball import training_snapshot as snapshot
    if type(self.np_random.bit_generator) is not np.random.PCG64:
      raise ValueError('Training snapshots support the Gymnasium PCG64 generator')
    if self._reverse_processing is not None and type(self._reverse_processing) is not bool:
      raise ValueError('Snapshots require a boolean or default reverse processing policy')
    return snapshot.encode({
        'kind': 'native-gym-v1', 'config': self._env.snapshot_config(),
        'needs_reset': self._needs_reset, 'rng': self.np_random.bit_generator.state,
        'rng_seed': self.np_random_seed, 'reverse_processing': self._reverse_processing},
        self._env.get_state())

  def set_state(self, state):
    self._check_snapshot()
    from gfootball import training_snapshot as snapshot
    import struct
    import zlib
    metadata, native = snapshot.decode(state)
    if set(metadata) != {'kind', 'config', 'needs_reset', 'rng', 'rng_seed', 'reverse_processing'}:
      raise ValueError('Invalid Gym snapshot metadata fields')
    if metadata['kind'] != 'native-gym-v1' or type(metadata['needs_reset']) is not bool:
      raise ValueError('Invalid Gym snapshot lifecycle')
    if (type(metadata['reverse_processing']) is not type(self._reverse_processing) or
        metadata['reverse_processing'] != self._reverse_processing):
      raise ValueError('Snapshot reverse processing policy differs')
    if type(metadata['rng_seed']) is not int or not -1 <= metadata['rng_seed'] < (1 << 256):
      raise ValueError('Invalid Gym RNG seed metadata')
    # Validate the native lifecycle before any Python or kernel mutation.
    magic, version, length, checksum = struct.unpack_from('<4sIII', native)
    if magic != b'FTRN' or version != 1 or len(native) != 16 + length or zlib.crc32(native[16:]) != checksum or length < 4:
      raise ValueError('Invalid nested native snapshot envelope')
    flags = struct.unpack_from('<I', native, 16)[0]
    if flags & ~31 or metadata['needs_reset'] != (not bool(flags & 16)):
      raise ValueError('Gym lifecycle disagrees with native snapshot')
    values, scenario_values = self._env.prepare_snapshot_config(metadata['config'])
    try:
      generator = np.random.PCG64()
      encoded_rng = metadata['rng']
      if (type(encoded_rng) is not dict or set(encoded_rng) != {'bit_generator', 'state', 'has_uint32', 'uinteger'} or
          encoded_rng['bit_generator'] != 'PCG64' or type(encoded_rng['state']) is not dict or
          set(encoded_rng['state']) != {'state', 'inc'}):
        raise ValueError('Invalid PCG64 state')
      for key in ('state', 'inc'):
        value = encoded_rng['state'][key]
        if type(value) is not int or not 0 <= value < (1 << 128):
          raise ValueError('Invalid PCG64 integer state')
      if not encoded_rng['state']['inc'] & 1:
        raise ValueError('Invalid PCG64 increment')
      if (type(encoded_rng['has_uint32']) is not int or encoded_rng['has_uint32'] not in (0, 1) or
          type(encoded_rng['uinteger']) is not int or not 0 <= encoded_rng['uinteger'] < (1 << 32)):
        raise ValueError('Invalid PCG64 cached sample')
      generator.state = encoded_rng
      rng = np.random.Generator(generator)
    except (TypeError, KeyError, OverflowError) as error:
      raise ValueError('Invalid Gym RNG metadata') from error
    self._env.set_state(native)
    # All prepared values are owned references; no output transform after mutation.
    self._env._config._values = values
    self._env._config._scenario_values = scenario_values
    self._np_random = rng
    self._np_random_seed = metadata['rng_seed']
    self._needs_reset = metadata['needs_reset']

  def save_state(self, path):
    self._check_snapshot()
    from gfootball import training_snapshot as snapshot
    snapshot.save(path, self.get_state())

  def load_state(self, path):
    self._check_snapshot()
    from gfootball import training_snapshot as snapshot
    self.set_state(snapshot.load(path))
