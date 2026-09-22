# Gymnasium environment

The current checkout uses Gymnasium 1.3+ and declares Python 3.10+. Install the
checkout with `python -m pip install .` after the native build prerequisites.
pygame-ce supplies the `pygame` import; do not install both pygame distributions
into the same environment.

```python
import gymnasium as gym

with gym.make(
    'gfootball.gymnasium:GFootball-11_vs_11_easy_stochastic-SMM-v0',
    max_episode_steps=1000,
) as env:
    observation, info = env.reset(seed=42)
    while True:
        observation, reward, terminated, truncated, info = env.step(
            env.action_space.sample())
        if terminated or truncated:
            break
```

The explicit `gfootball.gymnasium:` module prefix works even when a storage
module imported the root `gfootball` package first. Alternatively, import
`gfootball.gymnasium` once and use the registered ID without a module prefix.
Storage/network imports remain independent of Gymnasium, NumPy and the native
engine. Importing the Gymnasium entry module registers IDs without loading the
football environment or native library.

`reset(seed=...)` returns `(observation, info)`. Repeating a seed resets the
episode sequence and native random seed; unseeded resets advance the
environment's own generator. The built-in scenario path does not reseed or
consume the caller's global Python/NumPy generators. Per-reset `options` must
be absent or empty; configure the scenario at construction.

`step(action)` returns `(observation, reward, terminated, truncated, info)`.
The football match clock and scenario completion rules terminate the task.
Gymnasium's external `max_episode_steps` / TimeLimit truncates a rollout.
Reset after either condition before starting another episode. Invalid actions
are rejected before advancing the engine. Closing is idempotent; a closed
environment cannot be reset.

Registered representations are `SMM`, `Pixels`, `simple115` and `simple115v2`.
Stacking, checkpoint rewards and one or multiple controlled players on the
same team are supported. One Gymnasium policy controls 1–11 players on either
the left or the right team. Its joint-action reward is the mean of the
controlled players' rewards; `info['agent_rewards']` preserves the individual
rewards as a fresh array. Pixel observations retain the underlying football
restriction to left-team control. Raw observations and simultaneous control
of opposing teams remain available through the legacy factory below.

Select `render_mode='human'` or `'rgb_array'` when constructing the Gymnasium
environment. Human rendering returns `None`; RGB rendering returns an RGB
uint8 image. Pixel representations enable the renderer even without a render
mode. The final image remains available after native match termination and
before close. Rendering uses the actual SDL/EGL backend. `render=True` belongs
to the legacy API and is rejected by the Gymnasium entry point.

`gymnasium.vector.SyncVectorEnv` can own independent football environments.
Gymnasium remains responsible for vector rollout/autoreset behavior. Each
underlying football environment retains the existing owner and engine-pool
resource rules.

For existing replay and actor integrations:

```python
from gfootball.env import create_environment

env = create_environment(env_name='11_vs_11_easy_stochastic')
try:
    observation = env.reset()
    observation, reward, done, info = env.step(env.action_space.sample())
finally:
    env.close()
```

This factory retains its four-result protocol and wrapper snapshot support. It
uses Gymnasium spaces but does not pretend to implement Gymnasium.Env. Old
`import gym` / Gym plugin registration is retired from this checkout. Legacy
TensorFlow/OpenAI Baselines integrations require their own migration and
training acceptance; installing the environment does not validate those stacks.
