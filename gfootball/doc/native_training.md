# Native training backend

The opt-in C++ backend implements headless `simple115`/`simple115v2` observations, joint
discrete actions, scoring/optional checkpoint rewards and scenario termination. Python retains
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
`(steps, players)`. Observations have shape `(completed_steps, features)` or
`(completed_steps, players, features)`, where features is 115 or 460 with stacking.
Mean rewards, terminal flags, truncation flags
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
  team position/direction block in `simple115v2` has 22 values, padded with -1.
  Legacy `simple115` packs the four blocks without gaps, then pads the entire
  88-value prefix with -1. Both layouts share the final 27 values and agree for
  full 11v11 teams. The C++ constructor's optional `fixed_positions` argument
  selects the layout (default true).
- Action sets `default` (19 actions) and `v2` (20, including built-in AI).
- Scoring rewards, scenario score/possession/out-of-play termination and match
  clock termination. Gymnasium's external `TimeLimit` remains a truncation.
- `rewards='scoring,checkpoints'` adds the same per-agent distance checkpoints as
  Python. Only the active player holding the ball collects checkpoints; scoring
  fills each agent's remaining credit. Episode reset clears all collected counts,
  and right-team observations/rewards use its own perspective. Scalar and batch
  transitions apply the same shaping; `info['score_reward']` remains unshaped.
  C++ callers enable the optional fifth constructor argument `checkpoint_rewards`
  (default false); the checkpoint component has ten fixed thresholds and a 0.1
  reward per newly collected checkpoint, matching the Python wrapper defaults.
- `info['agent_rewards']` and `info['score_reward']` retain their Python meanings.
- Engines use the existing admission budget and creating-thread/process ownership.

`stacked=True` enables native four-frame history for either 115 layout. The
observation shape becomes `(460,)` or `(players, 460)`, with oldest to newest
frames concatenated on the last axis. Reset fills all four frames with the new
initial observation. Each returned transition appends exactly one frame, including
the terminal transition; batch returns the corresponding history at every step.
Rewards and checkpoint state are independent of stacking. The flag must be a
Python bool; the default is false. C++ callers use the sixth constructor argument.

C++ `reset` and transitions now return an `ObservationBuffer`, a contiguous
float32 matrix whose `size()` is the row count and `columns()` is 115 or 460.
Indexed rows are spans; batch rows are ordered by step then player. This keeps
unstacked row strides at 115 rather than storing padded 460-value row structs.
History contains at most 4×11×115 floats; output is bounded to 256×11 rows.

Rendering, pixels/SMM, extra
players, recording and `control_all_players` scenarios are
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

C++ callers can save complete training state with `env.get_state()` and restore
with `env.set_state(bytes)`. The target must first reset the same scenario, seed,
cadence and constructor options, using the same engine build and simulation
dataset. The versioned binary snapshot contains the engine, checkpoint counters,
termination history and frame stack. Restore verifies identities before mutation,
and rolls back if decoding or subsequent consistency checks fail. A normally
finished match can restore a live snapshot; restoring a terminal snapshot preserves
the requirement to reset before stepping. New, closed or failed environments
cannot save/restore. The kernel-only `get_state_digest()` is still a diagnostic,
and does not cover the complete training state.

Snapshot export/restore verifies runtime data files against the build manifest;
this work is outside the stepping loop. The format is intended for the supported
Linux little-endian ABI and identical build/resource inputs. The C++ byte API
does not save external Gym wrappers. Format and failure contracts are described in
`.project/native-training/SNAPSHOT.md`.

The raw native `FootballEnv` provides `get_state()/set_state(bytes)` and
`save_state(path)/load_state(path)`. Its Python envelope additionally stores the
Gymnasium PCG64 generator, seed bookkeeping, episode configuration and the
reset-needed flag. The target must reset a compatible scenario before loading:

```python
env.reset(seed=7)
env.step(5)
env.save_state('football-state.bin')
# In another process, create the same native environment and reset(seed=7).
other.reset(seed=7)
other.load_state('football-state.bin')
```

