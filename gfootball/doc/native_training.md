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

The standalone C++ categorical inference API lives in
`engine/src/training/categorical_policy.hpp` and `native_policy.hpp`. It is
separate from the Python bindings and the legacy 147-feature Gaussian RLtools
trainer. Build its contracts and inference-only example without Python:

```bash
cmake -S engine -B /tmp/football-policy -DBUILD_PYTHON_BINDINGS=OFF \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=23 \
  -DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=/tmp/football-policy/bin
cmake --build /tmp/football-policy --target categorical_policy_contract \
  engine_native_policy_contract native_policy_rollout --parallel 1
GFOOTBALL_DATA_DIR="$PWD/engine/data" \
  /tmp/football-policy/bin/native_policy_rollout 42 11 128
```

`PolicySpec` fixes 1..11 players, 115/460 features, simple115 versus simple115v2,
default/v2 actions and 1..64 tanh hidden units. A flattened joint observation feeds
per-player categorical logits and one team value head. Parameters and arithmetic
are float64; observations remain float32. The max-shifted categorical distribution
uses native action indices, joint log-prob and entropy summed over players,
inverse-CDF sampling or deterministic argmax. Argmax breaks ties toward the first
index and does not advance the sampling RNG. No continuous action clipping or
nearest-player remapping is applied. Model/observation dimensions and finite
values are checked before sampling/engine mutation.

`NativePolicyEnvironment` owns one matching `NativeTrainingEnv`. Call `reset` with
a native `ScenarioConfig` and cadence, then `step(policy, rng, deterministic,
horizon)`. A step returns copied pre/post observations, the decision/actions,
native per-agent rewards, score reward, terminal flag and optional horizon
truncation. The scalar team reward is a float64 mean of native float32 rewards;
Gym's float32 mean can differ by rounding. The creating process/thread owns the
adapter. Failed inference or identity validation preserves the live engine and
RNG; an engine/output failure closes the adapter. Terminal or horizon truncation
requires an explicit reset; terminal takes precedence. Sampling RNG commits only
after a successful environment step. The current observation accessor is borrowed
and valid until the next reset/step; copy it to retain a training sample.

The versioned `PolicyRng` is SplitMix64 with a fixed 53-bit uniform mapping, with
explicit state get/set. Policy initialization has its own local seeded stream;
sampling is caller-owned. The example accepts `[seed] [players] [steps]`, controls
the left team in `frame_sync::MakeDefaultScenario`, uses cadence10 and native
engine seed `seed % 2000000001`. This native seed protocol is distinct from Gym's
PCG64 seed conversion and arbitrary Python scenario discovery. The example reports
`categorical_inference_only`; it performs no PPO updates or learner checkpointing.
Those remain NT-4.3/4.4 tasks.

The math contract checks probabilities/log-prob/entropy, shift invariance, seeded
sample frequencies, RNG replay, finite/shape failures and maximum model dimensions;
the isolated validator also checks its MLP and categorical output against NumPy.
The engine contract compares 32 single/multi-player, left/right, action-set,
layout and stacking combinations against direct C++ native transitions and kernel
states. A separate sanitizer validator covers the standalone policy math, with
ASan/UBSan/LSan; it does not claim full-engine sanitizer coverage.

`engine/src/training/ppo_math.hpp` and `ppo_learner.hpp` add the native categorical
PPO update and full learner checkpoint. `PpoLearner` owns a matching policy, Adam,
sampling/shuffle/episode RNGs and one native environment. It takes a detached
native `ScenarioConfig`, policy shape, PPO hyperparameters, root seed, cadence,
episode horizon and checkpoint-reward setting. A collection/update contains
1..256 joint transitions. Each rollout is collected under one frozen policy;
old values/log-probs are verified against that policy before the first update.

GAE bootstraps a live or horizon-truncated step from its final observation value,
uses zero bootstrap for a match terminal, and cuts recursion at either episode
boundary. Returns use unnormalized advantages; optional advantage normalization
uses the rollout population standard deviation plus 1e-8. The combined objective
is clipped joint categorical PPO, half-squared value error with value coefficient,
and summed categorical entropy. Adam uses bias correction and explicit epsilon;
minibatch gradients are averaged and globally norm-clipped. Epochs are bounded
to 1..16 and minibatches to 1..256. A full update prepares model, optimizer and
shuffle RNG on copies and commits together. If an iteration fails after sampling,
the learner closes its progressed environment and requires a checkpoint restore;
it does not silently retry already executed actions.

