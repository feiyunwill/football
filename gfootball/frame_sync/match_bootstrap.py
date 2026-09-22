# 2026-09-10: incompatible cadence metadata/Ready gets its own protocol version.
# """Version 4 match origin inside a bounded StateSnapshot wire payload."""
# 2026-09-10: v6 binds control epochs to origin and Ready.
# """Version 5 match origin and cadence inside a bounded StateSnapshot payload."""
"""Version 6 match origin, cadence and pause control in a bounded snapshot."""
from dataclasses import dataclass
import hashlib
import json
import struct

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.match_archive import MAX_SNAPSHOT, engine_digest, parse_settings, settings_data
from gfootball.frame_sync.match_identity import engine_identity, validate_identity
from gfootball.frame_sync.match_cadence import MATCH_CADENCE, parse_cadence
from gfootball.frame_sync.match_control import (
    MatchControl, RUNNING, RESUMING, MAX_EPOCH, parse_control_metadata,
    CONTROL_HEADER, unpack_control,
)
# 2026-09-10: require a validated capability in the explicitly versioned request.
# from gfootball.frame_sync.resume_protocol import ResumeBuffers, ResumeLimits
from gfootball.frame_sync.resume_protocol import ResumeBuffers, ResumeLimits, validate_token
from gfootball.frame_sync.save_data import SaveFormatError

# 2026-09-10: v4 cannot acknowledge an explicit cadence; no silent downgrade.
# MATCH_VERSION = 4
# MAGIC = b'FMATCH4\0'
# 2026-09-10: epoch-tagged input and pause barriers are incompatible with v5.
# MATCH_VERSION = 5
# MAGIC = b'FMATCH5\0'
# 2026-09-13: v7 changes physical cadence and checkpoint identity; no silent v6 fallback.
# MATCH_VERSION = 6
# MAGIC = b'FMATCH6\0'
MATCH_VERSION = 7
MAGIC = b'FMATCH7\0'
HEADER = struct.Struct('<8sI')
MAX_METADATA = 4096
MAX_PAYLOAD = HEADER.size + MAX_METADATA + MAX_SNAPSHOT


# 2026-09-10: confirm the exact control epoch of the restored origin.
# def pack_match_ready():
def pack_match_ready(epoch=0):
  if type(epoch) is not int or not 0 <= epoch <= MAX_EPOCH:
    raise ValueError('Invalid match Ready epoch')
  cadence = MATCH_CADENCE
  # return struct.pack('<BHHHHI', wire.MessageType.MatchReady, MATCH_VERSION,
  #     cadence.input_hz, cadence.network_hz, cadence.physics_steps, cadence.physics_step_us)
  return struct.pack('<BHHHHII', wire.MessageType.MatchReady, MATCH_VERSION,
      cadence.input_hz, cadence.network_hz, cadence.physics_steps, cadence.physics_step_us, epoch)


# 2026-09-10: retain the cadence-only reader API and expose epoch explicitly.
# def unpack_match_ready(packet):
def unpack_match_ready(packet, *, include_epoch=False):
  if type(packet) is not bytes or len(packet) != wire.MATCH_READY_BYTES:
    raise ValueError('Invalid match cadence confirmation')
  # kind, version, input_hz, network_hz, steps, step_us = struct.unpack('<BHHHHI', packet)
  kind, version, input_hz, network_hz, steps, step_us, epoch = struct.unpack('<BHHHHII', packet)
  if kind != wire.MessageType.MatchReady or version != MATCH_VERSION:
    raise ValueError('Invalid match cadence version')
  # return parse_cadence(dict(input_hz=input_hz, network_hz=network_hz,
  #                          physics_steps=steps, physics_step_us=step_us))
  cadence = parse_cadence(dict(input_hz=input_hz, network_hz=network_hz,
                              physics_steps=steps, physics_step_us=step_us))
  return (cadence, epoch) if include_epoch else cadence


def pack_match_reconnect(token):
  return struct.pack('<BHQ', wire.MessageType.MatchReconnectRequest, MATCH_VERSION, validate_token(token))


def unpack_match_reconnect(packet):
  if type(packet) is not bytes or len(packet) != wire.MATCH_RECONNECT_REQUEST_BYTES:
    raise ValueError('Invalid match resume request')
  kind, version, token = struct.unpack('<BHQ', packet)
  if kind != wire.MessageType.MatchReconnectRequest or version != MATCH_VERSION:
    raise ValueError('Invalid match resume version')
  return validate_token(token)


