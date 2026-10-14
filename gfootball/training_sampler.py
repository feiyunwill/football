"""Bounded closed-loop episodes over native process workers, with streaming data."""
from dataclasses import dataclass, replace
import hashlib
from itertools import islice
import struct
import time

import numpy as np

from gfootball.training_workers import WorkerTransition, _integer

MAX_EPISODES = 1024
MAX_EPISODE_STEPS = 4096


@dataclass(frozen=True)
class PolicyContext:
  episode_id: int
  seed: int
  step: int


@dataclass(frozen=True)
class SampleTransition:
  context: PolicyContext
  observation: np.ndarray
  actions: tuple
  following: WorkerTransition  # collector horizon is reported as truncated


@dataclass(frozen=True)
class EpisodeResult:
  episode_id: int
  seed: int
  steps: int
  reward: float
  terminated: bool
  truncated: bool
  trajectory_sha256: str
  kernel_sha256: str


@dataclass(frozen=True)
class CollectionResult:
  episodes: tuple
  transitions: int
  wall_ns: int
  policy_ns: int
  callback_ns: int
  digest_ns: int


def _readonly(array):
  result = array.copy()
  result.setflags(write=False)
  return result


def _update_digest(digest, actions, transition):
  digest.update(np.asarray(actions, dtype='<i8').tobytes())
  digest.update(np.asarray(transition.observation, dtype='<f4').tobytes())
  digest.update(np.asarray(transition.agent_rewards, dtype='<f4').tobytes())
  digest.update(struct.pack('!d??q', transition.reward, transition.terminated,
                            transition.truncated, transition.score_reward))


def collect_episodes(pool, episode_ids, policy, *, max_steps=256, on_transition=None):
  """Collect up to 1024 episodes, at most 4096 steps each, without storing history.

  policy(readonly_latest_observation, PolicyContext) decides one joint action.
  on_transition(SampleTransition) streams isolated pre/post observations for a
  learner. Callbacks run on the owner thread, outside IPC deadlines; their time
  and storage are caller-owned. Replay requires a policy deterministic per
  episode/step and unchanged during collection. Callback failures close the pool.
  """
  pool._check_open()
  _integer(max_steps, 1, MAX_EPISODE_STEPS, 'max_steps')
  if not callable(policy) or (on_transition is not None and not callable(on_transition)):
    raise ValueError('Policy and optional transition callback must be callable')
  episodes = tuple(islice(iter(episode_ids), MAX_EPISODES + 1))
  if not 1 <= len(episodes) <= MAX_EPISODES:
    raise ValueError('Select 1..1024 bounded episode IDs')
  for episode in episodes:
    _integer(episode, 0, 2**63 - 1, 'episode_id')
  if len(set(episodes)) != len(episodes):
    raise ValueError('Episode IDs in a collection must be unique')
  remaining = iter(episodes)
  current = {}
  states = {}
  completed = {}
  policy_ns = callback_ns = digest_ns = 0
  transitions = 0
  start = time.perf_counter_ns()

  def assign(worker_indices):
    assignments = {}
    for worker in sorted(worker_indices):
      episode = next(remaining, None)
      if episode is not None:
        assignments[worker] = episode
    if assignments:
      reset = pool.reset(assignments)
      for worker, transition in reset.items():
        current[worker] = transition
        digest = hashlib.sha256(np.asarray(transition.observation, dtype='<f4').tobytes())
        states[worker] = [0, 0.0, digest]

  try:
    assign(range(len(pool.worker_pids)))
    while current:
      actions = {}
      contexts = {}
      for worker, transition in sorted(current.items()):
        contexts[worker] = PolicyContext(transition.episode_id, transition.seed, states[worker][0])
        tick = time.perf_counter_ns()
        actions[worker] = pool._prepare_action(policy(_readonly(transition.observation), contexts[worker]))
        policy_ns += time.perf_counter_ns() - tick
      following = pool.step(actions)
      finished = []
      for worker, transition in following.items():
        state = states[worker]
        state[0] += 1
        state[1] += transition.reward
        horizon = state[0] == max_steps and not transition.terminated
        transition = replace(transition, truncated=horizon)
        joint = tuple(int(value) for value in np.asarray(actions[worker]).reshape(-1))
        _update_digest(state[2], joint, transition)
        transitions += 1
        if on_transition is not None:
          tick = time.perf_counter_ns()
          isolated = replace(transition, observation=_readonly(transition.observation),
                             agent_rewards=_readonly(transition.agent_rewards))
          on_transition(SampleTransition(contexts[worker], _readonly(current[worker].observation),
                                         joint, isolated))
          callback_ns += time.perf_counter_ns() - tick
        current[worker] = transition
        if transition.terminated or transition.truncated:
          finished.append(worker)
      if finished:
        tick = time.perf_counter_ns()
        digests = pool.digests()
        digest_ns += time.perf_counter_ns() - tick
        for worker in finished:
          transition = current.pop(worker)
          steps, reward, digest = states.pop(worker)
          completed[transition.episode_id] = EpisodeResult(
              transition.episode_id, transition.seed, steps, reward, transition.terminated,
              transition.truncated, digest.hexdigest(), digests[worker].hex())
        assign(finished)
    return CollectionResult(tuple(completed[episode] for episode in episodes), transitions,
                            time.perf_counter_ns() - start, policy_ns, callback_ns, digest_ns)
  except BaseException:
    # Callback/action failures cannot leave a partially sampled pool in use.
    pool._shutdown()
    raise
