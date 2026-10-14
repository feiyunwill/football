"""Bounded spawn workers owning independent native training environments.

Runtime messages use versioned JSON metadata plus little-endian float32 buffers.
Each synchronous round has one request per selected worker and one deadline.
Failures close the entire pool; completed transitions are never silently retried.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import multiprocessing
import os
import selectors
import socket
import struct
import threading
import time

import numpy as np

MAX_WORKERS = 4
MAX_METADATA = 8192
MAX_MESSAGE = 32768
PROTOCOL_VERSION = 1


class WorkerError(RuntimeError):
  """A remote exception, broken protocol, worker exit, or deadline failure."""


def _integer(value, minimum, maximum, name):
  if type(value) is not int or not minimum <= value <= maximum:
    raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
  return value


def episode_seed(base_seed, episode_id):
  """Stable uint64 Gym seed, independent of worker count and completion order."""
  _integer(base_seed, 0, 2**64 - 1, 'base_seed')
  _integer(episode_id, 0, 2**63 - 1, 'episode_id')
  data = b'football-worker-seed-v1\0' + struct.pack('!QQ', base_seed, episode_id)
  return int.from_bytes(hashlib.sha256(data).digest()[:8], 'big')


def _encode(metadata, blob=b''):
  metadata = dict(metadata, version=PROTOCOL_VERSION)
  text = json.dumps(metadata, separators=(',', ':'), allow_nan=False).encode('utf-8')
  if len(text) > MAX_METADATA or len(text) + len(blob) + 4 > MAX_MESSAGE:
    raise WorkerError('Worker message exceeds its byte budget')
  body = struct.pack('!I', len(text)) + text + blob
  return struct.pack('!I', len(body)) + body


def _decode(body):
  if not 4 <= len(body) <= MAX_MESSAGE:
    raise WorkerError('Invalid worker message length')
  size = struct.unpack('!I', body[:4])[0]
  if not 1 <= size <= MAX_METADATA or size + 4 > len(body):
    raise WorkerError('Invalid worker metadata length')
  try:
    metadata = json.loads(body[4:4 + size])
  except (UnicodeError, ValueError) as error:
    raise WorkerError('Invalid worker JSON') from error
  if (type(metadata) is not dict or type(metadata.get('version')) is not int
      or metadata.get('version') != PROTOCOL_VERSION):
    raise WorkerError('Unsupported worker protocol')
  return metadata, body[4 + size:]


def _read_exact(channel, size):
  data = bytearray()
  while len(data) < size:
    chunk = channel.recv(size - len(data))
    if not chunk:
      raise EOFError('Worker channel closed')
    data.extend(chunk)
  return bytes(data)


def _receive(channel):
  size = struct.unpack('!I', _read_exact(channel, 4))[0]
  if not 4 <= size <= MAX_MESSAGE:
    raise WorkerError('Invalid worker frame length')
  return _decode(_read_exact(channel, size))


def _worker_main(channel, config):
  # Only this creating thread touches the C++ engine. No parent engine is inherited.
  channel.setblocking(True)
  env = None
  request_id = 0
  operation = 'startup'
  try:
    from gfootball.gymnasium import FootballEnv
    env = FootballEnv(backend='native', **json.loads(config))
    channel.sendall(_encode({'id': 0, 'operation': 'startup', 'ok': True,
                             'pid': os.getpid()}))
    while True:
      request, blob = _receive(channel)
      request_id = request['id']
      operation = request['operation']
      if blob or type(request_id) is not int or request_id < 1:
        raise WorkerError('Invalid worker request')
      response = {'id': request_id, 'operation': operation, 'ok': True}
      output = b''
      if operation == 'reset':
        observation, _ = env.reset(seed=request['seed'])
        rewards = np.zeros(env._env._count, dtype='<f4')
        response.update(reward=0.0, terminated=False, truncated=False,
                        score_reward=0, episode_id=request['episode_id'], seed=request['seed'])
      elif operation == 'step':
        observation, reward, terminated, truncated, info = env.step(request['action'])
        rewards = np.asarray(info['agent_rewards'], dtype='<f4')
        response.update(reward=reward, terminated=terminated, truncated=truncated,
                        score_reward=info['score_reward'])
      elif operation == 'digest':
        response['digest'] = hashlib.sha256(env._env._native.get_state_digest()).hexdigest()
      elif operation == 'close':
        env.close()
        env = None
      else:
        raise WorkerError('Unknown worker operation')
      if operation in ('reset', 'step'):
        observation = np.asarray(observation, dtype='<f4')
        response['shape'] = list(observation.shape)
        output = observation.tobytes(order='C') + rewards.tobytes(order='C')
      channel.sendall(_encode(response, output))
      if operation == 'close':
        return
  except BaseException as error:
    try:
      channel.sendall(_encode({'id': request_id, 'operation': operation, 'ok': False,
                               'error_type': type(error).__name__, 'error': str(error)[:1024]}))
    except BaseException:
      pass
  finally:
    if env is not None:
      try:
        env.close()
      except BaseException:
        pass
    channel.close()


@dataclass(frozen=True)
class WorkerTransition:
  observation: np.ndarray
  reward: float
  agent_rewards: np.ndarray
  terminated: bool
  truncated: bool
  score_reward: int
  episode_id: int
  seed: int


class NativeWorkerPool:
  """Synchronous, owner-thread pool with 1..4 persistent spawn processes.

  reset({worker: global_episode_id}) and step({worker: action}) return dictionaries
  in worker order. There is no auto-reset, background queue, or implicit retry.
  Parent-side validation rejects an entire invalid round before any engine step.
  Use a context manager and a guarded __main__ entry point with spawn.
  """
  def __init__(self, env_kwargs, *, workers=1, base_seed=0, timeout=30.0,
               startup_timeout=60.0):
    _integer(workers, 1, MAX_WORKERS, 'workers')
    episode_seed(base_seed, 0)
    for name, value in (('timeout', timeout), ('startup_timeout', startup_timeout)):
      if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError(f'{name} must be finite and in (0, 300]')
    if type(env_kwargs) is not dict or {'backend', 'render_mode'} & env_kwargs.keys():
      raise ValueError('Pass native environment keyword arguments without backend/render_mode')
    config = json.dumps(env_kwargs, allow_nan=False)
    if len(config.encode()) > MAX_METADATA:
      raise ValueError('Environment configuration exceeds its byte budget')
    kwargs = json.loads(config)  # detach caller-owned nested dictionaries
    left = kwargs.get('number_of_left_players_agent_controls', 1)
    right = kwargs.get('number_of_right_players_agent_controls', 0)
    _integer(left, 0, 11, 'left players')
    _integer(right, 0, 11, 'right players')
    if (left == 0) == (right == 0):
      raise ValueError('Control 1..11 players on exactly one team')
    self._players = left + right
    columns = 460 if kwargs.get('stacked', False) else 115
    self._shape = (columns,) if self._players == 1 else (self._players, columns)
    options = kwargs.get('other_config_options')
    if options is not None and type(options) is not dict:
      raise ValueError('other_config_options must be a dictionary or None')
    options = kwargs['other_config_options'] = dict(options or {})
    options.setdefault('game_engine_random_seed', 0)
    self._actions = 20 if options.get('action_set') == 'v2' else 19
    config = json.dumps(kwargs, allow_nan=False)
    if len(config.encode()) > MAX_METADATA:
      raise ValueError('Environment configuration exceeds its byte budget')
    self._owner = (os.getpid(), threading.get_ident())
    self._channels = []
    self._processes = []
    self._episodes = {}
    self._next_id = 1
    self._closed = False
    self._base_seed = base_seed
    self._timeout = float(timeout)
    self.worker_pids = ()
    self.exit_codes = ()
    context = multiprocessing.get_context('spawn')
    startup_deadline = time.monotonic() + startup_timeout
    try:
      for _ in range(workers):
        parent, child = socket.socketpair()
        parent.setblocking(False)
        process = context.Process(target=_worker_main, args=(child, config), daemon=True)
        try:
          process.start()
        except BaseException:
          parent.close()
          child.close()
          raise
        child.close()
        self._channels.append(parent)
        self._processes.append(process)
      self.worker_pids = tuple(process.pid for process in self._processes)
      replies = self._exchange({i: None for i in range(workers)}, 0, 'startup',
                               max(0, startup_deadline - time.monotonic()))
      for worker, (metadata, blob) in replies.items():
        if blob or metadata.get('pid') != self.worker_pids[worker]:
          raise WorkerError('Worker startup identity mismatch')
    except BaseException:
      self._shutdown()
      raise

  @property
  def closed(self):
    return self._closed

  def _check_owner(self):
    if (os.getpid(), threading.get_ident()) != self._owner:
      raise RuntimeError('Worker pool must be used by its creating process and thread')

  def _check_open(self):
    self._check_owner()
    if self._closed:
      raise RuntimeError('Worker pool is closed')
    if any(not process.is_alive() for process in self._processes):
      self._shutdown()
      raise WorkerError('A worker exited; the entire pool has been closed')

  def _selection(self, values):
    self._check_open()
    if type(values) is not dict or not 1 <= len(values) <= len(self._channels):
      raise ValueError('Select a nonempty bounded dictionary of workers')
    for worker in values:
      _integer(worker, 0, len(self._channels) - 1, 'worker')

  def _exchange(self, packets, request_id, operation, timeout):
    # Nonblocking framing prevents a partial response from defeating the deadline.
    deadline = time.monotonic() + timeout
    replies = {}
    incoming = {worker: bytearray() for worker in packets}
    outgoing = {worker: memoryview(packet) for worker, packet in packets.items() if packet}
    expected = {}
    try:
      with selectors.DefaultSelector() as selector:
        for worker in packets:
          mask = selectors.EVENT_READ | (selectors.EVENT_WRITE if worker in outgoing else 0)
          selector.register(self._channels[worker], mask, worker)
        while len(replies) < len(packets):
          remaining = deadline - time.monotonic()
          if remaining <= 0:
            raise WorkerError(f'{operation} deadline exceeded; outstanding workers '
                              f'{sorted(set(packets) - replies.keys())}')
          for key, mask in selector.select(remaining):
            worker = key.data
            channel = key.fileobj
            if mask & selectors.EVENT_WRITE:
              sent = channel.send(outgoing[worker])
              outgoing[worker] = outgoing[worker][sent:]
              if not outgoing[worker]:
                del outgoing[worker]
                selector.modify(channel, selectors.EVENT_READ, worker)
            if mask & selectors.EVENT_READ:
              data = channel.recv(MAX_MESSAGE + 4 - len(incoming[worker]))
              if not data:
                raise WorkerError(f'Worker {worker} exited during {operation}')
              incoming[worker].extend(data)
              buffer = incoming[worker]
              if worker not in expected and len(buffer) >= 4:
                expected[worker] = struct.unpack('!I', buffer[:4])[0]
                if not 4 <= expected[worker] <= MAX_MESSAGE:
                  raise WorkerError(f'Worker {worker} exceeded message budget')
              if worker in expected and len(buffer) >= expected[worker] + 4:
                if len(buffer) != expected[worker] + 4 or worker in outgoing:
                  raise WorkerError(f'Worker {worker} sent an unsolicited response')
                metadata, blob = _decode(buffer[4:])
                if (type(metadata.get('id')) is not int or metadata.get('id') != request_id
                    or metadata.get('operation') != operation):
                  raise WorkerError(f'Worker {worker} response identity mismatch')
                if metadata.get('ok') is not True:
                  raise WorkerError(f'Worker {worker} {operation}: '
                                    f'{metadata.get("error_type")}: {metadata.get("error")}')
                replies[worker] = (metadata, blob)
                selector.unregister(channel)
      return dict(sorted(replies.items()))
    except OSError as error:
      self._shutdown()
      raise WorkerError(f'Worker channel failed during {operation}: {error}') from error
    except BaseException:
      self._shutdown()
      raise

  def _request(self, operation, arguments):
    request_id = self._next_id
    packets = {worker: _encode(dict(value, id=request_id, operation=operation))
               for worker, value in arguments.items()}
    self._next_id += 1
    return self._exchange(packets, request_id, operation, self._timeout)

  def _transition(self, metadata, blob, episode_id, seed):
    size = math.prod(self._shape)
    if (metadata.get('shape') != list(self._shape) or len(blob) != 4 * (size + self._players)
        or type(metadata.get('terminated')) is not bool or metadata.get('truncated') is not False
        or type(metadata.get('score_reward')) is not int
        or type(metadata.get('reward')) not in (float, int)):
      raise WorkerError('Invalid worker transition')
    observation = np.frombuffer(blob[:size * 4], dtype='<f4').reshape(self._shape).copy()
    rewards = np.frombuffer(blob[size * 4:], dtype='<f4').copy()
    if not np.isfinite(observation).all() or not np.isfinite(rewards).all() or not math.isfinite(metadata['reward']):
      raise WorkerError('Nonfinite worker transition')
    return WorkerTransition(observation, float(metadata['reward']), rewards,
                            metadata['terminated'], False, metadata['score_reward'], episode_id, seed)

  def reset(self, episode_ids):
    self._selection(episode_ids)
    arguments = {worker: {'episode_id': episode, 'seed': episode_seed(self._base_seed, episode)}
                 for worker, episode in episode_ids.items()}
    replies = self._request('reset', arguments)
    try:
      result = {}
      for worker, (metadata, blob) in replies.items():
        episode, seed = arguments[worker]['episode_id'], arguments[worker]['seed']
        if metadata.get('episode_id') != episode or metadata.get('seed') != seed:
          raise WorkerError('Worker episode identity mismatch')
        result[worker] = self._transition(metadata, blob, episode, seed)
        self._episodes[worker] = (episode, seed, False)
      return result
    except BaseException:
      self._shutdown()
      raise

  def step(self, actions):
    self._selection(actions)
    arguments = {}
    for worker, action in actions.items():
      if worker not in self._episodes or self._episodes[worker][2]:
        raise ValueError(f'Reset worker {worker} before stepping')
      values = [action] if self._players == 1 else action
      if isinstance(values, np.ndarray):
        if values.shape != (self._players,):
          raise ValueError('One action is required per controlled player')
        values = list(values)
      if type(values) not in (list, tuple) or len(values) != self._players:
        raise ValueError('One action is required per controlled player')
      values = [_integer(int(value) if isinstance(value, np.integer) else value,
                         0, self._actions - 1, 'action') for value in values]
      arguments[worker] = {'action': values[0] if self._players == 1 else values}
    replies = self._request('step', arguments)
    try:
      result = {}
      for worker, (metadata, blob) in replies.items():
        episode, seed, _ = self._episodes[worker]
        transition = self._transition(metadata, blob, episode, seed)
        result[worker] = transition
        self._episodes[worker] = (episode, seed, transition.terminated)
      return result
    except BaseException:
      self._shutdown()
      raise

  def digests(self):
    self._check_open()
    replies = self._request('digest', {worker: {} for worker in self._episodes})
    try:
      result = {}
      for worker, (metadata, blob) in replies.items():
        digest = metadata.get('digest')
        if blob or type(digest) is not str or len(digest) != 64:
          raise WorkerError('Invalid worker digest')
        result[worker] = bytes.fromhex(digest)
      return result
    except BaseException:
      self._shutdown()
      raise

  def _shutdown(self, graceful=False):
    self._closed = True
    for channel in self._channels:
      channel.close()
    if graceful:
      deadline = time.monotonic() + 1
      for process in self._processes:
        process.join(max(0, deadline - time.monotonic()))
    for process in self._processes:
      if process.is_alive():
        process.terminate()
    deadline = time.monotonic() + 2
    for process in self._processes:
      process.join(max(0, deadline - time.monotonic()))
    for process in self._processes:
      if process.is_alive():
        process.kill()
    deadline = time.monotonic() + 2
    for process in self._processes:
      process.join(max(0, deadline - time.monotonic()))
    if any(process.is_alive() for process in self._processes):
      raise WorkerError('Worker could not be reaped after termination and kill')
    if self._processes:
      self.exit_codes = tuple(process.exitcode for process in self._processes)
    for process in self._processes:
      process.close()
    self._processes.clear()

  def close(self):
    self._check_owner()
    if self._closed:
      if self._processes:
        self._shutdown()
      return
    try:
      replies = self._request('close', {i: {} for i in range(len(self._channels))})
      if any(blob for _, blob in replies.values()):
        raise WorkerError('Invalid worker close acknowledgement')
    finally:
      self._shutdown(graceful=True)

  def __enter__(self):
    self._check_open()
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    if exc_type is None:
      self.close()
    else:
      self._check_owner()
      self._shutdown()