For wrapped environments use the wrapper-aware functions, passing the outer
environment. They preserve TimeLimit elapsed steps, OrderEnforcing flags and
PassiveEnvChecker history, including the first-step observation check:

```python
from gfootball import training_snapshot
training_snapshot.save_state(wrapped_env, 'football-state.bin')
training_snapshot.load_state(other_wrapped_env, 'football-state.bin')
```

The target must have the same wrapper order, TimeLimit configuration and
Gymnasium version. Unknown/custom/vector wrappers reject explicitly. Raw
`env.unwrapped.save_state()` covers only the raw environment. Action-space and
observation-space RNGs, policies, callbacks and external learner state remain
caller-owned. Only the saved environment PCG64 generator is restored.

The FPTR v1 envelope uses bounded JSON metadata and binary native bytes, without
pickle. Metadata is at most 64 KiB; total files are at most 10,098,340 bytes and
paths at most 4096 bytes. Reads reject non-regular files and oversized or corrupt
data. Saving writes a private temporary file in the target directory, flushes
and fsyncs it, then atomically replaces the target and syncs its directory on
POSIX. Failures or process interruption before replacement keep the old target;
errors after replacement may leave the complete new file in place. A killed
writer can leave its private temporary file, which callers can remove after the
writer has exited. No directory is created automatically. These file semantics
are validated on Linux/WSL; other platforms remain part of S5 verification.

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

For optional native phase timing, call the owned native object's
`enable_profiling(True)` after warmup, then `get_profile()` after a rollout.
Enabling or disabling resets the counters; the default is disabled. Counts cover
returned transitions and actual engine calls (including skipped stoppages), with
nanosecond totals for action, engine step, get_info, termination/history, encoding,
reward and NumPy output construction. They are diagnostic values, excluded from
snapshots/digests. Disabled timing does not read the clock but retains flag checks.

`python -m gfootball.profile_native_training --output profiles.json` measures
1/11 players, cadence 2/10, rotating repeated raw/Gym/scalar/batch and observation
feedback workloads. It reports wall time, policy time, phase timing and unclassified
residual separately, and rejects divergent final digests. The feedback heuristic
is not model inference. Raw evidence and the baseline interpretation are in
`.project/native-training/PERFORMANCE.md`; timing-enabled results and normal
throughput are separate, and host scheduling variation must be considered.

For bounded process sampling, use `NativeWorkerPool`. Each spawned process owns
one independent native C++ environment; scenario setup and the process protocol
remain Python orchestration. The existing Python backend remains the default.
Use a guarded entry point, including in scripts started from an IDE:

```python
from gfootball.training_workers import NativeWorkerPool

def main():
    with NativeWorkerPool({'env_name': '11_vs_11_easy_stochastic'},
                          workers=2, base_seed=42) as pool:
        current = pool.reset({0: 0, 1: 1})  # worker index -> global episode ID
        following = pool.step({0: 0, 1: 0})
        print(following[0].reward, following[0].observation.shape)

if __name__ == '__main__':
    main()
```

The pool supports 1..4 workers and the raw native numerical configuration,
including right-team control, checkpoints, stacking and both discrete action
sets. Single-player actions are integers; joint actions are integer lists,
tuples or one-dimensional NumPy arrays. `reset` and `step` accept a nonempty
dictionary selecting any subset of workers and return `WorkerTransition` values
in worker order. Each value contains copied float32 observations and per-agent
rewards, team-mean reward, score reward, terminated/truncated flags and its
episode ID/seed. Truncated is false for this raw environment; external rollout
length limits must retain their own bootstrap semantics. There is no auto-reset.

`episode_seed(base_seed, episode_id)` uses a versioned SHA256 mapping to a uint64
Gym seed, independent of worker assignment/count or completion order. The caller
assigns global episode IDs (and owns uniqueness); resetting the same ID replays
the same episode. The Gym seed still passes through the existing PCG64-to-engine
seed mapping. `digests()` returns SHA256 of each reset worker's canonical kernel
state bytes as a diagnostic, not a complete training checkpoint.

