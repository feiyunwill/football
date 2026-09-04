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
#include <cmath>
#include <bit>
#include <functional>

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
  Heartbeat = 8,         // 2026-08-28 双向心跳：周期性保活包，载荷 frame_id(4B) + timestamp(4B)
  VersionNegotiate = 9,  // 2026-08-28 版本协商：客户端→服务器，载荷 protocol_version(2B) + min_version(2B)
  // 2026-09-01 断线托管协议扩展
  TakeoverNotify = 10,   // server -> client: slot 被 AI 接管，载荷 slot_index(2) + frame_id(4)
  HandbackNotify = 11,   // server -> client: 控制权归还，载荷 slot_index(2) + frame_id(4)
  ReconnectRequest = 12, // client -> server: 重连请求，载荷 session_token(8)
  StateSnapshot = 13,    // server -> client: 完整游戏状态，载荷 frame_id(4) + state_len(4) + state_bytes
  SpectatorJoin = 14,    // client -> server: 观战者加入（只读，不发送输入）
};

// C++23: using enum for scoped enum access (when needed)
// using enum MessageType;  // Uncomment if you want to use Connect, Disconnect, etc. directly

// 2026-08-28 协议版本
inline constexpr uint16_t PROTOCOL_VERSION = 2;      // 当前协议版本（升至 2 以支持托管扩展）
inline constexpr uint16_t PROTOCOL_MIN_VERSION = 1;  // 客户端支持的最低版本（向后兼容 v1）
inline constexpr size_t VERSION_NEGOTIATE_BYTES = 1 + sizeof(uint16_t) + sizeof(uint16_t);  // msg(1) + ver(2) + min(2) = 5

// 2026-08-28 心跳间隔（毫秒）：服务器/客户端周期性发送 Heartbeat；
// 连续 HEARTBEAT_MISS_LIMIT 个间隔无包则判定断连。
inline constexpr int HEARTBEAT_INTERVAL_MS = 1000;
inline constexpr int HEARTBEAT_MISS_LIMIT = 5;  // 5s 无心跳判定断连

// ----- Frame semantics -----
// One network frame = one env step = physics_steps_per_frame (default 10) ProcessPhase() ticks.
// Frame IDs start at 0 after SessionStart; increment by 1 per env step.
// Timeout: server waits for all clients' FrameInput for frame N up to FRAME_INPUT_TIMEOUT_MS.
// Default input: if a client does not send in time, use SlotInput::Default() (zero direction, no buttons).
// 常量与 gfootball/frame_sync/schema/constants.yaml 保持一致（单一来源）；修改 YAML 后请同步此处。
inline constexpr int FRAME_INPUT_TIMEOUT_MS = 200;

// ----- Prediction cap (tunable) -----
// Max frames client may run ahead of last confirmed authoritative frame; beyond this, wait.
inline constexpr int MAX_PREDICT_AHEAD_FRAMES = 3;
// If no server packet received for this many consecutive frames, stop predicting and wait for authority.
inline constexpr int MAX_FRAMES_WITHOUT_PACKET = 5;
// State hash every K frames for verification (server sends, client compares).
inline constexpr int STATE_HASH_INTERVAL_K = 10;

// ----- Per-slot input: full action (direction + button bitmask; order matches SetControllerSetup) -----
// Direction: 2D in plane (x, y), normalized or zero. Stored as two floats.
// Buttons: bitmask of e_ButtonFunction (0..e_ButtonFunction_Size-1). Bit i = 1 means button i pressed.
inline constexpr int BUTTON_COUNT = 12;  // e_ButtonFunction_Size

#pragma pack(push, 1)  // 2026-08-28 修复 padding bug：与 Python struct.pack('<ffH') 对齐，10 字节无填充
struct SlotInput {
  float dir_x = 0.f;
  float dir_y = 0.f;
  uint16_t buttons = 0;  // bitmask for e_ButtonFunction

  // C++23: Using default member initializer
  [[nodiscard]] static consteval SlotInput Default() noexcept {
    return SlotInput{.dir_x = 0.f, .dir_y = 0.f, .buttons = 0};
  }

  // C++23: using enum for button constants (if needed)
  // static constexpr uint16_t kButtonShoot = 1u << 0;
  // static constexpr uint16_t kButtonPass = 1u << 1;
  // ...

  [[nodiscard]] constexpr bool operator==(const SlotInput& o) const noexcept = default;
  [[nodiscard]] constexpr bool operator!=(const SlotInput& o) const noexcept = default;
};
#pragma pack(pop)

// C++23: Structured bindings support
static_assert(sizeof(SlotInput) == 10, "SlotInput must be 10 bytes (no padding)");

inline constexpr size_t SLOT_INPUT_BYTES = sizeof(SlotInput);

// ----- Input validation (2026-08-31 ms-1.5 外挂校验) -----
// Validates SlotInput: direction range, NaN/Inf, button bitmask.
// Returns true if valid; false if input should be rejected.
[[nodiscard]] inline constexpr bool IsValidSlotInput(const SlotInput& si) noexcept {
  // 1. Direction range: normalized to [-1,1] or zero (with tolerance)
  if (std::abs(si.dir_x) > 1.001f || std::abs(si.dir_y) > 1.001f) return false;
  // 2. No NaN/Inf
  if (!std::isfinite(si.dir_x) || !std::isfinite(si.dir_y)) return false;
  // 3. Button bitmask: only valid bits (0..BUTTON_COUNT-1) set
  constexpr uint16_t kValidButtonMask = (1u << BUTTON_COUNT) - 1;
  if (si.buttons & ~kValidButtonMask) return false;
  return true;
}

