"""Bounded plain-JSON values and immutable public save records."""
from dataclasses import dataclass
from enum import Enum
import json
import math
import sys
import time


class SaveFormatError(ValueError):
  pass


class SaveCapacityError(SaveFormatError):
  pass


class SaveConflictError(RuntimeError):
  pass


class SaveType(Enum):
  PROGRESS = 'progress'
  SETTINGS = 'settings'
  REPLAY = 'replay'
  CUSTOM = 'custom'


@dataclass(frozen=True)
class SaveLimits:
  slots: int = 10
  slot_bytes: int = 1024**2
  total_bytes: int = 8 * 1024**2
  graph_bytes: int = 4 * 1024**2
  nodes: int = 16384
  depth: int = 16
  container_items: int = 4096
  string_bytes: int = 65536

  def __post_init__(self):
    for name, lower, upper in (
        ('slots', 1, 64), ('slot_bytes', 128, 4 * 1024**2),
        ('total_bytes', 512, 64 * 1024**2), ('graph_bytes', 1024, 16 * 1024**2),
        ('nodes', 32, 65536), ('depth', 4, 32), ('container_items', 16, 16384),
        ('string_bytes', 256, 1024**2)):
      value = getattr(self, name)
      if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Invalid save limit: ' + name)
    if self.total_bytes < self.slot_bytes:
      raise ValueError('Total save capacity must fit one payload')

  @property
  def file_bytes(self):
    return self.total_bytes + self.slots * 2048 + 2048


def limits_or_default(value):
  if value is None:
    return SaveLimits()
  if type(value) is not SaveLimits:
    raise TypeError('Expected SaveLimits')
  return value


def text(value, label, maximum, *, empty=False):
  if type(value) is not str or (not value and not empty) or len(value) > maximum:
    raise SaveFormatError('Invalid ' + label)
  try:
    if len(value.encode('utf-8')) > maximum or any(ord(c) < 32 for c in value):
      raise SaveFormatError('Invalid ' + label)
  except UnicodeError as error:
    raise SaveFormatError('Invalid UTF-8 in ' + label) from error
  return value


def integer(value, label, minimum=0, maximum=2**63 - 1):
  if type(value) is not int or not minimum <= value <= maximum:
    raise SaveFormatError('Invalid ' + label)
  return value


def timestamp(value):
  if type(value) not in (int, float) or not 0 <= value <= 4102444800 or not math.isfinite(value):
    raise SaveFormatError('Invalid save timestamp')
  return float(value)


class _Copy:
  def __init__(self, limits):
    self.limits = limits
    self.nodes = self.bytes = 0
    self.ancestors = set()

  def value(self, value, depth=0):
    self.nodes += 1
    if depth > self.limits.depth or self.nodes > self.limits.nodes:
      raise SaveCapacityError('Save structure capacity exceeded')
    kind = type(value)
    if value is None or kind is bool:
      result = value
    elif kind is int:
      result = integer(value, 'save integer', -(2**63))
    elif kind is float:
      if not math.isfinite(value):
        raise SaveFormatError('Save numbers must be finite')
      result = value
    elif kind is str:
      if len(value) > self.limits.string_bytes:
        raise SaveCapacityError('Save string capacity exceeded')
      try:
        if len(value.encode('utf-8')) > self.limits.string_bytes:
          raise SaveCapacityError('Save string capacity exceeded')
      except UnicodeError as error:
        raise SaveFormatError('Save text must be UTF-8') from error
      result = value
    elif kind in (dict, list, tuple):
      if id(value) in self.ancestors:
        raise SaveFormatError('Cyclic save data')
      if len(value) > self.limits.container_items:
        raise SaveCapacityError('Save container capacity exceeded')
      self.ancestors.add(id(value))
      try:
        if kind is dict:
          result = {}
          for key, item in value.items():
            text(key, 'save field', 128)
            result[self.value(key, depth + 1)] = self.value(item, depth + 1)
        else:
          result = [self.value(item, depth + 1) for item in value]
      except RuntimeError as error:
        raise SaveFormatError('Save input changed during copying') from error
      finally:
        self.ancestors.remove(id(value))
    else:
      raise SaveFormatError('Save data must contain plain JSON values')
    self.bytes += sys.getsizeof(result)
    if self.bytes > self.limits.graph_bytes:
      raise SaveCapacityError('Save object graph byte capacity exceeded')
    return result


def encode_data(value, limits):
  if type(value) is not dict:
    raise SaveFormatError('Save payload must be a plain dictionary')
  owned = _Copy(limits).value(value)
  # The graph has already passed limits before any caller data is serialized.
  encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
  result = bytearray()
  for piece in encoder.iterencode(owned):
    raw = piece.encode('utf-8')
    if len(result) + len(raw) > limits.slot_bytes:
      raise SaveCapacityError('Save payload byte capacity exceeded')
    result.extend(raw)
  return bytes(result)