For C++ callers, link the `football_ppo_learner` CMake target:

```cpp
PpoLearnerConfig config;
config.scenario = frame_sync::MakeDefaultScenario(1, 0, 42);
config.seed = 42;
PpoLearner learner(config);
auto metrics = learner.train(128);  // actual Adam/PPO parameter updates
learner.save("/tmp/football-learner.bin");
// Create another learner with exactly the same config, then:
other.load("/tmp/football-learner.bin");
```

The `FPPO` v1 file is distinct from legacy RLtools TAR and environment-only
FTRN/FPTR. Its little-endian payload has an exact length and SHA256 checksum,
algorithm/policy/RNG versions, model/layout/action dimensions, all hyperparameters,
parameters, Adam first/second moments and step, all live RNG states, policy and
transition counters, base/current scenario identities, episode ID/step/return,
and the complete native FTRN state plus current float32 observation and lifecycle.
It is bounded to 32 MiB; internal model sizes, blobs and counters are validated
before allocation/use. The checksum detects corruption, not authenticity.

Saving/loading is supported at complete update boundaries (including the initial
zero-update boundary), when no pending rollout is retained. Mid-rollout recovery
is not represented by this format. Restore requires the same config/root seed,
engine build/resources and ABI. It prepares a separate engine, resets the saved
current scenario/seed, restores its full FTRN state and verifies the duplicated
observation against the restored engine. Only then are the learner, optimizer,
RNGs and environment committed together. Any validation or staging failure leaves
the original target unchanged; a failed staging `NativePolicyEnvironment.restore`
closes that staging adapter. `NativeTrainingEnv.current_observation()` returns a
copy without advancing physics or appending another stacked frame.

Checkpoint file I/O reuses the bounded native atomic-file helper: same-directory
temporary, flush/fsync and atomic replacement; nonregular/symlink reads reject.
Failures before publication retain the old target; failures after publication
can leave the complete new checkpoint in place. Checkpoint file support is
currently validated on Linux/POSIX. Borrowed policy/optimizer views must not be
retained across train/restore; configuration access returns a detached scenario.
The learner belongs to its creating process/thread.

The standalone `ppo_math_contract` and NumPy reference verify full MLP/loss
gradients by finite differences, both advantage signs and clipping branches,
terminal/truncated/live GAE, population normalization, Adam's first two steps,
and update failure atomicity/replay. `engine_ppo_checkpoint_contract` performs
real parameter updates and compares resumed trajectories and complete state
bytes, with shape/checksum/lifecycle/observation and file failure tests. They are
included in isolated native validation and the expanded full-engine sanitizer
entry point. Multi-seed training/evaluation and frozen evaluation isolation
remain NT-4.4; passing these contracts does not demonstrate learned football skill.

The `native_ppo_train` executable provides real training, frozen evaluation and
checkpoint resume without Python:

```bash
cmake --build /tmp/football-policy --target native_ppo_train --parallel 1
GFOOTBALL_DATA_DIR="$PWD/engine/data" \
GFOOTBALL_FONT="$PWD/engine/fonts/AlegreyaSansSC-ExtraBold.ttf" \
  /tmp/football-policy/bin/native_ppo_train --scenario empty_goal --seed 42 \
  --updates 6 --rollout 128 --hidden 16 --epochs 4 --minibatch 32 \
  --episode-limit 128 --eval-seed 12345 --eval-episodes 3 --eval-steps 96 \
  --save /tmp/football-trained.bin
```

Use `--help` for bounded numeric options and `--right`, `--v2`, `--compact`,
`--stacked`, `--checkpoints`. The two builtin scenarios are deterministic native
templates: `empty_goal` is a sparse two-left/one-right roster with ball x=.77,
duration400 and score/out-of-play/possession-change endings; `11v11` uses the
project's native default formation and duration3000. They are not an interpreter
for Python scenario files; the sparse template intentionally uses deterministic
native physics and explicitly controllable players. Training changes only the
engine seed per episode, preserving other scenario settings.

`--updates N` means N additional complete updates, including after `--load`.
Load requires the same root seed, scenario, shape, horizon, cadence, reward and
optimizer config. `--updates 0 --load FILE` evaluates frozen restored weights.
`--no-initial-eval` skips the pre-training/pre-resume comparison. An evaluation
count of zero disables episode sampling; `--save` runs after isolation checks.
JSON stdout contains actual update metrics/trajectory hashes, version/counts,
initial/final evaluations, full-state hashes and elapsed time.

