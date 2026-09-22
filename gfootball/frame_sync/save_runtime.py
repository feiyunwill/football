"""Save and progress owners with transactional admission and optional disk I/O."""
import json
import os
import threading
import time

from gfootball.frame_sync.save_data import (
    SaveCapacityError, SaveFormatError, SaveSlot, SaveType, encode_data,
    integer, limits_or_default, slot_from_json, text,
)


class SaveManager:
  def __init__(self, *, limits=None, path=None, disk_limits=None):
    self._limits = limits_or_default(limits)
    self._slots = {}
    self._revision = None
    self._pid = os.getpid()
    self._lock = threading.RLock()
    self._closed = False
    self._store = None
    if path is not None:
      from gfootball.frame_sync.save_store import SaveStore
      self._store = SaveStore(path, self._limits, disk_limits)
      self.reload()
    elif disk_limits is not None:
      raise ValueError('disk_limits requires a save path')

  @property
  def limits(self):
    return self._limits

  def _check_process(self):
    if os.getpid() != self._pid:
      raise RuntimeError('Save managers cannot be reused after fork; use spawn')

  def _check(self):
    if self._closed:
      raise RuntimeError('Save manager is closed')

  def _commit(self, slots):
    if len(slots) > self._limits.slots or sum(slot._bytes for slot in slots.values()) > self._limits.total_bytes:
      raise SaveCapacityError('Save collection capacity exceeded')
    if self._store is not None:
      try:
        revision = self._store.write(slots, self._revision)
      except BaseException:
        if self._store.last_publication is not None:
          self._slots, self._revision = slots, self._store.last_publication
        raise
      self._revision = revision
    self._slots = slots

  def create_slot(self, slot_id, name, save_type=SaveType.CUSTOM):
    self._check_process()
    with self._lock:
      self._check()
      text(slot_id, 'slot ID', 64)
      if slot_id in self._slots:
        raise ValueError('Save slot already exists: ' + slot_id)
      if len(self._slots) >= self._limits.slots:
        raise SaveCapacityError('Maximum save slots reached')
      slot = SaveSlot(slot_id, name, save_type, limits=self._limits)
      candidate = dict(self._slots)
      candidate[slot_id] = slot
      self._commit(candidate)
      return slot

  def save(self, slot_id, data, name=None):
    self._check_process()
    with self._lock:
      self._check()
      text(slot_id, 'slot ID', 64)
      old = self._slots.get(slot_id)
      if old is None:
        return False
      if type(data) is not dict:
        raise SaveFormatError('Save payload must be a plain dictionary')
      slot = SaveSlot(slot_id, old.name if name is None else name, old.save_type, data,
                      old.created_at, max(old.updated_at, time.time()), limits=self._limits)
      candidate = dict(self._slots)
      candidate[slot_id] = slot
      self._commit(candidate)
      return True

  def load(self, slot_id):
    slot = self.get_slot(slot_id)
    return None if slot is None else slot.data

  def delete_slot(self, slot_id):
    self._check_process()
    with self._lock:
      self._check()
      text(slot_id, 'slot ID', 64)
      if slot_id not in self._slots:
        return False
      candidate = dict(self._slots)
      del candidate[slot_id]
      self._commit(candidate)
      return True

  def get_slot(self, slot_id):
    self._check_process()
    with self._lock:
      self._check()
      text(slot_id, 'slot ID', 64)
      return self._slots.get(slot_id)

  def list_slots(self, save_type=None):
    self._check_process()
    with self._lock:
      self._check()
      if save_type is not None and type(save_type) is not SaveType:
        raise SaveFormatError('Invalid save type')
      return [slot for slot in self._slots.values() if save_type is None or slot.save_type is save_type]

  def export_slot(self, slot_id):
    slot = self.get_slot(slot_id)
    return None if slot is None else slot.export_bytes().decode('utf-8')

  def import_slot(self, json_str):
    self._check_process()
    with self._lock:
      self._check()
      try:
        slot = slot_from_json(json_str, self._limits)
        candidate = dict(self._slots)
        candidate[slot.slot_id] = slot
        self._commit(candidate)
        return slot
      except SaveFormatError:
        return None

  def get_storage_usage(self):
    self._check_process()
    with self._lock:
      self._check()
      total = sum(slot.size_bytes for slot in self._slots.values())
      return dict(slots_used=len(self._slots), slots_max=self._limits.slots,
                  total_bytes=total, total_kb=total / 1024,
                  retained_bytes=sum(slot._bytes for slot in self._slots.values()),
                  retained_bytes_max=self._limits.total_bytes, slot_bytes_max=self._limits.slot_bytes,
                  persistent=self._store is not None,
                  generation=0 if self._revision is None else self._revision[0])

  def reload(self):
    self._check_process()
    with self._lock:
      self._check()
      if self._store is not None:
        slots, revision = self._store.read()
        self._slots, self._revision = slots, revision
      return len(self._slots)

  def close(self):
    self._check_process()
    with self._lock:
      self._slots = {}
      self._closed = True

  def __enter__(self):
    self._check_process()
    with self._lock:
      self._check()
    return self

  def __exit__(self, *args):
    self.close()


