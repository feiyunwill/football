# Native training backend

The opt-in C++ backend implements headless `simple115v2` observations, joint
discrete actions, scoring rewards and scenario termination. Python retains
scenario generation and Gymnasium seed/API handling. The default backend remains
`python`.

```python
from gfootball.gymnasium import FootballEnv

env = FootballEnv(
    backend='native',
    env_name='11_vs_11_easy_stochastic',
    representation='simple115v2',
    rewards='scoring',
)
try:
    observation, info = env.reset(seed=42)
    observation, reward, terminated, truncated, info = env.step(0)
finally:
    env.close()
```

Rebuild the extension from this checkout before selecting the backend. It
requires the `NativeTrainingEnv` binding, so an older installed extension cannot
provide it.

Current supported behavior and the staged expansion contract are recorded in
the [compatibility matrix](../../.project/native-training/COMPATIBILITY.md).

## Predetermined action batches

The raw native `FootballEnv` also offers `step_many(actions)`. One call executes
1–256 predetermined transitions in C++, releases the GIL once, and allocates
training output buffers once for the batch. Use it for offline sampling or
replaying known actions. A policy that selects each action from the preceding
observation should continue to use `step()`.

```python
import numpy as np

env.reset(seed=42)
observations, rewards, terminated, truncated, info = env.step_many(
    np.zeros(32, dtype=np.int64))
```

Single-player input has shape `(steps,)` or `(steps, 1)`. Joint input has shape
`(steps, players)`. Observations have shape `(completed_steps, 115)` or
`(completed_steps, players, 115)`. Mean rewards, terminal flags, truncation flags
and `info['score_reward']` have shape `(completed_steps,)`;
`info['agent_rewards']` has shape `(completed_steps, players)`.

The whole action array is validated before simulation, including any suffix
after a possible terminal step. Invalid shape, dtype, action ID or capacity
preserves the live state. Execution stops at the first terminal step and returns
only the completed prefix, including the final observation. There is no automatic
reset; reset before continuing after termination. Returned arrays retain their
data independently of subsequent steps.

Call this extension on the raw environment. External wrappers such as
`TimeLimit` do not receive individual batch transitions, so their truncation and
other hooks are not applied; batch truncation flags are always false. Use the
standard single-step API when wrapper behavior is required. This batches time
steps within one match; it does not add parallel environment instances.

Supported behavior:

- Control 1–11 players on one team; one player uses `Discrete`, multiple players
  use `MultiDiscrete`. The right team's observation and directional actions are
  rotated to its own perspective.
- Observation shape is `(115,)` or `(players, 115)`, with float32 values. Each
  team position/direction block has 22 values, padded with -1.
- Action sets `default` (19 actions) and `v2` (20, including built-in AI).
- Scoring rewards, scenario score/possession/out-of-play termination and match
  clock termination. Gymnasium's external `TimeLimit` remains a truncation.
- `info['agent_rewards']` and `info['score_reward']` retain their Python meanings.
- Engines use the existing admission budget and creating-thread/process ownership.

Rendering, pixels/SMM/legacy simple115, stacking, checkpoint rewards, extra
players, recording, state save/restore and `control_all_players` scenarios are
outside this backend's first implementation. Unsupported factory/configuration
options raise an error; the backend does not silently switch to Python.

The C++ API is in `engine/src/training/native_training.hpp` and has no Python or
RLtools dependency. `reset` receives a native `ScenarioConfig` and a physics step
count; `step` accepts one action-set index per controlled player. The C++ adapter
owns its engine, validates joint actions before mutation, and serializes access.
Python integrations must additionally preserve process/thread ownership. It
returns one float32 observation and scoring reward per player plus the terminal
flag and the left-minus-right score change. This is separate from the existing
147-feature RLtools example and does not change its policy or checkpoints.

Validation (with an extension built from this checkout):

For isolated build/staging plus full native and existing Gymnasium integration
checks on Linux/WSL, use an interpreter with the project dependencies installed:

```bash
python .project/native-training/validate.py --python /path/to/venv/bin/python \
  --build-root /tmp/football-native-validation --output /tmp/football-native-evidence
```

The build directory can be reused for incremental compilation. The output
directory must be new, so previous evidence is preserved. This checks the staged
extension path, configures bindings ON and OFF, and records logs, source/resource
fingerprints and artifact hashes. It does not perform wheel installation tests.

Individual checks:

```bash
python -m unittest gfootball.test_native_training -v
python -m gfootball.benchmark_native_training --steps 512 --repeats 3 --batch-size 32
cmake -S engine -B /tmp/football-native -DBUILD_PYTHON_BINDINGS=OFF \
  -DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=/tmp/football-native/bin
cmake --build /tmp/football-native --target engine_native_training_contract --parallel 1
GFOOTBALL_DATA_DIR="$PWD/engine/data" /tmp/football-native/bin/engine_native_training_contract
```

The Python tests compare actual native simulation against the existing Python
pipeline, including observations, rewards, termination and state digests. They
also run Gymnasium's checker, deterministic reseeding, ownership and cleanup
checks. No throughput improvement is implied by passing correctness checks.

The benchmark rotates the order of Python, native scalar and native batch modes,
excludes reset and warmup, and checks final state digests. Add `--players 11` for
joint-action workloads. It measures predetermined-action stepping, not policy
inference or end-to-end PPO training.