`EvaluatePpo` evaluates sampled model actions, argmax model actions, uniformly
random configured actions, and native built-in-AI action19. It uses separate raw
environments and RNGs, with the same explicit engine seeds for all strategies.
The raw evaluation environments admit K=20 solely to allow the built-in-AI
baseline; model/random use their trained/configured K. Full learner state bytes
before/after evaluation must match, covering weights, moments, RNGs and the live
training environment. Evaluated horizon endings remain truncated, and reported
controlled score delta is a goal difference, not a match win-rate. Reward includes
checkpoint shaping only if the training config enables it.

The multi-seed experiment validator records full six-update runs, three-update
prefixes, resumed suffixes in new processes, and evaluation-only restored runs.
It compares exact iterations/trajectories, final checkpoint bytes and frozen
evaluations across processes. Short reproducible updates and these baselines do
not establish convergence or general football skill; report per-seed results and
the workload limits alongside any training claim.

## Reproduction, delivery and rollback

The staged delivery workflow is documented in
`.project/native-training/DELIVERY.md`; it builds a clean committed-source wheel,
installs it in a new environment, and validates a relocated Linux native package.
For a one-command training/resume/evaluation check with that package, run:

```sh
python .project/native-training/reproduce_training.py \
  --program /tmp/football-native-package/native_ppo_train \
  --output /tmp/football-native-reproduction
```

This short functional run checks actual parameter updates, full/resumed checkpoint
bytes and frozen evaluation. It does not demonstrate football skill. See
`.project/native-training/MIGRATION.md` for configuration matching, opt-in Gym
examples and rollback, `COMPATIBILITY.md` for backend behavior, `PLATFORMS.md` for
verified Python/platform/ABI limits, and `QUALITY.md` for continuous acceptance.
Existing Gym defaults remain `backend='python'`; switching back requires a new
environment/episode. FPPO, native environment snapshots and legacy RLtools models
have distinct formats and cannot be interchanged.

## Native engine performance evidence

The headless engine reuses completed Node/Geometry subtree invalidation until a
transform/AABB read or hierarchy change revokes it. Rendering, active tracker
verification and custom dynamic types retain the original update path. No new
runtime option or snapshot field is required; rebuild the native artifacts to use
the source change.

The 2026-10-17 local acceptance measured a 20.54% median CPU cost reduction for
11-player/cadence-2 predetermined engine stepping. All eight workload regression
gates and trajectory checks passed, as did exact 128-update four-worker learner
and replay comparison. This particular measurement covers engine stepping. See the
[measurement report](../../.project/optimization/spatial-invalidation-report-20261017.md)
and current [quality receipt](../../.project/native-training/evidence/spatial-candidate-quality-20261017-b/report.json).


The subsequent [PPO pipeline acceptance](../../.project/optimization/ppo-pipeline-report-20261017.md)
uses eight alternating pairs of 64 real updates per comparison, the production
Python pool/collector and a diagnostic bridge to production C++ PPO math. Primary
four/one-worker throughput is 2.2102x (95% interval 2.1633-2.2586). Primary retained/
archived-engine pipeline throughput is 1.0902x (1.00045-1.10983); the lower bound
is close to one. All four configuration median cost gates passed; the
11-player/cadence-10 interval includes regression. These loop timings include
PPO diagnostics and in-loop saves, and exclude startup/warmup/final save/close.
They do not establish shipped native CLI or general hardware speedups.

Current-source training also completed 1800 seconds, 7265 updates and 1859840 joint
transitions, with fresh-process learner checkpoint load, parent FD 5-to-5 and all
workers reaped. A separate project's compilation overlapped this run: its 1033.23
transitions/s is a resource/duration observation under contention, not an isolated
sustained-throughput or learning proof. Current-source wheel delivery and the
multi-seed held-out learning roadmap remain open. Full receipts are linked in the
report and its [completion audit](../../.project/native-training/evidence/pipeline-completion-audit-20261017-b/report.json).

## Varied-start shooting tasks

The native CLI also accepts `--scenario varied_empty_goal` and
`--scenario varied_keeper`. Both control one left-side outfield player and sample
12 training starts from a fixed grid. The empty task parks a lazy goalkeeper
outside the shooting area; the keeper task uses the normal engine AI goalkeeper.
These are bounded shooting tasks, not full 11v11 training.

