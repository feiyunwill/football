// Copyright 2019 Google LLC & Contributors
// Pack/unpack for frame_sync protocol (no engine dependency).

#ifndef GFOOTBALL_FRAME_SYNC_PROTOCOL_IO_HPP
#define GFOOTBALL_FRAME_SYNC_PROTOCOL_IO_HPP

#include "protocol.hpp"
#include "state_compression.hpp"  // 2026-09-05 优化: 添加 DeltaSlotInput 支持
#include <cstring>
#include <utility>
#include <vector>

namespace frame_sync {

// ----- SessionStart: msg_type(1) + seed(4) + left_agents(2) + right_agents(2) -----
inline size_t PackSessionStart(uint32_t seed, uint16_t left_agents, uint16_t right_agents,
                               void* buf, size_t size) {
  if (size < 1u + SESSION_START_PARAMS_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::SessionStart);
  memcpy(p, &seed, 4); p += 4;
  memcpy(p, &left_agents, 2); p += 2;
  memcpy(p, &right_agents, 2);
  return 1 + SESSION_START_PARAMS_BYTES;
}

inline size_t UnpackSessionStart(const void* buf, size_t size,
                                 uint32_t* seed, uint16_t* left_agents, uint16_t* right_agents) {
  if (size < 1u + SESSION_START_PARAMS_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::SessionStart)) return 0;
  memcpy(seed, p + 1, 4);
  memcpy(left_agents, p + 5, 2);
  memcpy(right_agents, p + 7, 2);
  return 1 + SESSION_START_PARAMS_BYTES;
}

// ----- SlotAssignment: msg_type(1) + num_slots(2) + slot_index(2) each -----
inline size_t PackSlotAssignment(const uint16_t* slot_indices, uint16_t num_slots,
                                 void* buf, size_t size) {
  size_t need = 1 + 2 + num_slots * 2;
  if (size < need) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::SlotAssignment);
  memcpy(p, &num_slots, 2); p += 2;
  for (uint16_t i = 0; i < num_slots; ++i) {
    memcpy(p, &slot_indices[i], 2); p += 2;
  }
  return need;
}

inline size_t UnpackSlotAssignment(const void* buf, size_t size,
                                   std::vector<uint16_t>* out_slots) {
  if (size < 1u + 2u) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::SlotAssignment)) return 0;
  uint16_t num;
  memcpy(&num, p + 1, 2);
  size_t need = 1 + 2 + num * 2;
  if (size < need) return 0;
  out_slots->resize(num);
  for (uint16_t i = 0; i < num; ++i)
    memcpy(&(*out_slots)[i], p + 3 + i * 2, 2);
  return need;
}

// ----- AuthoritativeFrame: msg_type(1) + frame_id(4) + num_slots(2) + slot_inputs -----
inline size_t PackAuthoritativeFrame(frame_id_t frame_id,
                                     const SlotInput* slot_inputs, uint16_t num_slots,
                                     void* buf, size_t size) {
  size_t need = 1 + 4 + 2 + num_slots * SLOT_INPUT_BYTES;
  if (size < need) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::AuthoritativeFrame);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &num_slots, 2); p += 2;
  for (uint16_t i = 0; i < num_slots; ++i) {
    memcpy(p, &slot_inputs[i], SLOT_INPUT_BYTES); p += SLOT_INPUT_BYTES;
  }
  return need;
}

inline size_t UnpackAuthoritativeFrame(const void* buf, size_t size,
                                       frame_id_t* frame_id, std::vector<SlotInput>* out_inputs) {
  if (size < 1u + 4u + 2u) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::AuthoritativeFrame)) return 0;
  memcpy(frame_id, p + 1, 4);
  uint16_t num_slots;
  memcpy(&num_slots, p + 5, 2);
  size_t need = 7 + num_slots * SLOT_INPUT_BYTES;
  if (size < need) return 0;
  out_inputs->resize(num_slots);
  for (uint16_t i = 0; i < num_slots; ++i)
    memcpy(&(*out_inputs)[i], p + 7 + i * SLOT_INPUT_BYTES, SLOT_INPUT_BYTES);
  return need;
}

