# 2026-09-10: immutable, size-accounted match records; no engine or I/O imports.
"""Frame replay values are JSON data, distinct from native state/pickle replays."""
# 2026-09-10: fields now use Python 3.9-compatible explicit immutable slots.
# from dataclasses import dataclass, field
from dataclasses import dataclass, FrozenInstanceError
from enum import Enum
import math
import sys
from types import MappingProxyType
# 2026-09-10: no evaluated union annotations are required by the slotted records.
# from typing import Optional

MAX_FRAME = 0xfffffff7
MAX_TIME_MS = 7 * 24 * 60 * 60 * 1000
RECORD_BYTES = 64 * 1024


class ReplayFormatError(ValueError):
  pass


class ReplayCapacityError(ReplayFormatError):
  pass


@dataclass(frozen=True)
class ReplayLimits:
  frames: int = 100000
  events: int = 10000
  replay_bytes: int = 128 * 1024**2
  total_bytes: int = 256 * 1024**2
  replays: int = 50
  frame_bytes: int = RECORD_BYTES
  event_bytes: int = RECORD_BYTES
  file_bytes: int = 128 * 1024**2
  line_bytes: int = 512 * 1024

  def __post_init__(self):
    for name, lower, upper in (
        ('frames', 1, 1000000), ('events', 1, 100000),
        ('replay_bytes', 512, 512 * 1024**2), ('total_bytes', 512, 1024**3),
        ('replays', 1, 1000), ('frame_bytes', 128, RECORD_BYTES),
        ('event_bytes', 128, RECORD_BYTES), ('file_bytes', 128, 1024**3),
        ('line_bytes', 128, 1024**2)):
      integer(getattr(self, name), name, upper, lower)
    if self.total_bytes < self.replay_bytes:
      raise ValueError('Total replay capacity must fit one replay budget')


def limits_or_default(value):
  if value is None:
    return ReplayLimits()
  if type(value) is not ReplayLimits:
    raise ValueError('Expected ReplayLimits')
  return value


def integer(value, name, maximum=MAX_FRAME, minimum=0):
  if type(value) is not int or not minimum <= value <= maximum:
    raise ReplayFormatError('Invalid ' + name)
  return value


def text(value, name, maximum=128, *, optional=False):
  if optional and value is None:
    return None
  if type(value) is not str or not value or len(value) > maximum or '\0' in value:
    raise ReplayFormatError('Invalid ' + name)
  try:
    if len(value.encode('utf-8')) > maximum:
      raise ReplayFormatError('Invalid ' + name)
  except UnicodeError as error:
    raise ReplayFormatError('Invalid ' + name) from error
  return value


def finite(value, name, maximum=1000000):
  if type(value) not in (int, float) or not -maximum <= value <= maximum or not math.isfinite(value):
    raise ReplayFormatError('Invalid ' + name)
  return float(value)


class _Freeze:
  """Count and copy plain JSON graphs, never run caller-defined conversion code."""
  def __init__(self):
    self.nodes = self.used = 0
    self.ancestors = set()

  def charge(self, size):
    self.used += size
    if self.used > RECORD_BYTES:
      raise ReplayCapacityError('Replay record byte capacity exceeded')

  def value(self, value, depth=0):
    self.nodes += 1
    if depth > 8 or self.nodes > 2048:
      raise ReplayCapacityError('Replay record structure capacity exceeded')
    kind = type(value)
    if value is None or kind is bool:
      result = value
    elif kind is int:
      if not -(2**63) <= value < 2**63:
        raise ReplayFormatError('Replay integer is outside int64')
      result = value
    elif kind is float:
      if not math.isfinite(value):
        raise ReplayFormatError('Replay values must be finite')
      result = value
    elif kind is str:
      if len(value) > 4096:
        raise ReplayCapacityError('Replay string capacity exceeded')
      try:
        if len(value.encode('utf-8')) > 4096:
          raise ReplayCapacityError('Replay string capacity exceeded')
      except UnicodeError as error:
        raise ReplayFormatError('Replay text is not valid UTF-8') from error
      result = value
    elif kind in (list, tuple, dict, MappingProxyType):
      if id(value) in self.ancestors:
        raise ReplayFormatError('Cyclic replay data')
      if len(value) > 128:
        raise ReplayCapacityError('Replay container capacity exceeded')
      self.ancestors.add(id(value))
      try:
        if kind in (dict, MappingProxyType):
          copied = {}
          for key, item in value.items():
            text(key, 'replay field', 128)
            copied[self.value(key, depth + 1)] = self.value(item, depth + 1)
          self.charge(sys.getsizeof(copied))
          result = MappingProxyType(copied)
        else:
          result = tuple(self.value(item, depth + 1) for item in value)
      finally:
        self.ancestors.remove(id(value))
    else:
      raise ReplayFormatError('Replay data must contain plain JSON values')
    self.charge(sys.getsizeof(result))
    return result


def thaw(value):
  if type(value) is MappingProxyType:
    return {key: thaw(item) for key, item in value.items()}
  if type(value) is tuple:
    return [thaw(item) for item in value]
  return value