```sh
./native_ppo_train --scenario varied_empty_goal --seed 42 --hidden 64 \
  --cadence 10 --episode-limit 256 --rollout 256 --epochs 4 --minibatch 64 \
  --updates 780 --no-initial-eval --eval-episodes 0 \
  --save varied-empty-seed42.fppo
```

Use `--eval-partition validation` for configuration selection. The current
registered study uses `--eval-partition confirmation` with fresh geometries and
seeds; `test` retains the earlier exploratory partition. Default evaluation uses
`train`. All four fixed geometry sets are disjoint. Episode JSON includes engine seed,
start index and normalized ball start coordinates, so paired evaluation can be
checked. With the same scenario/seed/policy/PPO configuration, load the model with
`--updates 0 --no-initial-eval --eval-partition confirmation --eval-seed 700001
--eval-episodes 50 --eval-steps 256` for frozen evaluation.

Variable-task FPPO payloads identify their scenario variation explicitly and
restore the sampled current scene and episode RNG. Loading into a different task
or configuration is rejected; this is not an implicit fine-tuning/weight-transfer
interface. Fixed-task payload encoding remains unchanged. All checkpoints still
require the same source/build/ABI and runtime resources.

The [registered five-seed study and final-source delivery target](../../.project/optimization/generalization-plan-20261018.md)
defines the learning gates. Protocol execution alone does not establish learning;
use its separate learning decision and audit receipts.

The confirmation study evaluates the trained categorical sampling policy as its
primary deployment mode. Argmax outcomes remain reported separately. An earlier
greedy-policy trial failed one training seed and is retained as rejected evidence;
its results do not establish performance for the sampled-policy confirmation run.
# 2v1 配合进攻任务

`native_ppo_train --scenario 2v1` 使用一个固定可控前锋、一个引擎 AI 队友，
对抗一个引擎 AI 后卫及门将；双方另有必要的门将阵容，因此“2v1”不包含门将。
仅支持一个左侧学习球员，禁止切换到 AI 队友；`--right`、`--players 2` 和 `--v2` 被拒绝。
底层固定两个控制槽（球员 1/2），第二槽始终执行内置 AI 动作 19。学习球员只输出
0–18 动作，策略观测、概率及 PPO 损失只包含第一槽；第二槽完整保留在原生快照内。
普通未绑定控制器的 AI 队友在人工队伍里不会执行持球进攻，不能用它代替该固定 AI 槽。
七个 `--eval-partition` 各有 12 个有限起点。当前 2v1 独立确认使用 `holdout`
（索引6，偏移 .075）；`confirmation`、`replication`、`prospective` 保留已拒绝试验的数据，不用于新一轮确认。

评估 JSON 增加 `pass_requests`、`completed_passes`、`teammate_transfers` 和
`turnovers`。它们是决策边界观测：只有持球的可控球员请求动作 9–11 后，
30 次决策内由前场 AI 队友（索引 2）持球、期间未被对方控球，才计为一次完成传球；
传给己方门将不计入完成传球。
射门或超时取消待完成请求。动作请求不等于实际触球；cadence 内的短暂触球可能未被观测。
这些指标用于识别配合行为，不能用单独的进球率代替配合验收。

本任务的学习效果与安装交付仍需独立验收；此前单人射门任务的结果不适用于 2v1。
当前验证协议为每个模型 2048 次更新，每次 256 个转移；CLI 接受 `--updates 0..2048`。

2v1 的 PPO 训练始终保留真实进球和检查点奖励，首次传给前场 AI 队友另奖励 2，
每回合至多一次。策略可显式看到本回合是否已经完成前场传球的历史标志：
观测到该传球后实际进球时，再按真实正向 `score_reward` 额外奖励 2 倍；
检查点本身不触发这项进球奖励，丢球及未配合进球的原始奖励保持不变。
2v1 专用策略视图把未使用的左队第 11 人 y 坐标填充槽（索引 21）设为 -1/+1。
标志完全由过去的持球观测计算；训练、bootstrap 和冻结评估使用同一变换。
该策略视图还在空闲槽28–37提供第一槽的8个持续方向位、冲刺和盘带位，取自原生
控制器当前状态，避免把仍保持的按键当成已释放；输入维度不变，恢复时从原生状态重建。
原生 simple115 输出及快照仍保持原始填充值，其他任务不使用该视图。
训练和评估均为完整任务，没有奖励门控、课程混合或伪造的完成传球计数。
评估继续报告原始进球和传球指标，不把训练奖励当作进球率。
FPPO 内层 schema3 保存待完成传球、持球者、计数及时间窗口，恢复时校验原生持球状态，
禁止用旧 schema2 的 2v1 状态恢复新奖励任务；单人变起点任务仍使用 schema2。

