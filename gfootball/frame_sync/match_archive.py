"""Actual match snapshots, authoritative input recordings and verified playback.

All engine calls are synchronous on the caller's engine owner. Files use the
existing bounded save/replay stores; no pickle, detached worker or unbounded
input history is introduced. The supplied engine factory defaults to GameEnv.
"""
import base64
import hashlib
import math
import os
import threading
import uuid

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.replay_data import ReplayEvent, ReplayEventType, ReplayFrame, ReplayFormatError
from gfootball.frame_sync.replay_store import Replay, ReplayManager
from gfootball.frame_sync.save_data import SaveLimits, SaveSlot, SaveType, SaveFormatError
from gfootball.frame_sync.save_runtime import SaveManager
# 2026-09-10: Persisted native state requires explicit build/content compatibility.
# from gfootball.frame_sync.server_runtime import ServerSettings, native_engine
# 2026-09-13: archives validate cadence before constructing an engine.
# from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.match_cadence import MATCH_CADENCE, parse_cadence
from gfootball.frame_sync.match_identity import (
    engine_identity, require_identity, validate_identity, native_match_engine as native_engine,
)

MAX_SNAPSHOT = 1024 * 1024
CHUNK_BYTES = 24576
MAX_CHUNKS = (MAX_SNAPSHOT + CHUNK_BYTES - 1) // CHUNK_BYTES
SAVE_LIMITS = SaveLimits(slots=1, slot_bytes=2 * 1024 * 1024, total_bytes=2 * 1024 * 1024)


def engine_digest(env):
  data = env.get_state_digest()
  if type(data) is str:
    if len(data) > MAX_SNAPSHOT:
      raise SaveFormatError('Engine digest capacity exceeded')
    data = data.encode('utf-8')
  if type(data) is not bytes or not 1 <= len(data) <= MAX_SNAPSHOT:
    raise SaveFormatError('Invalid engine digest')
  return hashlib.sha256(data).hexdigest()


def settings_data(settings):
  if type(settings) is not ServerSettings:
    raise SaveFormatError('Expected match settings')
  return dict(scenario=settings.scenario_name, left=settings.left_agents,
              right=settings.right_agents, seed=settings.game_engine_random_seed)


def parse_settings(data):
  if type(data) is not dict or set(data) != {'scenario', 'left', 'right', 'seed'}:
    raise SaveFormatError('Invalid saved match settings')
  return ServerSettings(scenario_name=data['scenario'], left_agents=data['left'],
                        right_agents=data['right'], game_engine_random_seed=data['seed'])


def _hex(value, size=64):
  if type(value) is not str or len(value) != size or any(c not in '0123456789abcdef' for c in value):
    raise SaveFormatError('Invalid match checksum')
  return value


def capture(settings, env):
  # 2026-09-10: Capture identity before reading native snapshot state.
  # state = env.get_state('')
  identity = engine_identity(env)
  state = env.get_state('')
  if type(state) is not bytes or not 1 <= len(state) <= MAX_SNAPSHOT:
    raise SaveFormatError('Native match snapshot must be 1..1048576 bytes')
  # 2026-09-10: Version 2 carries the required compatibility identity.
  # return dict(format='football.match_checkpoint', version=1, settings=settings_data(settings),
  # 2026-09-13: checkpoint v3 carries an explicit physical time contract.
  # return dict(format='football.match_checkpoint', version=2, identity=identity, settings=settings_data(settings),
  return dict(format='football.match_checkpoint', version=3, identity=identity, settings=settings_data(settings),
      cadence=MATCH_CADENCE.to_dict(),
      size=len(state), sha256=hashlib.sha256(state).hexdigest(), digest=engine_digest(env),
      chunks=[base64.b64encode(state[offset:offset + CHUNK_BYTES]).decode('ascii')
              for offset in range(0, len(state), CHUNK_BYTES)])


