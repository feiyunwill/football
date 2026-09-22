"""Four-result environment protocol retained for existing football callers.

Spaces use Gymnasium. These classes deliberately do not inherit Gymnasium.Env:
the legacy reset/step signatures are not the Gymnasium environment contract.
The public Gymnasium adapter lives in gfootball.gymnasium.
"""
from gymnasium import spaces


class Env:
  @property
  def unwrapped(self):
    return self


class Wrapper(Env):
  def __init__(self, env):
    self.env = env

  def __getattr__(self, name):
    if name == 'env' or name.startswith('__'):
      raise AttributeError(name)
    return getattr(self.env, name)

  @property
  def unwrapped(self):
    return self.env.unwrapped

  def reset(self, *args, **kwargs):
    return self.env.reset(*args, **kwargs)

  def step(self, action):
    return self.env.step(action)

  def render(self, *args, **kwargs):
    return self.env.render(*args, **kwargs)

  def close(self, **kwargs):
    return self.env.close(**kwargs)


class ObservationWrapper(Wrapper):
  def reset(self, *args, **kwargs):
    return self.observation(self.env.reset(*args, **kwargs))

  def step(self, action):
    observation, reward, done, info = self.env.step(action)
    return self.observation(observation), reward, done, info


class RewardWrapper(Wrapper):
  def step(self, action):
    observation, reward, done, info = self.env.step(action)
    return observation, self.reward(reward), done, info