## 2v1 独立推理与恢复

正式 `native_ppo_train` 提供 `--inference-mode balanced|argmax|sample|uniform_random|builtin_ai`。
此入口只做固定 simple115、19 动作的 2v1 推理，拒绝训练参数。balanced 为确定性概率额度
分配控制器，每回合重置；原有 argmax、采样和默认训练评估行为保持原定义。

先在与 FPPO 快照兼容的构建中使用 `--scenario 2v1 ... --load MODEL.fppo --updates 0
--eval-episodes 0 --export-policy POLICY.fpol` 导出策略。FPOL1 只含版本化策略权重、任务视图
和原模型 SHA256；不包含优化器或训练环境，不能用于训练续跑。FPPO 继续严格校验源码、
构建、ABI 与资源；旧模型必须在旧兼容构建中导出，不能直接改写快照身份。

```sh
native_ppo_train --inference-mode balanced --policy POLICY.fpol --inference-cases cases.txt
native_ppo_train --inference-mode balanced --policy POLICY.fpol --inference-cases cases.txt \
  --inference-decisions 8 --inference-state-out session.fifs
native_ppo_train --inference-mode balanced --policy POLICY.fpol --inference-cases cases.txt \
  --inference-state-in session.fifs
```

场景文件每行是 `index group 0 engine_seed action_seed ax ay tx ty dx dy`，index 从 0 连续递增，
group 为 0–4；坐标为有界 2v1 场景中的学习球员、AI 队友和后卫位置。
每回合使用 cadence10、最多256次决策，第二槽始终执行内置AI动作19。
输出为每个已完成回合一行 JSON，末行 summary 表示本次调用是否完成全部场景。
分段运行时拼接回合行，忽略各段 summary。

FIFS1 推理快照包含原生环境、控制器 DIC1 状态、动作 RNG、配合指标与累计回报，绑定策略
文件、完整场景文件与推理模式的哈希。恢复还要求相同源码、构建、ABI、资源和场景；
损坏、模式或输入不匹配时拒绝恢复。只有预算耗尽并暂停时才写 session，完整运行不写它。
推理快照独立于 FPPO，禁止将它作为训练检查点使用。

## 实验性扩大起点训练

`--scenario 2v1_broad` 是独立训练任务：20%回合使用原2v1训练起点，80%从插值、更靠后、
边路、近防守及队友变化五类连续几何分布均匀选类后采样。每回合几何由引擎种子确定，
可精确重建；训练不读取验证坐标。奖励、策略观测、19动作及固定AI队友与2v1一致。
原 `--scenario 2v1` 仍使用原12点分布。

FPPO内层schema4只接受2v1_broad，schema3仍对应原2v1。两任务的完整快照不能互相恢复，
源码/构建/ABI/资源校验继续生效。两种任务均可显式导出FPOL1，供同一固定2v1策略视图
推理。扩大训练分布本身不代表学习效果已经通过；需要单独的五种子验证和新场景确认。

`--scenario 2v1_broad_annealed` 保留 broad80 的几何、奖励和策略视图，使用独立任务标识5、
FPPO内层schema5。每次更新的有效学习率为
`base_lr * max(0.1, 1 - global_update_version / 8192)`；默认从0.0003退火至0.00003，
8192更新后保持下限。时钟取完整检查点的累计更新数，分段进程不会重启调度。
每条iteration记录实际 `learning_rate`，顶层 `ppo.learning_rate` 仍为基础学习率。
原有任务继续使用固定学习率；两种broad任务的完整FPPO互相拒绝，原有源码/构建/ABI/资源
守卫保持。新任务同样可显式导出供推理使用的FPOL1，不代表已经通过学习质量确认。

`--scenario 2v1_broad_reweighted` 使用独立任务标识6和FPPO内层schema6。
它沿用任务5的奖励、策略视图、各家族内部几何和全局学习率调度，只修改训练家族概率：
旧离散起点20%，第五类连续起点40%，其他四类各10%。任务4和5的采样序列保持原样。
任务5和6的完整FPPO不能互相恢复，源码/构建/ABI/资源守卫继续生效；FPOL仍仅供推理。
重加权是针对困难家族的实验假设，尚未通过独立学习确认。