// 2026-09-05 优化: 增量广播 - 只传输变化的槽位
// DeltaAuthoritativeFrame: msg_type(1) + frame_id(4) + num_changed(2) + [slot_index(2)+delta_flags(1)+changed_fields...] per slot
inline size_t PackDeltaAuthoritativeFrame(frame_id_t frame_id,
                                          const SlotInput* current_inputs,
                                          const SlotInput* previous_inputs,
                                          uint16_t num_slots,
                                          void* buf, size_t size) {
  // 计算最大可能大小
  size_t max_need = 1 + 4 + 2 + num_slots * (2 + 1 + SLOT_INPUT_BYTES);
  if (size < max_need) return 0;
  
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::DeltaAuthoritativeFrame);
  memcpy(p, &frame_id, 4); p += 4;
  
  // 先预留 num_changed 的位置
  uint16_t* num_changed_ptr = reinterpret_cast<uint16_t*>(p);
  p += 2;
  uint16_t num_changed = 0;
  
  for (uint16_t i = 0; i < num_slots; ++i) {
    // 计算 delta
    DeltaSlotInput delta = DeltaSlotInput::Compute(current_inputs[i], previous_inputs[i]);
    if (!delta.is_empty()) {
      memcpy(p, &i, 2); p += 2;
      *p++ = delta.flags;
      if (delta.flags & 0x01) { memcpy(p, &delta.dir_x, 4); p += 4; }
      if (delta.flags & 0x02) { memcpy(p, &delta.dir_y, 4); p += 4; }
      if (delta.flags & 0x04) { memcpy(p, &delta.buttons, 2); p += 2; }
      ++num_changed;
    }
  }
  
  *num_changed_ptr = num_changed;
  return 1 + 4 + 2 + (p - reinterpret_cast<uint8_t*>(num_changed_ptr + 1));
}

// 2026-09-05 优化: 增量解包
inline size_t UnpackDeltaAuthoritativeFrame(const void* buf, size_t size,
                                            frame_id_t* frame_id,
                                            std::vector<SlotInput>* out_inputs,
                                            const std::vector<SlotInput>* previous_inputs) {
  if (size < 1u + 4u + 2u) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::DeltaAuthoritativeFrame)) return 0;
  memcpy(frame_id, p + 1, 4);
  uint16_t num_changed;
  memcpy(&num_changed, p + 5, 2);
  p += 7;
  
  // 初始化输出为上一帧的输入
  *out_inputs = *previous_inputs;
  
  size_t consumed = 7;
  for (uint16_t i = 0; i < num_changed; ++i) {
    if (consumed + 2 + 1 > size) return 0;
    uint16_t slot_index;
    memcpy(&slot_index, p, 2); p += 2;
    uint8_t flags = *p++; p += 1;
    consumed += 3;
    
    if (slot_index >= out_inputs->size()) continue;
    
    SlotInput& target = (*out_inputs)[slot_index];
    if (flags & 0x01) { memcpy(&target.dir_x, p, 4); p += 4; consumed += 4; }
    if (flags & 0x02) { memcpy(&target.dir_y, p, 4); p += 4; consumed += 4; }
    if (flags & 0x04) { memcpy(&target.buttons, p, 2); p += 2; consumed += 2; }
  }
  return consumed;
}

// ----- Client FrameInput: msg_type(1) + frame_id(4) + num_slots(2) + [slot_index(2)+SlotInput] per slot -----
inline size_t PackClientFrameInput(frame_id_t frame_id,
                                   const uint16_t* slot_indices,
                                   const SlotInput* inputs, uint16_t num_slots,
                                   void* buf, size_t size) {
  size_t need = 1 + 4 + 2 + num_slots * (2 + SLOT_INPUT_BYTES);
  if (size < need) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::FrameInput);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &num_slots, 2); p += 2;
  for (uint16_t i = 0; i < num_slots; ++i) {
    memcpy(p, &slot_indices[i], 2); p += 2;
    memcpy(p, &inputs[i], SLOT_INPUT_BYTES); p += SLOT_INPUT_BYTES;
  }
  return need;
}

