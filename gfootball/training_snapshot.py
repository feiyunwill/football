"""Bounded non-pickle metadata envelope and atomic local snapshot files."""
import json
import math
import os
import stat
import struct
import tempfile
import zlib
import base64
import sys

MAX_NATIVE_BYTES = 10_032_784
MAX_METADATA_BYTES = 65_536
MAX_BYTES = 20 + MAX_METADATA_BYTES + MAX_NATIVE_BYTES
HEADER = struct.Struct('<4sIIII')


def _values(value, depth=0):
  if depth > 8:
    raise ValueError('Snapshot metadata exceeds nesting budget')
  if value is None or type(value) is bool:
    return
  if type(value) is int and value.bit_length() <= 256:
    return
  if type(value) is float and math.isfinite(value):
    return
  if type(value) is str and len(value) <= 8192:
    return
  if type(value) is list and len(value) <= 128:
    for item in value:
      _values(item, depth + 1)
    return
  if type(value) is dict and len(value) <= 128 and all(type(k) is str and len(k) <= 128 for k in value):
    for item in value.values():
      _values(item, depth + 1)
    return
  raise ValueError('Invalid snapshot metadata value or capacity')


def encode(metadata, native):
  if type(native) is not bytes or not 16 <= len(native) <= MAX_NATIVE_BYTES:
    raise ValueError('Invalid native snapshot byte length')
  if type(metadata) is not dict:
    raise ValueError('Snapshot metadata must be a dictionary')
  _values(metadata)
  payload = json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
  if len(payload) > MAX_METADATA_BYTES:
    raise ValueError('Snapshot metadata exceeds byte budget')
  body = payload + native
  return HEADER.pack(b'FPTR', 1, len(payload), len(native), zlib.crc32(body)) + body


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result:
      raise ValueError('Duplicate snapshot metadata key')
    result[key] = value
  return result