_DEFAULT_PROGRESS = {
    'career': {'current_team': None, 'season': 0, 'money': 0, 'trophies': []},
    'unlocks': {'teams': ['real_madrid', 'barcelona'], 'stadiums': ['santiago_bernabeu'], 'challenges': []},
    'stats': {'total_matches': 0, 'total_goals': 0, 'total_wins': 0, 'playtime_seconds': 0},
}


def _path(key):
  text(key, 'progress path', 512)
  parts = key.split('.')
  if len(parts) > 8:
    raise SaveCapacityError('Progress path is too deep')
  for part in parts:
    text(part, 'progress field', 64)
  return parts


def _progress_data(value, limits):
  raw = encode_data(value, limits)
  value = json.loads(raw)
  try:
    career, unlocks, stats = value['career'], value['unlocks'], value['stats']
    if any(type(item) is not dict for item in (career, unlocks, stats)):
      raise SaveFormatError('Progress sections must be dictionaries')
    if career['current_team'] is not None:
      text(career['current_team'], 'current team', 64)
    integer(career['season'], 'season', 0, 10000)
    integer(career['money'], 'career money', -(2**63))
    if type(career['trophies']) is not list:
      raise SaveFormatError('Trophies must be a list')
    for name in ('teams', 'stadiums', 'challenges'):
      entries = unlocks[name]
      if type(entries) is not list:
        raise SaveFormatError('Unlocked content must be a list')
      seen = set()
      for entry in entries:
        text(entry, 'unlocked content ID', 64)
        if entry in seen:
          raise SaveFormatError('Duplicate unlocked content')
        seen.add(entry)
    for name in ('total_matches', 'total_goals', 'total_wins', 'playtime_seconds'):
      integer(stats[name], name)
    if stats['total_wins'] > stats['total_matches']:
      raise SaveFormatError('Wins cannot exceed matches played')
  except (KeyError, TypeError) as error:
    raise SaveFormatError('Missing or invalid progress fields') from error
  return raw


class GameProgress:
  def __init__(self, *, limits=None):
    self._limits = limits_or_default(limits)
    self._lock = threading.RLock()
    self._pid = os.getpid()
    self._data = _progress_data(_DEFAULT_PROGRESS, self._limits)

  def _check_process(self):
    if self._pid != os.getpid():
      raise RuntimeError('Game progress cannot be reused after fork; use spawn')

  def get(self, key, default=None):
    self._check_process()
    parts = _path(key)
    with self._lock:
      value = json.loads(self._data)
      for part in parts:
        if type(value) is not dict or part not in value:
          return default
        value = value[part]
      return value

  def set(self, key, value):
    self._check_process()
    parts = _path(key)
    with self._lock:
      candidate = json.loads(self._data)
      target = candidate
      for part in parts[:-1]:
        if part not in target:
          target[part] = {}
        if type(target[part]) is not dict:
          raise SaveFormatError('Progress path traverses a scalar')
        target = target[part]
      target[parts[-1]] = value
      self._data = _progress_data(candidate, self._limits)

  def update_stats(self, match_played=False, goal_scored=False, won=False, playtime_seconds=0):
    self._check_process()
    if any(type(flag) is not bool for flag in (match_played, goal_scored, won)):
      raise SaveFormatError('Statistics flags must be boolean')
    integer(playtime_seconds, 'playtime increment')
    with self._lock:
      candidate = json.loads(self._data)
      stats = candidate['stats']
      for name, increment in (('total_matches', int(match_played)), ('total_goals', int(goal_scored)),
                               ('total_wins', int(won)), ('playtime_seconds', playtime_seconds)):
        stats[name] += increment
      self._data = _progress_data(candidate, self._limits)

  def unlock_team(self, team_id):
    self._check_process()
    text(team_id, 'team ID', 64)
    with self._lock:
      candidate = json.loads(self._data)
      teams = candidate['unlocks']['teams']
      if team_id in teams:
        return False
      teams.append(team_id)
      self._data = _progress_data(candidate, self._limits)
      return True

  def is_team_unlocked(self, team_id):
    text(team_id, 'team ID', 64)
    return team_id in self.get('unlocks.teams')

  def to_dict(self):
    self._check_process()
    with self._lock:
      return json.loads(self._data)

  def from_dict(self, data):
    self._check_process()
    with self._lock:
      self._data = _progress_data(data, self._limits)
