"""Deterministic match completion, including state needed by rollback/archives.

This application adapter wraps an actual engine; it does not replace its binding.
Snapshots contain a bounded, checksummed policy header and the engine snapshot.
"""
import hashlib
import os
import struct
import threading


MAX_SNAPSHOT = 1024 * 1024
_MAGIC = b'FMTERM1\0'
_HEADER = struct.Struct('<8sIBBBiibBI')
_REASONS = (None, 'duration', 'score', 'out_of_play', 'possession_change', 'engine')


def match_finished(env):
  """Optional explicit capability; legacy engine contracts keep their behavior."""
  operation = getattr(env, 'is_match_finished', None)
  if operation is None:
    return False
  if not callable(operation):
    raise ValueError('Invalid match completion capability')
  result = operation()
  if type(result) is not bool:
    raise ValueError('Match completion must return bool')
  return result


class MatchLifecycleEngine:
  def __init__(self, env, *, normal_mode, done_state):
    self._env = env
    self._owner, self._pid = threading.current_thread(), os.getpid()
    self._closed = False
    self._normal, self._done = int(normal_mode), done_state
    if not 0 <= self._normal <= 0x7fffffff:
      raise ValueError('Invalid normal game mode')
    self._rules = self._read_rules()
    info = self._info()
    # 2026-09-10: like Core, no preceding played observation exists at reset.
    # self._previous_mode = int(info.game_mode)
    # self._last_owner = info.ball_owned_team
    self._previous_mode = self._last_owner = -1
    self._reason = 5 if env.state == self._done else 0

  def _check(self):
    if os.getpid() != self._pid or threading.current_thread() is not self._owner:
      raise RuntimeError('Match lifecycle belongs to its creating thread')
    if self._closed:
      raise RuntimeError('Match lifecycle is closed')
    if self._read_rules() != self._rules:
      raise RuntimeError('Match termination configuration changed')

  def __getattr__(self, name):
    self._check()
    return getattr(self._env, name)

  def _read_rules(self):
    config = self._env.config
    duration = config.game_duration
    flags = (config.end_episode_on_score, config.end_episode_on_out_of_play,
             config.end_episode_on_possession_change)
    if type(duration) is not int or not 1 <= duration <= 0x7fffffff or any(type(v) is not bool for v in flags):
      raise ValueError('Invalid match termination configuration')
    return (duration,) + flags

  def _info(self):
    info = self._env.get_info()
    # 2026-09-10: actual GameEnv.reset sets context->step=-1 before kickoff.
    # if (type(info.step) is not int or not 0 <= info.step <= 0x7fffffff
    if (type(info.step) is not int or not -1 <= info.step <= 0x7fffffff
        or type(info.ball_owned_team) is not int or info.ball_owned_team not in (-1, 0, 1)
        or any(type(v) is not int or not 0 <= v <= 0x7fffffff for v in (info.left_goals, info.right_goals))
        or not 0 <= int(info.game_mode) <= 0x7fffffff):
      raise ValueError('Invalid match observation')
    return info

  def is_match_finished(self):
    self._check()
    return self._reason != 0

  def get_match_end_reason(self):
    self._check()
    return _REASONS[self._reason]

  def finish(self):
    """Explicit engine completion also participates in snapshot/digest state."""
    self._check()
    if not self._reason:
      self._env.finish()
      self._reason = 5

  def reset(self, *args, **kwargs):
    self._check()
    raise RuntimeError('Create a new match engine to reset; use set_state for rollback')

  def step(self):
    self._check()
    raise RuntimeError('Match simulations require step_with_input')

  def step_with_input(self, data):
    self._check()
    if self._reason:
      raise RuntimeError('Match has ended; restore a running match before stepping')
    self._env.step_with_input(data)
    info = self._info()
    duration, score, out_of_play, possession = self._rules
    mode, owner = int(info.game_mode), info.ball_owned_team
    reason = (1 if info.step >= duration else
              2 if score and (info.left_goals or info.right_goals) else
              3 if out_of_play and mode != self._normal and self._previous_mode == self._normal else
              4 if possession and owner != -1 and self._last_owner != -1 and owner != self._last_owner else
              5 if self._env.state == self._done else 0)
    if reason and self._env.state != self._done:
      self._env.finish()
    self._reason, self._previous_mode = reason, mode
    if owner != -1:
      self._last_owner = owner

  def _header(self, size):
    return _HEADER.pack(_MAGIC, *self._rules, self._normal, self._previous_mode,
                        self._last_owner, self._reason, size)

  def get_state(self, extra=''):
    self._check()
    if type(extra) not in (str, bytes) or extra not in ('', b''):
      raise ValueError('Match snapshots do not accept external payloads')
    raw = self._env.get_state('')
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_SNAPSHOT - _HEADER.size - 32:
      raise ValueError('Match snapshot capacity exceeded')
    header = self._header(len(raw))
    digest = hashlib.sha256(header)
    digest.update(raw)
    return header + digest.digest() + raw

  def set_state(self, data):
    self._check()
    if type(data) is not bytes or not _HEADER.size + 32 < len(data) <= MAX_SNAPSHOT:
      raise ValueError('Invalid match lifecycle snapshot size')
    values = _HEADER.unpack_from(data)
    magic, duration, score, out_of_play, possession, normal, previous, owner, reason, size = values
    if (magic != _MAGIC or any(v not in (0, 1) for v in (score, out_of_play, possession))
        or (duration, bool(score), bool(out_of_play), bool(possession)) != self._rules
        # 2026-09-10: -1 is the initial no-previous-observation sentinel.
        # or normal != self._normal or not 0 <= previous <= 0x7fffffff
        or normal != self._normal or not -1 <= previous <= 0x7fffffff
        or owner not in (-1, 0, 1) or not 0 <= reason < len(_REASONS)
        or size != len(data) - _HEADER.size - 32):
      raise ValueError('Incompatible match lifecycle snapshot')
    raw = memoryview(data)[_HEADER.size + 32:]
    digest = hashlib.sha256(data[:_HEADER.size])
    digest.update(raw)
    if digest.digest() != data[_HEADER.size:_HEADER.size + 32]:
      raise ValueError('Match lifecycle checksum mismatch')
    # Metadata validation precedes native mutation. A native restore or terminal
    # mismatch must restore both halves of the old state, or close the engine.
    backup = self._env.get_state('')
    if type(backup) is not bytes or not 1 <= len(backup) <= MAX_SNAPSHOT:
      raise ValueError('Match restore backup capacity exceeded')
    try:
      self._env.set_state(bytes(raw))
      # 2026-09-10: validate restored configuration/history as well as done state.
      # self._info()
      info = self._info()
      # 2026-09-10: the untouched origin has not yet observed a played frame.
      # if (self._read_rules() != self._rules or int(info.game_mode) != previous
      #     or info.ball_owned_team != -1 and info.ball_owned_team != owner):
      if (self._read_rules() != self._rules or previous == -1 and (owner != -1 or reason not in (0, 5))
          or previous != -1 and (int(info.game_mode) != previous
              or info.ball_owned_team != -1 and info.ball_owned_team != owner)):
        raise ValueError('Native and match lifecycle histories disagree')
      if (self._env.state == self._done) != bool(reason):
        raise ValueError('Native and match terminal states disagree')
      if (reason == 1 and info.step < duration
          or reason == 2 and (not score or not (info.left_goals or info.right_goals))
          or reason == 3 and (not out_of_play or int(info.game_mode) == normal)
          or reason == 4 and (not possession or info.ball_owned_team == -1)):
        raise ValueError('Invalid restored match termination reason')
    except BaseException as error:
      try:
        self._env.set_state(backup)
      except BaseException:
        try:
          self.close()
        except BaseException:
          pass
        if hasattr(error, 'add_note'):
          error.add_note('Match restore recovery failed; the engine was closed.')
      raise
    self._previous_mode, self._last_owner, self._reason = previous, owner, reason
    return b''

  def get_state_digest(self):
    self._check()
    value = self._env.get_state_digest()
    if type(value) is str and len(value) <= MAX_SNAPSHOT:
      value = value.encode('utf-8')
    if type(value) is not bytes or not 1 <= len(value) <= MAX_SNAPSHOT:
      raise ValueError('Invalid match engine digest')
    digest = hashlib.sha256(self._header(0))
    digest.update(value)
    return digest.hexdigest()

  def close(self):
    if os.getpid() != self._pid or threading.current_thread() is not self._owner:
      raise RuntimeError('Match lifecycle belongs to its creating thread')
    if not self._closed:
      self._closed = True
      self._env.close()