def decode(data):
  if type(data) is not bytes:
    raise TypeError('Snapshot must be immutable bytes')
  if not HEADER.size <= len(data) <= MAX_BYTES:
    raise ValueError('Invalid snapshot byte length')
  magic, version, metadata_size, native_size, checksum = HEADER.unpack_from(data)
  if magic != b'FPTR' or version != 1:
    raise ValueError('Unsupported Python training snapshot version')
  if not 1 <= metadata_size <= MAX_METADATA_BYTES or not 16 <= native_size <= MAX_NATIVE_BYTES:
    raise ValueError('Snapshot fields exceed byte budget')
  if len(data) != HEADER.size + metadata_size + native_size:
    raise ValueError('Snapshot length mismatch')
  body = data[HEADER.size:]
  if zlib.crc32(body) != checksum:
    raise ValueError('Snapshot checksum mismatch')
  try:
    metadata = json.loads(body[:metadata_size], object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite metadata')))
  except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
    raise ValueError('Invalid snapshot metadata') from error
  if type(metadata) is not dict:
    raise ValueError('Snapshot metadata must be a dictionary')
  _values(metadata)
  return metadata, body[metadata_size:]


def _path(path):
  value = os.fspath(path)
  if type(value) is not str or not value or '\0' in value or len(os.fsencode(value)) > 4096:
    raise ValueError('Snapshot path must contain 1..4096 non-NUL bytes')
  value = os.path.abspath(value)
  if len(os.fsencode(value)) > 4096:
    raise ValueError('Resolved snapshot path exceeds byte budget')
  return value


def save(path, data):
  """Replace only after complete writing/fsync; failures before replace keep old file."""
  decode(data)
  target = _path(path)
  parent = os.path.dirname(target)
  descriptor, temporary = tempfile.mkstemp(prefix='.football-snapshot-', dir=parent)
  try:
    with os.fdopen(descriptor, 'wb') as stream:
      descriptor = None
      written = stream.write(data)
      if written != len(data):
        raise OSError('Incomplete snapshot write')
      stream.flush()
      os.fsync(stream.fileno())
    os.replace(temporary, target)
    temporary = None
    # Directory fsync makes the replacement durable on supported POSIX filesystems.
    if os.name == 'posix':
      directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
      try:
        os.fsync(directory)
      finally:
        os.close(directory)
  finally:
    failure = sys.exc_info()[1]
    try:
      if descriptor is not None:
        os.close(descriptor)
      if temporary is not None:
        os.unlink(temporary)
    except BaseException:
      if failure is None:
        raise
      if hasattr(failure, 'add_note'):
        failure.add_note('Snapshot temporary-file cleanup also failed.')


def load(path):
  """Read a regular file within the fixed budget, including a growing-file check."""
  descriptor = os.open(_path(path), os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
  try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or not HEADER.size <= info.st_size <= MAX_BYTES:
      raise ValueError('Snapshot must be a regular file within the byte budget')
    stream = os.fdopen(descriptor, 'rb')
    descriptor = None
    with stream:
      data = stream.read(MAX_BYTES + 1)
  finally:
    if descriptor is not None:
      os.close(descriptor)
  decode(data)
  return data


def _chain(env):
  import gymnasium as gym
  from gfootball.gymnasium import FootballEnv
  wrappers = []
  while type(env) in (gym.wrappers.TimeLimit, gym.wrappers.OrderEnforcing, gym.wrappers.PassiveEnvChecker):
    if len(wrappers) >= 8 or any(env is wrapper for wrapper in wrappers):
      raise ValueError('Snapshot wrapper chain exceeds budget or contains a cycle')
    wrappers.append(env)
    env = env.env
  if type(env) is not FootballEnv:
    raise ValueError('Snapshot supports only native FootballEnv and standard TimeLimit/OrderEnforcing/PassiveEnvChecker')
  env._check_snapshot()
  return env, wrappers


def _array(value):
  import numpy as np
  if type(value) is not np.ndarray or value.dtype != np.float32 or value.size > 5060 or not np.isfinite(value).all():
    raise ValueError('Invalid checker history array')
  encoded = base64.b64encode(value.astype('<f4', copy=False).tobytes()).decode('ascii')
  return {'shape': list(value.shape), 'float32': [encoded[i:i + 4096] for i in range(0, len(encoded), 4096)]}


def _restore_array(value, shape):
  import numpy as np
  if (type(value) is not dict or set(value) != {'shape', 'float32'} or
      type(value['shape']) is not list or any(type(n) is not int for n in value['shape']) or
      value['shape'] != list(shape)):
    raise ValueError('Checker history shape mismatch')
  chunks = value['float32']
  if type(chunks) is not list or len(chunks) > 7 or any(type(c) is not str or len(c) > 4096 for c in chunks):
    raise ValueError('Checker history byte budget exceeded')
  try:
    data = base64.b64decode(''.join(chunks), validate=True)
  except (ValueError, UnicodeError) as error:
    raise ValueError('Invalid checker history bytes') from error
  if len(data) != int(np.prod(shape)) * 4:
    raise ValueError('Checker history length mismatch')
  result = np.frombuffer(data, dtype='<f4').reshape(shape).astype(np.float32, copy=True)
  if not np.isfinite(result).all():
    raise ValueError('Nonfinite checker history')
  return result


def _checker_data(previous):
  if previous is None:
    return None
  observation, info = previous
  encoded = dict(info)
  if 'agent_rewards' in encoded:
    encoded['agent_rewards'] = _array(encoded['agent_rewards'])
  return {'observation': _array(observation), 'info': encoded}


def _restore_checker_data(previous, raw):
  if previous is None:
    return None
  if type(previous) is not dict or set(previous) != {'observation', 'info'} or type(previous['info']) is not dict:
    raise ValueError('Invalid checker previous data')
  info = dict(previous['info'])
  if set(info) - {'agent_rewards', 'score_reward'}:
    raise ValueError('Unknown checker history info')
  if 'agent_rewards' in info:
    info['agent_rewards'] = _restore_array(info['agent_rewards'], (raw._env._count,))
  if 'score_reward' in info and type(info['score_reward']) is not int:
    raise ValueError('Invalid checker score')
  return _restore_array(previous['observation'], raw.observation_space.shape), info


def get_state(env):
  """Snapshot raw or standard wrapped native Gym environments; unknown wrappers reject."""
  import gymnasium as gym
  raw, wrappers = _chain(env)
  metadata, native = decode(raw.get_state())
  chain = []
  for wrapper in wrappers:
    if type(wrapper) is gym.wrappers.TimeLimit:
      if type(wrapper._elapsed_steps) is not int or not 0 <= wrapper._elapsed_steps < (1 << 63):
        raise ValueError('Reset the complete TimeLimit wrapper before saving')
      record = {'name': 'TimeLimit', 'maximum': wrapper._max_episode_steps, 'elapsed': wrapper._elapsed_steps}
    elif type(wrapper) is gym.wrappers.OrderEnforcing:
      if wrapper._has_reset is not True:
        raise ValueError('Reset the complete OrderEnforcing wrapper before saving')
      record = {'name': 'OrderEnforcing', 'has_reset': wrapper._has_reset,
                'disable_render': wrapper._disable_render_order_enforcing}
    else:
      fields = ('checked_reset', 'checked_step', 'checked_render', 'close_called', 'checked_data_reuse')
      record = {'name': 'PassiveEnvChecker', **{name: getattr(wrapper, name) for name in fields},
                'previous': _checker_data(wrapper._previous_data)}
    chain.append(record)
  metadata['wrapper_chain'] = chain
  metadata['gymnasium_version'] = gym.__version__
  return encode(metadata, native)


def set_state(env, data):
  import gymnasium as gym
  raw, wrappers = _chain(env)
  metadata, native = decode(data)
  if metadata.pop('gymnasium_version', None) != gym.__version__:
    raise ValueError('Snapshot Gymnasium version differs')
  chain = metadata.pop('wrapper_chain', None)
  if type(chain) is not list or len(chain) != len(wrappers):
    raise ValueError('Snapshot wrapper chain differs')
  prepared = []
  for wrapper, record in zip(wrappers, chain):
    if type(record) is not dict:
      raise ValueError('Invalid wrapper record')
    if type(wrapper) is gym.wrappers.TimeLimit:
      if (set(record) != {'name', 'maximum', 'elapsed'} or record['name'] != 'TimeLimit' or
          type(record['maximum']) is not int or record['maximum'] != wrapper._max_episode_steps or
          type(record['elapsed']) is not int or not 0 <= record['elapsed'] < (1 << 63)):
        raise ValueError('TimeLimit snapshot differs or has invalid elapsed count')
      prepared.append({'_elapsed_steps': record['elapsed']})
    elif type(wrapper) is gym.wrappers.OrderEnforcing:
      if (set(record) != {'name', 'has_reset', 'disable_render'} or record['name'] != 'OrderEnforcing' or
          record['has_reset'] is not True or type(record['disable_render']) is not bool or
          record['disable_render'] != wrapper._disable_render_order_enforcing):
        raise ValueError('Invalid OrderEnforcing snapshot')
      prepared.append({'_has_reset': True})
    else:
      fields = ('checked_reset', 'checked_step', 'checked_render', 'close_called', 'checked_data_reuse')
      if (set(record) != set(fields) | {'name', 'previous'} or record['name'] != 'PassiveEnvChecker' or
          any(type(record[name]) is not bool for name in fields) or record['close_called']):
        raise ValueError('Invalid PassiveEnvChecker snapshot')
      previous = _restore_checker_data(record['previous'], raw)
      if record['checked_data_reuse'] and previous is not None:
        raise ValueError('Checker completed reuse check but retains previous data')
      prepared.append({**{name: record[name] for name in fields}, '_previous_data': previous})
  # Both wrapper and raw metadata are validated/prepared before kernel mutation.
  prepared_raw = encode(metadata, native)
  assignments = list(zip(wrappers, prepared))
  undo = [(wrapper, {key: wrapper.__dict__[key] for key in values}) for wrapper, values in assignments]
  prior_raw = raw.get_state()
  raw.set_state(prepared_raw)
  try:
    _commit_wrappers(assignments)
  except BaseException as failure:
    try:
      raw.set_state(prior_raw)
      _commit_wrappers(undo)
    except BaseException:
      try:
        env.close()
      finally:
        raise RuntimeError('Wrapper snapshot rollback failed; environment was closed') from failure
    raise


def _commit_wrappers(assignments):
  for wrapper, values in assignments:
    wrapper.__dict__.update(values)


def save_state(env, path):
  save(path, get_state(env))


def load_state(env, path):
  _chain(env)  # Ownership check before filesystem work.
  set_state(env, load(path))