inline size_t UnpackClientFrameInput(const void* buf, size_t size,
                                     frame_id_t* frame_id,
                                     std::vector<std::pair<uint16_t, SlotInput>>* out_entries) {
  if (size < 1u + 4u + 2u) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::FrameInput)) return 0;
  memcpy(frame_id, p + 1, 4);
  uint16_t num_slots;
  memcpy(&num_slots, p + 5, 2);
  size_t need = 7 + num_slots * (2 + SLOT_INPUT_BYTES);
  if (size < need) return 0;
  out_entries->clear();
  out_entries->reserve(num_slots);
  size_t off = 7;
  for (uint16_t i = 0; i < num_slots; ++i) {
    uint16_t idx;
    memcpy(&idx, p + off, 2); off += 2;
    SlotInput si;
    memcpy(&si, p + off, SLOT_INPUT_BYTES); off += SLOT_INPUT_BYTES;
    out_entries->emplace_back(idx, si);
  }
  return need;
}

// ----- Ready: msg_type(1) -----
inline size_t PackReady(void* buf, size_t size) {
  if (size < 1u) return 0;
  static_cast<uint8_t*>(buf)[0] = std::to_underlying(MessageType::Ready);
  return 1;
}

// ----- StateHash (server -> client): msg_type(1) + frame_id(4) + hash(8) -----
constexpr size_t STATE_HASH_PACK_BYTES = 1 + sizeof(frame_id_t) + sizeof(state_hash_t);
inline size_t PackStateHash(frame_id_t frame_id, state_hash_t hash, void* buf, size_t size) {
  if (size < STATE_HASH_PACK_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::StateHash);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &hash, 8);
  return STATE_HASH_PACK_BYTES;
}
inline size_t UnpackStateHash(const void* buf, size_t size,
                              frame_id_t* frame_id, state_hash_t* hash) {
  if (size < STATE_HASH_PACK_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::StateHash)) return 0;
  memcpy(frame_id, p + 1, 4);
  memcpy(hash, p + 5, 8);
  return STATE_HASH_PACK_BYTES;
}

// ----- Heartbeat (bidirectional): msg_type(1) + frame_id(4) + timestamp_ms(4) -----
struct heartbeat_t {
  frame_id_t frame_id;
  uint32_t timestamp_ms;
};
constexpr size_t HEARTBEAT_PACK_BYTES = 1 + sizeof(frame_id_t) + sizeof(uint32_t);
inline size_t PackHeartbeat(frame_id_t frame_id, uint32_t timestamp_ms,
                            void* buf, size_t size) {
  if (size < HEARTBEAT_PACK_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::Heartbeat);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &timestamp_ms, 4);
  return HEARTBEAT_PACK_BYTES;
}
inline size_t UnpackHeartbeat(const void* buf, size_t size, heartbeat_t* out) {
  if (size < HEARTBEAT_PACK_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::Heartbeat)) return 0;
  memcpy(&out->frame_id, p + 1, 4);
  memcpy(&out->timestamp_ms, p + 5, 4);
  return HEARTBEAT_PACK_BYTES;
}

// ----- VersionNegotiate (client -> server): msg_type(1) + version(2) + min_version(2) -----
struct version_negotiate_t {
  uint16_t version;
  uint16_t min_version;
};
constexpr size_t VERSION_NEGOTIATE_PACK_BYTES = 1 + sizeof(uint16_t) + sizeof(uint16_t);
inline size_t PackVersionNegotiate(uint16_t version, uint16_t min_version,
                                   void* buf, size_t size) {
  if (size < VERSION_NEGOTIATE_PACK_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::VersionNegotiate);
  memcpy(p, &version, 2); p += 2;
  memcpy(p, &min_version, 2);
  return VERSION_NEGOTIATE_PACK_BYTES;
}
inline size_t UnpackVersionNegotiate(const void* buf, size_t size,
                                     version_negotiate_t* out) {
  if (size < VERSION_NEGOTIATE_PACK_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::VersionNegotiate)) return 0;
  memcpy(&out->version, p + 1, 2);
  memcpy(&out->min_version, p + 3, 2);
  return VERSION_NEGOTIATE_PACK_BYTES;
}