def _position(value):
  if type(value) not in (tuple, list) or len(value) != 3:
    raise ReplayFormatError('Positions must have exactly three coordinates')
  return tuple(finite(item, 'coordinate') for item in value)


def _players(value, positions=False):
  if type(value) not in (dict, MappingProxyType) or len(value) > 22:
    raise ReplayFormatError('Replay player map must contain at most 22 entries')
  result = {}
  for key, item in value.items():
    text(key, 'player ID')
    if positions:
      result[key] = _position(item)
    else:
      if type(item) not in (dict, MappingProxyType):
        raise ReplayFormatError('Replay input must be a field mapping')
      result[key] = item
  return result


class ReplayEventType(Enum):
  GOAL = 'goal'
  SAVE = 'save'
  FOUL = 'foul'
  CARD = 'card'
  SUBSTITUTION = 'substitution'
  MATCH_START = 'match_start'
  MATCH_END = 'match_end'
  # 2026-09-10: bounded native-origin chunks for actual match playback.
  STATE_SNAPSHOT = 'state_snapshot'


# 2026-09-10: explicit slots work on Python 3.9 and remove the writable __dict__
# escape hatch. Public constructors/fields/equality/to_dict remain available.
# # 2026-09-10: retain the package's Python >=3.9 declaration and weak references.
# # @dataclass(frozen=True, slots=True)
# @dataclass(frozen=True)
# class ReplayEvent:
#   event_type: ReplayEventType
#   timestamp_ms: int
#   frame_id: int
#   # 2026-09-10: union operator annotations require Python 3.10 at evaluation.
#   # player_id: str | None = None
#   # team_id: str | None = None
#   player_id: Optional[str] = None
#   team_id: Optional[str] = None
#   details: dict = field(default_factory=dict)
#   _bytes: int = field(init=False, repr=False, compare=False)
# 
#   def __post_init__(self):
#     if type(self.event_type) is not ReplayEventType:
#       raise ReplayFormatError('Unknown replay event type')
#     integer(self.timestamp_ms, 'event timestamp', MAX_TIME_MS)
#     integer(self.frame_id, 'event frame')
#     text(self.player_id, 'player ID', optional=True)
#     text(self.team_id, 'team ID', optional=True)
#     if type(self.details) not in (dict, MappingProxyType):
#       raise ReplayFormatError('Event details must be a mapping')
#     freezer = _Freeze()
#     details = freezer.value(self.details)
#     object.__setattr__(self, '_bytes', 0)
#     # 2026-09-10: account the actual dataclass dictionary, including the byte field.
#     # freezer.charge(sys.getsizeof(self) + 64 + sum(sys.getsizeof(item) for item in (
#     freezer.charge(sys.getsizeof(self) + sys.getsizeof(self.__dict__) + 64 + sum(sys.getsizeof(item) for item in (
#         self.event_type.value, self.timestamp_ms, self.frame_id, self.player_id, self.team_id)))
#     object.__setattr__(self, 'details', details)
#     object.__setattr__(self, '_bytes', freezer.used)
# 
#   @property
#   def retained_bytes(self):
#     return self._bytes
# 
#   def to_dict(self):
#     return dict(event_type=self.event_type.value, timestamp_ms=self.timestamp_ms,
#                 frame_id=self.frame_id, player_id=self.player_id,
#                 team_id=self.team_id, details=thaw(self.details))
# 
#   @classmethod
#   def from_dict(cls, data):
#     if type(data) is not dict or set(data) != {
#         'event_type', 'timestamp_ms', 'frame_id', 'player_id', 'team_id', 'details'}:
#       raise ReplayFormatError('Invalid replay event fields')
#     try:
#       kind = ReplayEventType(data['event_type'])
#     except (TypeError, ValueError) as error:
#       raise ReplayFormatError('Unknown replay event type') from error
#     return cls(kind, data['timestamp_ms'], data['frame_id'], data['player_id'], data['team_id'], data['details'])
# 
# 
# # 2026-09-10: Python 3.9-compatible immutable dataclass with measured instance dict.
# # @dataclass(frozen=True, slots=True)
# @dataclass(frozen=True)
# class ReplayFrame:
#   frame_id: int
#   ball_pos: tuple = (0, 0, 0)
#   player_positions: dict = field(default_factory=dict)
#   inputs: dict = field(default_factory=dict)
#   _bytes: int = field(init=False, repr=False, compare=False)
# 
#   def __post_init__(self):
#     integer(self.frame_id, 'replay frame')
#     freezer = _Freeze()
#     ball = freezer.value(_position(self.ball_pos))
#     positions = freezer.value(_players(self.player_positions, positions=True))
#     inputs = freezer.value(_players(self.inputs))
#     # 2026-09-10: include instance storage after all fields have been allocated.
#     # freezer.charge(sys.getsizeof(self) + sys.getsizeof(self.frame_id) + 64)
#     object.__setattr__(self, '_bytes', 0)
#     freezer.charge(sys.getsizeof(self) + sys.getsizeof(self.__dict__) + sys.getsizeof(self.frame_id) + 64)
#     object.__setattr__(self, 'ball_pos', ball)
#     object.__setattr__(self, 'player_positions', positions)
#     object.__setattr__(self, 'inputs', inputs)
#     object.__setattr__(self, '_bytes', freezer.used)
# 
#   @property
#   def retained_bytes(self):
#     return self._bytes
# 
#   def to_dict(self):
#     return dict(frame_id=self.frame_id, ball_pos=self.ball_pos,
#                 player_positions={key: tuple(value) for key, value in self.player_positions.items()},
#                 inputs=thaw(self.inputs))
# 
#   @classmethod
#   def from_dict(cls, data):
#     if type(data) is not dict or set(data) != {'frame_id', 'ball_pos', 'player_positions', 'inputs'}:
#       raise ReplayFormatError('Invalid replay frame fields')
#     return cls(**data)