def decode_json(raw, limits, maximum=None, *, envelope=False):
  """Reject size/depth/token growth before invoking the JSON decoder."""
  maximum = limits.slot_bytes + 2048 if maximum is None else maximum
  if type(raw) not in (str, bytes) or len(raw) > maximum:
    raise SaveCapacityError('Save JSON byte capacity exceeded')
  try:
    encoded = raw.encode('utf-8') if type(raw) is str else raw
    if len(encoded) > maximum:
      raise SaveCapacityError('Save JSON byte capacity exceeded')
    source = encoded.decode('utf-8')
  except UnicodeError as error:
    raise SaveFormatError('Save JSON must be UTF-8') from error
  depth = nodes = 0
  quoted = escaped = token = False
  allowance = 32 if envelope else 0
  for char in source:
    if quoted:
      if escaped:
        escaped = False
      elif char == '\\':
        escaped = True
      elif char == '"':
        quoted = False
      continue
    if char == '"':
      quoted = True
      nodes += 1
      token = False
    elif char in '[{':
      depth += 1
      nodes += 1
      token = False
    elif char in ']}':
      depth -= 1
      token = False
    elif char in ',: \t\r\n':
      token = False
    elif not token:
      nodes += 1
      token = True
    if depth > limits.depth + 1 + bool(envelope) or nodes > limits.nodes + allowance:
      raise SaveCapacityError('Save JSON structure capacity exceeded')
  def pairs(items):
    if len(items) > limits.container_items:
      raise SaveCapacityError('Save JSON field capacity exceeded')
    result = {}
    for key, value in items:
      if key in result:
        raise SaveFormatError('Duplicate save JSON field')
      result[key] = value
    return result
  def number(value):
    if len(value.lstrip('-')) > 19:
      raise SaveFormatError('Save integer is outside int64')
    return integer(int(value), 'save integer', -(2**63))
  def real(value):
    if len(value) > 64:
      raise SaveFormatError('Save number is too long')
    result = float(value)
    if not math.isfinite(result):
      raise SaveFormatError('Save number must be finite')
    return result
  def constant(value):
    raise SaveFormatError('Invalid JSON constant')
  try:
    return json.loads(source, object_pairs_hook=pairs, parse_int=number,
                      parse_float=real, parse_constant=constant)
  except (ValueError, RecursionError) as error:
    if isinstance(error, SaveFormatError):
      raise
    raise SaveFormatError('Invalid save JSON') from error


class SaveSlot:
  """An immutable snapshot; data returns an independent bounded dictionary."""
  __slots__ = ('slot_id', 'name', 'save_type', 'created_at', 'updated_at', 'size_bytes',
               '_payload', '_bytes', '__weakref__')

  def __init__(self, slot_id, name, save_type, data=None, created_at=None, updated_at=None,
               size_bytes=0, *, limits=None):
    limits = limits_or_default(limits)
    payload = encode_data({} if data is None else data, limits)
    created_at = time.time() if created_at is None else created_at
    updated_at = max(created_at, time.time()) if updated_at is None else updated_at
    text(slot_id, 'slot ID', 64)
    text(name, 'save name', 256)
    if type(save_type) is not SaveType:
      raise SaveFormatError('Invalid save type')
    created_at, updated_at = timestamp(created_at), timestamp(updated_at)
    if updated_at < created_at:
      raise SaveFormatError('Save update precedes creation')
    for key, value in dict(slot_id=slot_id, name=name, save_type=save_type, created_at=created_at,
                           updated_at=updated_at, size_bytes=len(payload), _payload=payload).items():
      object.__setattr__(self, key, value)
    owned = (self, slot_id, name, payload, created_at, updated_at, self.size_bytes)
    object.__setattr__(self, '_bytes', sum(sys.getsizeof(value) for value in owned) + sys.getsizeof(0))

  def __setattr__(self, name, value):
    raise AttributeError('SaveSlot is immutable; use SaveManager.save')

  def __delattr__(self, name):
    raise AttributeError('SaveSlot is immutable')

  @property
  def data(self):
    return json.loads(self._payload)

  def to_dict(self):
    return dict(slot_id=self.slot_id, name=self.name, save_type=self.save_type.value,
                created_at=self.created_at, updated_at=self.updated_at, size_bytes=self.size_bytes)

  def export_bytes(self):
    meta = dict(format='football.save_slot', version=1, **self.to_dict())
    prefix = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return prefix[:-1] + b',"data":' + self._payload + b'}'


def slot_from_json(raw, limits):
  data = decode_json(raw, limits, envelope=True)
  required = {'slot_id', 'name', 'save_type'}
  allowed = required | {'data', 'created_at', 'updated_at', 'size_bytes', 'format', 'version'}
  if type(data) is not dict or not required <= data.keys() or not data.keys() <= allowed:
    raise SaveFormatError('Invalid save slot fields')
  if 'format' in data or 'version' in data:
    if data.get('format') != 'football.save_slot' or type(data.get('version')) is not int or data['version'] != 1:
      raise SaveFormatError('Unsupported save slot version')
  try:
    save_type = SaveType(data['save_type'])
  except (ValueError, TypeError) as error:
    raise SaveFormatError('Invalid save type') from error
  if type(data.get('data', {})) is not dict:
    raise SaveFormatError('Save payload must be a plain dictionary')
  for name in ('created_at', 'updated_at'):
    if name in data:
      timestamp(data[name])
  if 'size_bytes' in data:
    integer(data['size_bytes'], 'declared save size')
  return SaveSlot(data['slot_id'], data['name'], save_type, data.get('data', {}),
                  data.get('created_at'), data.get('updated_at'), limits=limits)