// ----- Type aliases (used by several packet layouts) -----
using frame_id_t = uint32_t;
using state_hash_t = uint64_t;
using session_token_t = uint64_t;

// 2026-09-01 断线托管：消息大小常量
// TakeoverNotify / HandbackNotify: msg_type(1) + slot_index(2) + frame_id(4) = 7
inline constexpr size_t TAKEOVER_NOTIFY_BYTES = 1 + sizeof(uint16_t) + sizeof(frame_id_t);
inline constexpr size_t HANDBACK_NOTIFY_BYTES = 1 + sizeof(uint16_t) + sizeof(frame_id_t);
// ReconnectRequest: msg_type(1) + session_token(8) = 9
inline constexpr size_t RECONNECT_REQUEST_BYTES = 1 + sizeof(session_token_t);
// StateSnapshot header: msg_type(1) + frame_id(4) + state_len(4) = 9, then state_len bytes
inline constexpr size_t STATE_SNAPSHOT_HEADER_BYTES = 1 + sizeof(frame_id_t) + sizeof(uint32_t);

// C++23: Using std::bit_cast for type-safe bit manipulation
template <typename To, typename From>
[[nodiscard]] constexpr To BitCast(const From& from) noexcept {
  static_assert(sizeof(To) == sizeof(From), "BitCast requires same size");
  return std::bit_cast<To>(from);
}

// ----- Heartbeat packet (2026-08-28) -----
// Layout: message_type (1) + frame_id (4) + timestamp_ms (4B uint32_t)
inline constexpr size_t HEARTBEAT_PACKET_BYTES = 1 + sizeof(frame_id_t) + sizeof(uint32_t);

// ----- Authoritative frame packet (server -> client) -----
// Layout: message_type (1) + frame_id (4) + num_slots (2) + slot_inputs (num_slots * SLOT_INPUT_BYTES)
// Optional trailer: state_hash (4 or 8 bytes) if MessageType has hash.

inline constexpr size_t AUTHORITATIVE_FRAME_HEADER_BYTES = 1 + sizeof(frame_id_t) + sizeof(uint16_t);

// ----- Client frame input (client -> server) -----
// Layout: message_type (1) + frame_id (4) + num_my_slots (2) + slot_index (2) per slot + slot_inputs
// For simplicity: client sends one FrameInput per frame with all slots they control (slot indices + inputs).
struct ClientFrameInputHeader {
  frame_id_t frame_id;
  uint16_t num_slots;  // number of (slot_index, SlotInput) pairs following

  // C++23: Using defaulted comparison operators
  [[nodiscard]] constexpr bool operator==(const ClientFrameInputHeader&) const noexcept = default;
};
inline constexpr size_t CLIENT_FRAME_INPUT_HEADER_BYTES = 1 + sizeof(ClientFrameInputHeader);
// Per reported slot: slot_index (2 bytes) + SlotInput
inline constexpr size_t CLIENT_SLOT_ENTRY_BYTES = sizeof(uint16_t) + SLOT_INPUT_BYTES;

// ----- Session start (server -> client) -----
// Params needed for setConfig + reset: left_agents, right_agents, game_engine_random_seed,
// and optionally a serialized ScenarioConfig or config id. Minimal: seed (4) + left_agents (2) + right_agents (2).
struct SessionStartParams {
  uint32_t game_engine_random_seed = 42;
  uint16_t left_agents = 1;
  uint16_t right_agents = 0;

  // C++23: Using defaulted comparison operators
  [[nodiscard]] constexpr bool operator==(const SessionStartParams&) const noexcept = default;
};
inline constexpr size_t SESSION_START_PARAMS_BYTES = sizeof(SessionStartParams);

// ----- 2026-09-01 Session Token 生成 -----
// 用于断线重连时识别客户端身份。
// token = FNV1a(slot_index | (seed << 16) | (session_id << 32))
inline session_token_t MakeSessionToken(uint16_t slot_index, uint32_t seed,
                                        uint32_t session_id) noexcept {
  uint64_t raw = static_cast<uint64_t>(slot_index)
               | (static_cast<uint64_t>(seed) << 16)
               | (static_cast<uint64_t>(session_id) << 32);
  // FNV-1a 64-bit
  uint64_t hash = 14695981039346656037ULL;
  for (int i = 0; i < 8; ++i) {
    hash ^= static_cast<uint8_t>(raw >> (i * 8));
    hash *= 1099511628211ULL;
  }
  return hash;
}

}  // namespace frame_sync

// C++23: Adding std::hash specialization for MessageType
template <>
struct std::hash<frame_sync::MessageType> {
  [[nodiscard]] size_t operator()(frame_sync::MessageType mt) const noexcept {
    return std::hash<uint8_t>{}(static_cast<uint8_t>(mt));
  }
};

#endif