Runtime frames contain at most 32 KiB, with at most 8 KiB JSON metadata plus
little-endian float32 buffers. JSON environment configuration is at most 8 KiB.
Spawn's internal startup uses Python multiprocessing serialization; the runtime
protocol does not send Python objects or pickle snapshots. One synchronous round
has at most one in-flight request/response per selected worker, without an
unbounded task queue. These are per-pool limits, not an operating-system RSS quota.

The pool belongs to its creating process and thread. Invalid actions or episode
IDs reject the entire round before sending any command. A remote exception,
broken/oversized/partial frame, worker exit or deadline failure closes the whole
pool and raises `WorkerError`. Successful transitions on other workers cannot be
rolled back; recreate the pool and explicitly decide what work to replay. Normal
close requests native cleanup; failures terminate, then kill and reap children
within bounded cleanup windows. The default startup deadline is 60 seconds and
the default round deadline is 30 seconds (configurable up to 300 seconds);
cleanup can add up to five seconds. Nonblocking parent framing preserves the
deadline even when a worker stalls partway through a message. Always use a context
manager or `close()`; there is no implicit background retry or restart.

Worker protocol and real-process contracts run with
`python -m unittest gfootball.test_training_workers -v` and are included in the
isolated integration validator. Current process behavior is validated on
Linux/WSL; platform delivery and 1/2/4-worker scaling are separate roadmap tasks.

`collect_episodes` supplies a closed-loop rollout and optional transition stream:

```python
from gfootball.training_sampler import collect_episodes

def decide(observation, context):
    # Read this episode's latest observation; context has episode_id, seed, step.
    return 0

def consume(event):
    # event.observation -> event.actions -> event.following
    # Persist/use the transition in a learner; retained storage is caller-owned.
    pass

# Inside the guarded main() and NativeWorkerPool context above:
# result = collect_episodes(pool, range(8), decide, max_steps=256,
#                           on_transition=consume)
```

The collector accepts 1..1024 unique global episode IDs and 1..4096 steps per
episode. It assigns IDs in input order to free workers, resets explicitly, and
returns summaries in input order. Policies and transition consumers run in the
pool's owner thread. Each decision uses the preceding transition's observation,
or the reset observation at step zero. Inputs and stream arrays are isolated
copies, initially read-only; reusable policy action buffers are detached before
the next decision. Callback exceptions or invalid policy actions close the pool.
Callback execution time itself is outside IPC deadlines and is caller-owned.

The stream includes pre/post observations, joint actions, per-agent/team rewards,
episode/seed/step and terminated/truncated flags. Reaching the collection horizon
sets truncated=true on its final transition; an engine terminal takes precedence
and keeps truncated=false. A learner must bootstrap horizon truncation from the
final observation, without treating it as a match terminal. There is no collector
checkpoint or implicit policy RNG reset; replay requires a fixed policy with
deterministic state per episode/step, independent of worker assignment/order.

Only at most four current episode states and bounded summaries are retained by
the collector. The caller controls storage retained by `on_transition`. Results
include trajectory and final canonical kernel hashes, transition count, total
wall time, policy time, callback time and final kernel hashing time. Total wall
time includes reset, IPC, copying, encoding, validation and hashing.

`python -m gfootball.benchmark_training_workers --output workers.json` runs
rotating 1/2/4-worker workloads for 1/11 players and cadence 2/10. It verifies all
episode trajectories, statuses, rewards and final kernel hashes across counts
and repeats, and checks process/FD cleanup after each pool. Linux /proc reports
parent/worker CPU, sampled RSS and per-process lifetime high-water RSS. RSS sums
double-count shared pages. Startup/warmup/close are outside collection timing;
policy, transition/resource callbacks and hashing are included. This heuristic
is not model inference, and the measurements do not promise a scaling ratio.