_EMPTY = object()


class _ImmutableRecord:
  __slots__ = ()
  __hash__ = None

  def __setattr__(self, name, value):
    raise FrozenInstanceError('Replay record fields are immutable')

  def __delattr__(self, name):
    raise FrozenInstanceError('Replay record fields are immutable')

  def __eq__(self, other):
    if type(self) is not type(other):
      return NotImplemented
    return all(getattr(self, name) == getattr(other, name) for name in self._fields)

  def __repr__(self):
    return type(self).__name__ + '(' + ', '.join(name + '=' + repr(getattr(self, name)) for name in self._fields) + ')'

  @property
  def retained_bytes(self):
    return self._bytes


class ReplayEvent(_ImmutableRecord):
  __slots__ = ('event_type', 'timestamp_ms', 'frame_id', 'player_id', 'team_id', 'details', '_bytes', '__weakref__')
  _fields = ('event_type', 'timestamp_ms', 'frame_id', 'player_id', 'team_id', 'details')

  def __init__(self, event_type, timestamp_ms, frame_id, player_id=None, team_id=None, details=_EMPTY):
    if type(event_type) is not ReplayEventType:
      raise ReplayFormatError('Unknown replay event type')
    integer(timestamp_ms, 'event timestamp', MAX_TIME_MS)
    integer(frame_id, 'event frame')
    text(player_id, 'player ID', optional=True)
    text(team_id, 'team ID', optional=True)
    details = {} if details is _EMPTY else details
    if type(details) not in (dict, MappingProxyType):
      raise ReplayFormatError('Event details must be a mapping')
    freezer = _Freeze()
    details = freezer.value(details)
    freezer.charge(sys.getsizeof(self) + 64 + sum(sys.getsizeof(item) for item in (
        event_type.value, timestamp_ms, frame_id, player_id, team_id)))
    for name, value in zip(self._fields, (event_type, timestamp_ms, frame_id, player_id, team_id, details)):
      object.__setattr__(self, name, value)
    object.__setattr__(self, '_bytes', freezer.used)

  def to_dict(self):
    return dict(event_type=self.event_type.value, timestamp_ms=self.timestamp_ms,
                frame_id=self.frame_id, player_id=self.player_id,
                team_id=self.team_id, details=thaw(self.details))

  @classmethod
  def from_dict(cls, data):
    if type(data) is not dict or set(data) != {
        'event_type', 'timestamp_ms', 'frame_id', 'player_id', 'team_id', 'details'}:
      raise ReplayFormatError('Invalid replay event fields')
    try:
      kind = ReplayEventType(data['event_type'])
    except (TypeError, ValueError) as error:
      raise ReplayFormatError('Unknown replay event type') from error
    return cls(kind, data['timestamp_ms'], data['frame_id'], data['player_id'], data['team_id'], data['details'])


class ReplayFrame(_ImmutableRecord):
  __slots__ = ('frame_id', 'ball_pos', 'player_positions', 'inputs', '_bytes', '__weakref__')
  _fields = ('frame_id', 'ball_pos', 'player_positions', 'inputs')

  def __init__(self, frame_id, ball_pos=(0, 0, 0), player_positions=_EMPTY, inputs=_EMPTY):
    integer(frame_id, 'replay frame')
    freezer = _Freeze()
    ball = freezer.value(_position(ball_pos))
    positions = freezer.value(_players({} if player_positions is _EMPTY else player_positions, positions=True))
    inputs = freezer.value(_players({} if inputs is _EMPTY else inputs))
    freezer.charge(sys.getsizeof(self) + sys.getsizeof(frame_id) + 64)
    for name, value in zip(self._fields, (frame_id, ball, positions, inputs)):
      object.__setattr__(self, name, value)
    object.__setattr__(self, '_bytes', freezer.used)

  def to_dict(self):
    return dict(frame_id=self.frame_id, ball_pos=self.ball_pos,
                player_positions={key: tuple(value) for key, value in self.player_positions.items()},
                inputs=thaw(self.inputs))

  @classmethod
  def from_dict(cls, data):
    if type(data) is not dict or set(data) != {'frame_id', 'ball_pos', 'player_positions', 'inputs'}:
      raise ReplayFormatError('Invalid replay frame fields')
    return cls(**data)