// ----- 2026-09-01 断线托管协议扩展 -----

// ----- TakeoverNotify (server -> client): msg_type(1) + slot_index(2) + frame_id(4) -----
inline size_t PackTakeoverNotify(uint16_t slot_index, frame_id_t frame_id,
                                 void* buf, size_t size) {
  if (size < TAKEOVER_NOTIFY_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::TakeoverNotify);
  memcpy(p, &slot_index, 2); p += 2;
  memcpy(p, &frame_id, 4);
  return TAKEOVER_NOTIFY_BYTES;
}
inline size_t UnpackTakeoverNotify(const void* buf, size_t size,
                                   uint16_t* slot_index, frame_id_t* frame_id) {
  if (size < TAKEOVER_NOTIFY_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::TakeoverNotify)) return 0;
  memcpy(slot_index, p + 1, 2);
  memcpy(frame_id, p + 3, 4);
  return TAKEOVER_NOTIFY_BYTES;
}

// ----- HandbackNotify (server -> client): msg_type(1) + slot_index(2) + frame_id(4) -----
inline size_t PackHandbackNotify(uint16_t slot_index, frame_id_t frame_id,
                                 void* buf, size_t size) {
  if (size < HANDBACK_NOTIFY_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::HandbackNotify);
  memcpy(p, &slot_index, 2); p += 2;
  memcpy(p, &frame_id, 4);
  return HANDBACK_NOTIFY_BYTES;
}
inline size_t UnpackHandbackNotify(const void* buf, size_t size,
                                   uint16_t* slot_index, frame_id_t* frame_id) {
  if (size < HANDBACK_NOTIFY_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::HandbackNotify)) return 0;
  memcpy(slot_index, p + 1, 2);
  memcpy(frame_id, p + 3, 4);
  return HANDBACK_NOTIFY_BYTES;
}

// ----- ReconnectRequest (client -> server): msg_type(1) + session_token(8) -----
inline size_t PackReconnectRequest(session_token_t token, void* buf, size_t size) {
  if (size < RECONNECT_REQUEST_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::ReconnectRequest);
  memcpy(p, &token, 8);
  return RECONNECT_REQUEST_BYTES;
}
inline size_t UnpackReconnectRequest(const void* buf, size_t size,
                                     session_token_t* token) {
  if (size < RECONNECT_REQUEST_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::ReconnectRequest)) return 0;
  memcpy(token, p + 1, 8);
  return RECONNECT_REQUEST_BYTES;
}

// ----- StateSnapshot (server -> client): msg_type(1) + frame_id(4) + state_len(4) + state_bytes -----
inline size_t PackStateSnapshot(frame_id_t frame_id, const void* state_data,
                                uint32_t state_len, void* buf, size_t size) {
  size_t need = STATE_SNAPSHOT_HEADER_BYTES + state_len;
  if (size < need) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = std::to_underlying(MessageType::StateSnapshot);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &state_len, 4); p += 4;
  if (state_len > 0 && state_data) {
    memcpy(p, state_data, state_len);
  }
  return need;
}
// UnpackStateSnapshot 返回 state 数据的偏移和长度，调用者自行拷贝
inline size_t UnpackStateSnapshot(const void* buf, size_t size,
                                  frame_id_t* frame_id,
                                  const void** state_data, uint32_t* state_len) {
  if (size < STATE_SNAPSHOT_HEADER_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != std::to_underlying(MessageType::StateSnapshot)) return 0;
  memcpy(frame_id, p + 1, 4);
  memcpy(state_len, p + 5, 4);
  size_t need = STATE_SNAPSHOT_HEADER_BYTES + *state_len;
  if (size < need) return 0;
  *state_data = p + STATE_SNAPSHOT_HEADER_BYTES;
  return need;
}

}  // namespace frame_sync

#endif