# 2026-09-10: ephemeral control metadata does not alter the physical snapshot.
# def pack_origin(settings, env, maximum=MAX_SNAPSHOT):
def pack_origin(settings, env, maximum=MAX_SNAPSHOT, *, control=None):
  if type(maximum) is not int or not 1 <= maximum <= MAX_SNAPSHOT:
    raise ValueError('Invalid native match snapshot capacity')
  identity = engine_identity(env)
  state = env.get_state('')
  if type(state) is not bytes or not 1 <= len(state) <= maximum:
    raise SaveFormatError('Native match snapshot capacity exceeded')
  # 2026-09-10: verify the simulated-time contract before native construction/restore.
  # metadata = dict(settings=settings_data(settings), identity=identity,
  #                 sha256=hashlib.sha256(state).hexdigest(), digest=engine_digest(env))
  # metadata = dict(settings=settings_data(settings), identity=identity, cadence=MATCH_CADENCE.to_dict(),
  #                 sha256=hashlib.sha256(state).hexdigest(), digest=engine_digest(env))
  digest = engine_digest(env)
  state_hash = struct.unpack('<Q', bytes.fromhex(digest)[:8])[0]
  control = MatchControl(0, RUNNING, 0, state_hash) if control is None else control
  if type(control) is not MatchControl or control.state_hash != state_hash:
    raise SaveFormatError('Match control origin hash mismatch')
  metadata = dict(settings=settings_data(settings), identity=identity, cadence=MATCH_CADENCE.to_dict(),
                  control=control.metadata(), sha256=hashlib.sha256(state).hexdigest(), digest=digest)
  encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
  if not 1 <= len(encoded) <= MAX_METADATA:
    raise SaveFormatError('Match origin metadata capacity exceeded')
  return HEADER.pack(MAGIC, len(encoded)) + encoded + state


def _object(pairs):
  if len(pairs) > 8 or len({key for key, _ in pairs}) != len(pairs):
    raise ValueError('Duplicate or excessive match origin fields')
  return dict(pairs)


def _forbidden_number(_):
  raise ValueError('Match origin has a non-integer number')


# 2026-09-10: transport supplies the outer snapshot frame; preserve four-value callers.
# def unpack_origin(payload, session=None):
def unpack_origin(payload, session=None, *, next_frame=0, include_control=False):
  """Validate full payload before any engine construction or native restore."""
  if type(payload) is not bytes or not HEADER.size < len(payload) <= MAX_PAYLOAD:
    raise ClientFailure('invalid_match_snapshot')
  magic, size = HEADER.unpack_from(payload)
  if magic != MAGIC or not 1 <= size <= MAX_METADATA or not 1 <= len(payload) - HEADER.size - size <= MAX_SNAPSHOT:
    raise ClientFailure('invalid_match_snapshot')
  try:
    metadata = json.loads(payload[HEADER.size:HEADER.size + size].decode('utf-8'),
        object_pairs_hook=_object, parse_float=_forbidden_number, parse_constant=_forbidden_number)
    # 2026-09-10: require all cadence fields; old or extra fields are not guessed.
    # if type(metadata) is not dict or set(metadata) != {'settings', 'identity', 'sha256', 'digest'}:
    # if type(metadata) is not dict or set(metadata) != {'settings', 'identity', 'sha256', 'digest', 'cadence'}:
    if type(metadata) is not dict or set(metadata) != {'settings', 'identity', 'sha256', 'digest', 'cadence', 'control'}:
      raise ValueError('Invalid match origin fields')
    parse_cadence(metadata['cadence'])
    settings = parse_settings(metadata['settings'])
    identity = validate_identity(metadata['identity'])
    for name in ('sha256', 'digest'):
      value = metadata[name]
      if type(value) is not str or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
        raise ValueError('Invalid match origin checksum')
    state_hash = struct.unpack('<Q', bytes.fromhex(metadata['digest'])[:8])[0]
    control = parse_control_metadata(metadata['control'], next_frame, state_hash)
  except (ValueError, TypeError, RecursionError) as error:
    raise ClientFailure('invalid_match_metadata') from error
  if session is not None and session != (settings.game_engine_random_seed, settings.left_agents, settings.right_agents):
    raise ClientFailure('match_session_mismatch')
  state = payload[HEADER.size + size:]
  if hashlib.sha256(state).hexdigest() != metadata['sha256']:
    raise ClientFailure('match_snapshot_checksum')
  # return settings, state, metadata['digest'], identity
  result = settings, state, metadata['digest'], identity
  return result + (control,) if include_control else result


