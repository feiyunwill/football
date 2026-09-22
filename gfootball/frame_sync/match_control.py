# 2026-09-10: actual match transports now negotiate these v6 controls.
# The running version-5 match handshake does not enable these messages. A v6
# transport must negotiate the version, serialize control barriers with authority,
# and reject old input epochs before using the existing frame-input window.
"""Version-6 pause boundaries and epoch-tagged input; no transport ownership.

MatchServerRuntime and MatchClientProtocol serialize these controls with their
authoritative stream. Generic v2/v3 clients and native protocol peers do not
acquire match-v6 capabilities by importing the message constants.
"""
from dataclasses import dataclass
import struct

from gfootball.frame_sync import protocol as wire

CONTROL_VERSION = 6
MAX_EPOCH = 0xffffffff
MAX_FRAME = 0xfffffff7
RUNNING, PAUSED, RESUMING = 0, 1, 2
CONTROL_KIND, ACK_KIND, INPUT_KIND = 19, 20, 21
CONTROL_HEADER = struct.Struct('<BIBIQ')
ACK_HEADER = struct.Struct('<BIIQ')
INPUT_HEADER = struct.Struct('<BIIH')


def _integer(value, maximum, name):
  if type(value) is not int or not 0 <= value <= maximum:
    raise ValueError('Invalid match control ' + name)
  return value


@dataclass(frozen=True)
class MatchControl:
  epoch: int
  phase: int
  next_frame: int
  state_hash: int

  def __post_init__(self):
    _integer(self.epoch, MAX_EPOCH, 'epoch')
    _integer(self.phase, RESUMING, 'phase')
    _integer(self.next_frame, MAX_FRAME, 'frame')
    _integer(self.state_hash, 0xffffffffffffffff, 'hash')
    if self.epoch == 0 and self.phase != RUNNING:
      raise ValueError('Initial match control must be running')

  def validate_after(self, previous):
    """Accept retransmission, pause, prepare-resume and its same-epoch commit."""
    if type(previous) is not MatchControl:
      raise ValueError('Expected a previous match control state')
    if self == previous:
      return False
    same_boundary = (self.next_frame, self.state_hash) == (previous.next_frame, previous.state_hash)
    if self.epoch == previous.epoch:
      if previous.phase == RESUMING and self.phase == RUNNING and same_boundary:
        return True
      raise ValueError('Conflicting match control epoch')
    if self.epoch != previous.epoch + 1:
      raise ValueError('Out-of-order match control epoch')
    if previous.phase == RUNNING and self.phase == PAUSED and self.next_frame >= previous.next_frame:
      return True
    if previous.phase == PAUSED and self.phase == RESUMING and same_boundary:
      return True
    raise ValueError('Invalid match control transition')

  def metadata(self):
    return dict(epoch=self.epoch, phase=self.phase)


def parse_control_metadata(metadata, next_frame, state_hash):
  if type(metadata) is not dict or set(metadata) != {'epoch', 'phase'}:
    raise ValueError('Invalid match control metadata')
  return MatchControl(metadata['epoch'], metadata['phase'], next_frame, state_hash)


def pack_control(control):
  if type(control) is not MatchControl:
    raise ValueError('Expected MatchControl')
  return CONTROL_HEADER.pack(CONTROL_KIND, control.epoch, control.phase,
                             control.next_frame, control.state_hash)


def unpack_control(packet):
  if type(packet) is not bytes or len(packet) != CONTROL_HEADER.size:
    raise ValueError('Invalid match control packet size')
  kind, epoch, phase, frame, digest = CONTROL_HEADER.unpack(packet)
  if kind != CONTROL_KIND:
    raise ValueError('Invalid match control packet type')
  return MatchControl(epoch, phase, frame, digest)


def pack_control_ack(control):
  if type(control) is not MatchControl or control.phase == RUNNING:
    raise ValueError('Only pause/resume preparation can be acknowledged')
  return ACK_HEADER.pack(ACK_KIND, control.epoch, control.next_frame, control.state_hash)


def unpack_control_ack(packet):
  if type(packet) is not bytes or len(packet) != ACK_HEADER.size:
    raise ValueError('Invalid match control acknowledgement size')
  kind, epoch, frame, digest = ACK_HEADER.unpack(packet)
  if kind != ACK_KIND or epoch == 0:
    raise ValueError('Invalid match control acknowledgement')
  _integer(frame, MAX_FRAME, 'frame')
  return epoch, frame, digest


def pack_epoch_input(epoch, frame, entries):
  _integer(epoch, MAX_EPOCH, 'epoch')
  _integer(frame, MAX_FRAME, 'frame')
  if type(entries) not in (tuple, list) or not 1 <= len(entries) <= 22:
    raise ValueError('Expected bounded epoch input entries')
  seen = set()
  for entry in entries:
    if type(entry) not in (tuple, list) or len(entry) != 2:
      raise ValueError('Invalid epoch input entry')
    slot, value = entry
    _integer(slot, 21, 'slot')
    if slot in seen:
      raise ValueError('Duplicate epoch input slot')
    seen.add(slot)
    if (type(value) is not wire.SlotInput or type(value.buttons) is not int
        or type(value.dir_x) not in (int, float) or type(value.dir_y) not in (int, float)
        or not wire.is_valid_slot_input(value)):
      raise ValueError('Invalid epoch input value')
  ordinary = wire.pack_client_frame_input(frame, entries)
  return struct.pack('<BI', INPUT_KIND, epoch) + ordinary[1:]


def unpack_epoch_input(packet, num_slots=22):
  _integer(num_slots, 22, 'slot count')
  if not num_slots or type(packet) is not bytes or len(packet) < INPUT_HEADER.size:
    raise ValueError('Invalid epoch input packet')
  kind, epoch, frame, count = INPUT_HEADER.unpack_from(packet)
  if (kind != INPUT_KIND or not 1 <= count <= num_slots
      or len(packet) != INPUT_HEADER.size + count * (2 + wire.SLOT_INPUT_BYTES)):
    raise ValueError('Invalid epoch input packet shape')
  _integer(frame, MAX_FRAME, 'frame')
  # The existing frame window still validates each value, ownership, duplicates
  # and capacity. Do not silently mask the slot index or action bits here.
  return epoch, bytes((wire.MessageType.FrameInput,)) + packet[5:]
