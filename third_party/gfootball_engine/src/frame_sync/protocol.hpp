// Copyright 2019 Google LLC & Contributors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef GFOOTBALL_FRAME_SYNC_PROTOCOL_HPP
#define GFOOTBALL_FRAME_SYNC_PROTOCOL_HPP

#include <cstdint>
#include <cstddef>

namespace frame_sync {

// ----- Message types (for transport layer framing) -----
enum class MessageType : uint8_t {
  Connect = 0,           // client -> server: join, report controlled slots
  Disconnect = 1,        // either direction: connection closed
  FrameInput = 2,        // client -> server: this frame's input for my slot(s)
  AuthoritativeFrame = 3, // server -> client: frame_id + full frame input for all slots
  StateHash = 4,         // optional: server -> client, per K frames for verification
  SessionStart = 5,      // server -> client: scenario params, seed, left_agents, right_agents
  Ready = 6,             // client -> server: ready after SessionStart applied
  SlotAssignment = 7,    // server -> client: which slot indices this client controls
};

// ----- Frame semantics -----
// One network frame = one env step = physics_steps_per_frame (default 10) ProcessPhase() ticks.
// Frame IDs start at 0 after SessionStart; increment by 1 per env step.
// Timeout: server waits for all clients' FrameInput for frame N up to FRAME_INPUT_TIMEOUT_MS.
// Default input: if a client does not send in time, use SlotInput::Default() (zero direction, no buttons).
// 常量与 gfootball/frame_sync/schema/constants.yaml 保持一致（单一来源）；修改 YAML 后请同步此处。
constexpr int FRAME_INPUT_TIMEOUT_MS = 200;

// ----- Prediction cap (tunable) -----
// Max frames client may run ahead of last confirmed authoritative frame; beyond this, wait.
constexpr int MAX_PREDICT_AHEAD_FRAMES = 3;
// If no server packet received for this many consecutive frames, stop predicting and wait for authority.
constexpr int MAX_FRAMES_WITHOUT_PACKET = 5;
// State hash every K frames for verification (server sends, client compares).
constexpr int STATE_HASH_INTERVAL_K = 10;

// ----- Per-slot input: full action (direction + button bitmask; order matches SetControllerSetup) -----
// Direction: 2D in plane (x, y), normalized or zero. Stored as two floats.
// Buttons: bitmask of e_ButtonFunction (0..e_ButtonFunction_Size-1). Bit i = 1 means button i pressed.
constexpr int BUTTON_COUNT = 12;  // e_ButtonFunction_Size

struct SlotInput {
  float dir_x = 0.f;
  float dir_y = 0.f;
  uint16_t buttons = 0;  // bitmask for e_ButtonFunction

  static SlotInput Default() {
    SlotInput s;
    return s;
  }

  bool operator==(const SlotInput& o) const {
    return dir_x == o.dir_x && dir_y == o.dir_y && buttons == o.buttons;
  }
};

constexpr size_t SLOT_INPUT_BYTES = sizeof(SlotInput);

// ----- Authoritative frame packet (server -> client) -----
// Layout: message_type (1) + frame_id (4) + num_slots (2) + slot_inputs (num_slots * SLOT_INPUT_BYTES)
// Optional trailer: state_hash (4 or 8 bytes) if MessageType has hash.
using frame_id_t = uint32_t;
using state_hash_t = uint64_t;

constexpr size_t AUTHORITATIVE_FRAME_HEADER_BYTES = 1 + sizeof(frame_id_t) + sizeof(uint16_t);

// ----- Client frame input (client -> server) -----
// Layout: message_type (1) + frame_id (4) + num_my_slots (2) + slot_index (2) per slot + slot_inputs
// For simplicity: client sends one FrameInput per frame with all slots they control (slot indices + inputs).
struct ClientFrameInputHeader {
  frame_id_t frame_id;
  uint16_t num_slots;  // number of (slot_index, SlotInput) pairs following
};
constexpr size_t CLIENT_FRAME_INPUT_HEADER_BYTES = 1 + sizeof(ClientFrameInputHeader);
// Per reported slot: slot_index (2 bytes) + SlotInput
constexpr size_t CLIENT_SLOT_ENTRY_BYTES = sizeof(uint16_t) + SLOT_INPUT_BYTES;

// ----- Session start (server -> client) -----
// Params needed for setConfig + reset: left_agents, right_agents, game_engine_random_seed,
// and optionally a serialized ScenarioConfig or config id. Minimal: seed (4) + left_agents (2) + right_agents (2).
struct SessionStartParams {
  uint32_t game_engine_random_seed = 42;
  uint16_t left_agents = 1;
  uint16_t right_agents = 0;
};
constexpr size_t SESSION_START_PARAMS_BYTES = sizeof(SessionStartParams);

}  // namespace frame_sync

#endif
