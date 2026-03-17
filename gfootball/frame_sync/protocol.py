# Copyright 2019 Google LLC
# Python binary protocol for frame sync (matches third_party/gfootball_engine/src/frame_sync/protocol.hpp).

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import hashlib
import struct
from collections import namedtuple

# Match C++: 2 floats + uint16 = 10 bytes (no padding)
SLOT_INPUT_FMT = '<ffH'
SLOT_INPUT_BYTES = struct.calcsize(SLOT_INPUT_FMT)

FRAME_INPUT_TIMEOUT_MS = 200

# Prediction cap (tunable): max frames ahead of last confirmed; beyond this, wait for authority.
MAX_PREDICT_AHEAD_FRAMES = 3
# If no server packet for this many consecutive frames, stop predicting and wait for authority only.
MAX_FRAMES_WITHOUT_PACKET = 5
# State hash every K frames (server sends, client verifies).
STATE_HASH_INTERVAL_K = 10

SlotInput = namedtuple('SlotInput', ['dir_x', 'dir_y', 'buttons'])


def default_slot_input():
  return SlotInput(0.0, 0.0, 0)


class MessageType:
  Connect = 0
  Disconnect = 1
  FrameInput = 2
  AuthoritativeFrame = 3
  StateHash = 4
  SessionStart = 5
  Ready = 6
  SlotAssignment = 7  # server -> client: which slot indices this client controls


def pack_slot_input(slot_input):
  return struct.pack(
      SLOT_INPUT_FMT,
      slot_input.dir_x,
      slot_input.dir_y,
      slot_input.buttons & 0xFFFF,
  )


def unpack_slot_input(data, offset=0):
  if offset + SLOT_INPUT_BYTES > len(data):
    raise ValueError('Not enough data for SlotInput')
  t = struct.unpack_from(SLOT_INPUT_FMT, data, offset)
  return SlotInput(t[0], t[1], t[2]), offset + SLOT_INPUT_BYTES


# AuthoritativeFrame: msg_type(1) + frame_id(4) + num_slots(2) + slot_inputs
AUTH_FRAME_HEADER_FMT = '<BIH'
AUTH_FRAME_HEADER_BYTES = struct.calcsize(AUTH_FRAME_HEADER_FMT)


def pack_authoritative_frame(frame_id, slot_inputs):
  buf = bytearray()
  buf.append(MessageType.AuthoritativeFrame)
  buf.extend(struct.pack('<I', frame_id))
  buf.extend(struct.pack('<H', len(slot_inputs)))
  for s in slot_inputs:
    buf.extend(pack_slot_input(s))
  return bytes(buf)


def unpack_authoritative_frame(data):
  if len(data) < 1 + 4 + 2:
    raise ValueError('AuthoritativeFrame too short')
  msg_type = data[0]
  if msg_type != MessageType.AuthoritativeFrame:
    raise ValueError('Not AuthoritativeFrame')
  frame_id = struct.unpack_from('<I', data, 1)[0]
  num_slots = struct.unpack_from('<H', data, 5)[0]
  offset = 7
  slot_inputs = []
  for _ in range(num_slots):
    s, offset = unpack_slot_input(data, offset)
    slot_inputs.append(s)
  return frame_id, slot_inputs


# Client FrameInput: msg_type(1) + frame_id(4) + num_slots(2) + per slot: slot_index(2) + SlotInput
def pack_client_frame_input(frame_id, slot_entries):
  """slot_entries: list of (slot_index, SlotInput)."""
  buf = bytearray()
  buf.append(MessageType.FrameInput)
  buf.extend(struct.pack('<I', frame_id))
  buf.extend(struct.pack('<H', len(slot_entries)))
  for slot_index, slot_input in slot_entries:
    buf.extend(struct.pack('<H', slot_index & 0xFFFF))
    buf.extend(pack_slot_input(slot_input))
  return bytes(buf)


def unpack_client_frame_input(data):
  if len(data) < 1 + 4 + 2:
    raise ValueError('Client FrameInput too short')
  msg_type = data[0]
  if msg_type != MessageType.FrameInput:
    raise ValueError('Not FrameInput')
  frame_id = struct.unpack_from('<I', data, 1)[0]
  num_slots = struct.unpack_from('<H', data, 5)[0]
  offset = 7
  entries = []
  for _ in range(num_slots):
    if offset + 2 + SLOT_INPUT_BYTES > len(data):
      raise ValueError('Truncated FrameInput')
    slot_index = struct.unpack_from('<H', data, offset)[0]
    offset += 2
    s, offset = unpack_slot_input(data, offset)
    entries.append((slot_index, s))
  return frame_id, entries


# SessionStart: msg_type(1) + game_engine_random_seed(4) + left_agents(2) + right_agents(2)
SESSION_START_PAYLOAD_FMT = '<IHH'  # seed, left_agents, right_agents
SESSION_START_PAYLOAD_BYTES = struct.calcsize(SESSION_START_PAYLOAD_FMT)


def pack_session_start(seed, left_agents, right_agents):
  buf = bytearray()
  buf.append(MessageType.SessionStart)
  buf.extend(struct.pack(SESSION_START_PAYLOAD_FMT, seed, left_agents, right_agents))
  return bytes(buf)


def unpack_session_start(data):
  if len(data) < 1 + SESSION_START_PAYLOAD_BYTES:
    raise ValueError('SessionStart too short')
  if data[0] != MessageType.SessionStart:
    raise ValueError('Not SessionStart')
  seed, left_agents, right_agents = struct.unpack_from(
      SESSION_START_PAYLOAD_FMT, data, 1
  )
  return seed, left_agents, right_agents


# Ready: msg_type(1) only
def pack_ready():
  return bytes([MessageType.Ready])


# SlotAssignment: msg_type(1) + num_slots(2) + slot_index(2) each
def pack_slot_assignment(slot_indices):
  buf = bytearray()
  buf.append(MessageType.SlotAssignment)
  buf.extend(struct.pack('<H', len(slot_indices)))
  for idx in slot_indices:
    buf.extend(struct.pack('<H', idx & 0xFFFF))
  return bytes(buf)


def unpack_slot_assignment(data):
  if len(data) < 1 + 2:
    raise ValueError('SlotAssignment too short')
  if data[0] != MessageType.SlotAssignment:
    raise ValueError('Not SlotAssignment')
  num = struct.unpack_from('<H', data, 1)[0]
  if len(data) < 1 + 2 + num * 2:
    raise ValueError('SlotAssignment truncated')
  slots = []
  for i in range(num):
    slots.append(struct.unpack_from('<H', data, 3 + i * 2)[0])
  return slots


# StateHash (task 5.3): msg_type(1) + frame_id(4) + hash(8)
STATE_HASH_BYTES = 1 + 4 + 8


def pack_state_hash(frame_id, state_hash_64):
  buf = bytearray()
  buf.append(MessageType.StateHash)
  buf.extend(struct.pack('<I', frame_id))
  buf.extend(struct.pack('<Q', state_hash_64))
  return bytes(buf)


def unpack_state_hash(data):
  if len(data) < STATE_HASH_BYTES:
    raise ValueError('StateHash too short')
  if data[0] != MessageType.StateHash:
    raise ValueError('Not StateHash')
  frame_id = struct.unpack_from('<I', data, 1)[0]
  state_hash_64 = struct.unpack_from('<Q', data, 5)[0]
  return frame_id, state_hash_64


def compute_state_hash(state_str):
  """64-bit hash of state string for optional verification."""
  h = hashlib.sha256(state_str if isinstance(state_str, bytes) else state_str.encode())
  return struct.unpack_from('<Q', h.digest(), 0)[0]