@dataclass(frozen=True)
class MatchResumeLimits(ResumeLimits):
  snapshot_bytes: int = MAX_PAYLOAD

  def __post_init__(self):
    if type(self.snapshot_bytes) is not int or not HEADER.size + 1 <= self.snapshot_bytes <= MAX_PAYLOAD:
      raise ValueError('Invalid match snapshot envelope capacity')


class MatchBuffers(ResumeBuffers):
  # 2026-09-10: transport admission validates the same contract as the logic owner.
  # """Initial v4 session is not ready until its full origin has arrived."""
  # 2026-09-10: bounded control delivery distinguishes received and applied state.
  # """Initial/resumed v5 session requires a validated origin before Ready."""
  """Validated v6 origin and at most a commit plus one unacknowledged barrier."""
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.match_end = None
    self.cadence = None
    self.control = self.applied_control = None
    self.pending_controls = ()

  def fail(self, reason):
    super().fail(reason)
    self.match_end = None
    self.cadence = None
    self.control = self.applied_control = None
    self.pending_controls = ()

  def next_control(self):
    return self.pending_controls[0] if self.pending_controls else self.applied_control

  def consume_control(self, control):
    if not self.pending_controls or self.pending_controls[0] != control:
      raise ClientFailure('unexpected_control_consumption')
    self.applied_control = control
    self.pending_controls = self.pending_controls[1:]

  def _parse(self, now):
    phase = self.phase
    if phase in ('ready', 'streaming') and self.receive and self.receive[0] == wire.MessageType.MatchControl:
      if self.control is None or self.match_end is not None:
        raise ClientFailure('unexpected_match_control')
      if len(self.receive) < CONTROL_HEADER.size:
        return False
      try:
        control = unpack_control(self.receive[:CONTROL_HEADER.size])
        changed = control.validate_after(self.control)
      except ValueError as error:
        raise ClientFailure('invalid_match_control') from error
      # 2026-09-10: an identical commit retransmission may follow later authority.
      # if control.next_frame != self.next_authority:
      if changed and control.next_frame != self.next_authority:
        raise ClientFailure('match_control_frame')
      if changed:
        # Only RUNNING commit + the following PAUSED can coexist without a new
        # ACK. Reject preparations sent before the prior barrier was consumed.
        if self.pending_controls and not (len(self.pending_controls) == 1
            and self.pending_controls[0].phase == RUNNING and control.phase != RUNNING):
          raise ClientFailure('control_before_ack')
        self.pending_controls += (control,)
        self.control = control
      self.receive = self.receive[CONTROL_HEADER.size:]
      return True
    if self.control is not None and self.control.phase != RUNNING and self.receive and self.receive[0] == wire.MessageType.AuthoritativeFrame:
      raise ClientFailure('authority_while_paused')
    if (self.control is not None and self.control.phase != RUNNING and len(self.receive) >= 5
        and self.receive[0] == wire.MessageType.StateHash
        and struct.unpack_from('<I', self.receive, 1)[0] >= self.control.next_frame):
      raise ClientFailure('hash_while_paused')
    if phase in ('ready', 'streaming') and self.receive and self.receive[0] == wire.MessageType.MatchEnd:
      if not self._snapshot_received or self.match_end is not None:
        raise ClientFailure('unexpected_match_end')
      if len(self.receive) < wire.MATCH_END_BYTES:
        return False
      # 2026-09-10: same 64-bit hash width as StateHash.
      # frame, digest = struct.unpack_from('<II', self.receive, 1)
      frame, digest = struct.unpack_from('<IQ', self.receive, 1)
      if frame != self.next_authority:
        raise ClientFailure('match_end_frame')
      self.match_end = frame, digest
      self.receive = self.receive[wire.MATCH_END_BYTES:]
      return True
    if self.match_end is not None and self.receive and self.receive[0] in (
        wire.MessageType.AuthoritativeFrame, wire.MessageType.StateHash):
      raise ClientFailure('authority_after_match_end')
    if phase == 'snapshot_header' and not self.restoring and len(self.receive) >= 9:
      if struct.unpack_from('<I', self.receive, 1)[0] != 0:
        raise ClientFailure('initial_match_frame')
    parsed = super()._parse(now)
    if parsed and phase == 'snapshot_body' and self.phase == 'ready':
      # 2026-09-10: validate control before exposing Ready, using the outer frame.
      # unpack_origin(self.snapshot[1], self.session)
      decoded = unpack_origin(self.snapshot[1], self.session, next_frame=self.snapshot[0], include_control=True)
      self.control = self.applied_control = decoded[4]
      self.cadence = MATCH_CADENCE
    if parsed and phase == 'token':
      self.phase, self.ready_since = 'snapshot_header', None
    return parsed