def decode_checkpoint(data):
  # 2026-09-10: Do not trial-deserialize legacy snapshots without identity.
  # if type(data) is not dict or set(data) != {'format', 'version', 'settings', 'size', 'sha256', 'digest', 'chunks'}:
  if type(data) is dict and data.get('version') == 1:
    raise SaveFormatError('Checkpoint version 1 has no compatibility identity; automatic restore is unavailable')
  # 2026-09-13: reject identity-only archives before allocating snapshot bytes.
  # if type(data) is not dict or set(data) != {'format', 'version', 'settings', 'size', 'sha256', 'digest', 'chunks', 'identity'}:
  if type(data) is dict and data.get('version') == 2:
    raise SaveFormatError('Checkpoint version 2 has no cadence; automatic restore is unavailable')
  if type(data) is not dict or set(data) != {'format', 'version', 'settings', 'size', 'sha256', 'digest', 'chunks', 'identity', 'cadence'}:
    raise SaveFormatError('Invalid match checkpoint fields')
  # 2026-09-10: Require the versioned compatibility contract.
  # if data['format'] != 'football.match_checkpoint' or type(data['version']) is not int or data['version'] != 1:
  # 2026-09-13: require the cadence-bearing checkpoint version.
  # if data['format'] != 'football.match_checkpoint' or type(data['version']) is not int or data['version'] != 2:
  if data['format'] != 'football.match_checkpoint' or type(data['version']) is not int or data['version'] != 3:
    raise SaveFormatError('Unsupported match checkpoint')
  # 2026-09-10: Validate bounded metadata before allocating snapshot bytes.
  # settings = parse_settings(data['settings'])
  # 2026-09-13: cadence mismatch fails before any engine or snapshot deserialization.
  # identity = validate_identity(data['identity'])
  try:
    parse_cadence(data['cadence'])
  except ValueError as error:
    raise SaveFormatError('Unsupported checkpoint cadence') from error
  identity = validate_identity(data['identity'])
  settings = parse_settings(data['settings'])
  size = data['size']
  if type(size) is not int or not 1 <= size <= MAX_SNAPSHOT:
    raise SaveFormatError('Invalid match snapshot size')
  _hex(data['sha256'])
  _hex(data['digest'])
  chunks = data['chunks']
  if type(chunks) is not list or len(chunks) != (size + CHUNK_BYTES - 1) // CHUNK_BYTES:
    raise SaveFormatError('Invalid match snapshot chunk count')
  # Validate every encoded length before allocating the bounded native result.
  for index, chunk in enumerate(chunks):
    expected = min(CHUNK_BYTES, size - index * CHUNK_BYTES)
    if type(chunk) is not str or len(chunk) != 4 * ((expected + 2) // 3):
      raise SaveFormatError('Invalid match snapshot chunk length')
  result = bytearray(size)
  for index, chunk in enumerate(chunks):
    try:
      value = base64.b64decode(chunk, validate=True)
    except (ValueError, UnicodeError) as error:
      raise SaveFormatError('Invalid match snapshot encoding') from error
    expected = min(CHUNK_BYTES, size - index * CHUNK_BYTES)
    if len(value) != expected or base64.b64encode(value).decode('ascii') != chunk:
      raise SaveFormatError('Noncanonical match snapshot encoding')
    result[index * CHUNK_BYTES:index * CHUNK_BYTES + expected] = value
  if hashlib.sha256(result).hexdigest() != data['sha256']:
    raise SaveFormatError('Match snapshot checksum mismatch')
  # 2026-09-10: Pass validated identity to every restoration boundary.
  # return settings, bytes(result), data['digest']
  return settings, bytes(result), data['digest'], identity


def write_checkpoint(path, checkpoint):
  decode_checkpoint(checkpoint)
  slot = SaveSlot('match', 'Local match', SaveType.CUSTOM, checkpoint, limits=SAVE_LIMITS)
  with SaveManager(path=path, limits=SAVE_LIMITS) as manager:
    old = manager.list_slots()
    if old:
      if len(old) != 1 or old[0].slot_id != 'match':
        raise SaveFormatError('The destination is a different save collection')
      decode_checkpoint(old[0].data)
    # One complete slot publication, including first creation: no empty-slot
    # intermediate commit can replace a usable checkpoint.
    if manager.import_slot(slot.export_bytes().decode('utf-8')) is None:
      raise SaveFormatError('Checkpoint could not be admitted')


def read_checkpoint(path):
  with SaveManager(path=path, limits=SAVE_LIMITS) as manager:
    slots = manager.list_slots()
    if len(slots) != 1 or slots[0].slot_id != 'match':
      raise SaveFormatError('Match checkpoint does not exist')
    data = slots[0].data
    decode_checkpoint(data)
    return data


def positions(env):
  info = env.get_info()
  def position(value):
    result = tuple(float(value[i]) for i in range(3))
    if not all(math.isfinite(item) and abs(item) <= 1000000 for item in result):
      raise ReplayFormatError('Invalid engine position')
    return result
  players = {}
  for side, team in (('left', info.left_team), ('right', info.right_team)):
    if not 0 <= len(team) <= 11:
      raise ReplayFormatError('Engine team size exceeded')
    for index in range(len(team)):
      players[side + ':' + str(index)] = position(team[index].position)
  scores = info.left_goals, info.right_goals
  if any(type(value) is not int or not 0 <= value <= 999 for value in scores):
    raise ReplayFormatError('Invalid engine score')
  return position(info.ball_position), players, scores


def input_bytes(value):
  if (type(value) is not wire.SlotInput or type(value.buttons) is not int
      or any(type(item) not in (int, float) for item in (value.dir_x, value.dir_y))
      or not wire.is_valid_slot_input(value)):
    raise ReplayFormatError('Invalid recorded slot input')
  return wire.pack_slot_input(value)


class MatchRecorder:
  """One bounded in-memory replay; finish before transferring it to file I/O."""
  def __init__(self, settings, env, *, limits=None):
    self._owner, self._pid = threading.current_thread(), os.getpid()
    self.manager = ReplayManager(limits=limits)
    self.frames, self.closed = 0, False
    self.slots = settings.left_agents + settings.right_agents
    try:
      # 2026-09-10: Retain only bounded origin identity for final compatibility check.
      # checkpoint = capture(settings, env)
      checkpoint = capture(settings, env)
      self._identity = checkpoint['identity']
      identity = uuid.uuid4().hex
      # 2026-09-13: record time units in the existing replay header.
      # self.replay = self.manager.start_recording(identity, identity, 'Home', 'Away')
      self.replay = self.manager.start_recording(identity, identity, 'Home', 'Away',
                                                  tick_hz=MATCH_CADENCE.network_hz)
      self.manager.set_score(*positions(env)[2])
      metadata = {key: value for key, value in checkpoint.items() if key != 'chunks'}
      metadata['chunk_count'] = len(checkpoint['chunks'])
      self.manager.record_event(ReplayEvent(ReplayEventType.MATCH_START, 0, 0, details=metadata))
      for index, chunk in enumerate(checkpoint['chunks']):
        self.manager.record_event(ReplayEvent(ReplayEventType.STATE_SNAPSHOT, 0, 0,
            details=dict(index=index, parts=[chunk[start:start + 4096] for start in range(0, len(chunk), 4096)])))
    except BaseException:
      self.manager.close()
      raise

  def _check(self):
    if self._pid != os.getpid() or threading.current_thread() is not self._owner:
      raise RuntimeError('Match recording must stay on its engine owner')
    if self.closed:
      raise RuntimeError('Match recording is closed')

  def record(self, frame, inputs, env):
    self._check()
    if type(frame) is not int or frame != self.frames or type(inputs) not in (list, tuple) or len(inputs) != self.slots:
      raise ReplayFormatError('Match recording requires consecutive complete authority')
    # Wire round-trip validates the same float32 values that actually stepped.
    values = [wire.unpack_slot_input(input_bytes(value))[0] for value in inputs]
    ball, players, scores = positions(env)
    row = ReplayFrame(frame, ball, players, {str(i): dict(dir_x=value.dir_x, dir_y=value.dir_y, buttons=value.buttons)
                                           for i, value in enumerate(values)})
    self.manager.record_frame(row)
    self.manager.set_score(*scores)
    self.frames += 1

  def finish(self, env):
    # 2026-09-10: Do not publish a replay after its runtime resources change.
    # self._check()
    # self.manager.record_event(ReplayEvent(ReplayEventType.MATCH_END
    self._check()
    require_identity(env, self._identity)
    # 2026-09-13: terminal timestamp follows actual match frame duration.
    # self.manager.record_event(ReplayEvent(ReplayEventType.MATCH_END, self.frames * 100, self.frames,
    self.manager.record_event(ReplayEvent(ReplayEventType.MATCH_END, self.frames * MATCH_CADENCE.frame_ms, self.frames,
                                          details=dict(next_frame=self.frames, digest=engine_digest(env))))
    replay = self.manager.stop_recording()
    self.closed = True
    return replay

  def close(self):
    # Finalization seals data but does not prevent explicit resource release.
    if self._pid != os.getpid() or threading.current_thread() is not self._owner:
      raise RuntimeError('Match recording must stay on its engine owner')
    self.manager.close()
    self.closed = True


# 2026-09-10: allow presentation of a verified origin including zero-frame replay.
# def playback(path, *, engine_factory=None, limits=None, on_frame=None):
def playback(path, *, engine_factory=None, limits=None, on_frame=None, on_start=None):
  """Verify the whole file and origin before allocating an engine, then replay.

Every frame verifies native ball/player positions. The terminal canonical state
digest and score must also match. No native engine is replaced on import failure.
"""
  # 2026-09-10: validate both playback hooks before loading files.
  # if on_frame is not None and not callable(on_frame):
  #   raise ValueError('Expected a playback callback')
  if any(hook is not None and not callable(hook) for hook in (on_frame, on_start)):
    raise ValueError('Expected a playback callback')
  replay = Replay.load(path, limits=limits)
  # 2026-09-13: reject mismatched replay cadence before allocating an engine.
  # if replay.tick_hz != 10:
  #   raise ReplayFormatError('Recorded match requires the 10 Hz engine cadence')
  if replay.tick_hz != MATCH_CADENCE.network_hz:
    raise ReplayFormatError('Recorded match requires the 50 Hz engine cadence')
  events = replay.events
  if not 3 <= len(events) <= MAX_CHUNKS + 2 or events[0].event_type is not ReplayEventType.MATCH_START:
    raise ReplayFormatError('Replay has no complete native match origin')
  metadata = events[0].to_dict()['details']
  chunk_count = metadata.pop('chunk_count', None)
  if type(chunk_count) is not int or not 1 <= chunk_count <= MAX_CHUNKS or len(events) != chunk_count + 2:
    raise ReplayFormatError('Invalid origin snapshot event count')
  chunks = []
  for index, event in enumerate(events[1:-1]):
    details = event.to_dict()['details']
    if (event.event_type is not ReplayEventType.STATE_SNAPSHOT or event.frame_id != 0 or event.timestamp_ms != 0
        or set(details) != {'index', 'parts'} or type(details['index']) is not int or details['index'] != index
        or type(details['parts']) is not list or not 1 <= len(details['parts']) <= 8
        or any(type(part) is not str or not 1 <= len(part) <= 4096 for part in details['parts'])):
      raise ReplayFormatError('Invalid origin snapshot event')
    chunks.append(''.join(details['parts']))
  metadata['chunks'] = chunks
  # 2026-09-10: Carry origin identity through verified playback.
  # settings, snapshot, initial_digest = decode_checkpoint(metadata)
  settings, snapshot, initial_digest, identity = decode_checkpoint(metadata)
  end = events[-1]
  ending = end.to_dict()['details']
  count = replay.stats()['frames']
  # 2026-09-13: verify v7 terminal time instead of assuming 100 ms frames.
  # if (end.event_type is not ReplayEventType.MATCH_END or end.frame_id != count or end.timestamp_ms != count * 100
  if (end.event_type is not ReplayEventType.MATCH_END or end.frame_id != count or end.timestamp_ms != count * MATCH_CADENCE.frame_ms
      or set(ending) != {'next_frame', 'digest'} or type(ending['next_frame']) is not int or ending['next_frame'] != count):
    raise ReplayFormatError('Invalid terminal match state')
  _hex(ending['digest'])
  factory = engine_factory or native_engine
  env = factory(settings)
  try:
    # 2026-09-10: Reject incompatible snapshots BEFORE native deserialization.
    # env.set_state(snapshot)
    require_identity(env, identity)
    env.set_state(snapshot)
    del snapshot, chunks, metadata
    if engine_digest(env) != initial_digest:
      raise ReplayFormatError('Restored match origin differs')
    if on_start is not None:
      on_start(settings, env)
    for expected, frame in enumerate(replay.cursor()):
      if frame.frame_id != expected or set(frame.inputs) != {str(i) for i in range(settings.left_agents + settings.right_agents)}:
        raise ReplayFormatError('Invalid recorded authority frame')
      packed = []
      for index in range(settings.left_agents + settings.right_agents):
        value = frame.inputs[str(index)]
        if set(value) != {'dir_x', 'dir_y', 'buttons'}:
          raise ReplayFormatError('Invalid recorded input fields')
        packed.append(input_bytes(wire.SlotInput(**value)))
      env.step_with_input(b''.join(packed))
      ball, players, scores = positions(env)
      if ball != frame.ball_pos or players != dict(frame.player_positions):
        raise ReplayFormatError('Replay positions diverged at frame ' + str(expected))
      if on_frame is not None:
        on_frame(expected, env)
    if engine_digest(env) != ending['digest']:
      raise ReplayFormatError('Replay terminal state diverged')
    _, _, scores = positions(env)
    if scores != (replay.score_home, replay.score_away):
      raise ReplayFormatError('Replay score diverged')
    return dict(frames=count, digest=ending['digest'], score=scores, verified=True)
  finally:
    env.close()
