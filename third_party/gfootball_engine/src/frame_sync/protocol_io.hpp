// Copyright 2019 Google LLC & Contributors
// Pack/unpack for frame_sync protocol (no engine dependency).

#ifndef GFOOTBALL_FRAME_SYNC_PROTOCOL_IO_HPP
#define GFOOTBALL_FRAME_SYNC_PROTOCOL_IO_HPP

#include "protocol.hpp"
#include <cstring>
#include <vector>

namespace frame_sync {

// ----- SessionStart: msg_type(1) + seed(4) + left_agents(2) + right_agents(2) -----
inline size_t PackSessionStart(uint32_t seed, uint16_t left_agents, uint16_t right_agents,
                               void* buf, size_t size) {
  if (size < 1u + SESSION_START_PARAMS_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = static_cast<uint8_t>(MessageType::SessionStart);
  memcpy(p, &seed, 4); p += 4;
  memcpy(p, &left_agents, 2); p += 2;
  memcpy(p, &right_agents, 2);
  return 1 + SESSION_START_PARAMS_BYTES;
}

inline size_t UnpackSessionStart(const void* buf, size_t size,
                                 uint32_t* seed, uint16_t* left_agents, uint16_t* right_agents) {
  if (size < 1u + SESSION_START_PARAMS_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != static_cast<uint8_t>(MessageType::SessionStart)) return 0;
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
  *p++ = static_cast<uint8_t>(MessageType::SlotAssignment);
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
  if (p[0] != static_cast<uint8_t>(MessageType::SlotAssignment)) return 0;
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
  *p++ = static_cast<uint8_t>(MessageType::AuthoritativeFrame);
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
  if (p[0] != static_cast<uint8_t>(MessageType::AuthoritativeFrame)) return 0;
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

// ----- Client FrameInput: msg_type(1) + frame_id(4) + num_slots(2) + [slot_index(2)+SlotInput] per slot -----
inline size_t PackClientFrameInput(frame_id_t frame_id,
                                   const uint16_t* slot_indices,
                                   const SlotInput* inputs, uint16_t num_slots,
                                   void* buf, size_t size) {
  size_t need = 1 + 4 + 2 + num_slots * (2 + SLOT_INPUT_BYTES);
  if (size < need) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = static_cast<uint8_t>(MessageType::FrameInput);
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
  if (p[0] != static_cast<uint8_t>(MessageType::FrameInput)) return 0;
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
  static_cast<uint8_t*>(buf)[0] = static_cast<uint8_t>(MessageType::Ready);
  return 1;
}

// ----- StateHash (server -> client): msg_type(1) + frame_id(4) + hash(8) -----
constexpr size_t STATE_HASH_PACK_BYTES = 1 + sizeof(frame_id_t) + sizeof(state_hash_t);
inline size_t PackStateHash(frame_id_t frame_id, state_hash_t hash, void* buf, size_t size) {
  if (size < STATE_HASH_PACK_BYTES) return 0;
  auto* p = static_cast<uint8_t*>(buf);
  *p++ = static_cast<uint8_t>(MessageType::StateHash);
  memcpy(p, &frame_id, 4); p += 4;
  memcpy(p, &hash, 8);
  return STATE_HASH_PACK_BYTES;
}
inline size_t UnpackStateHash(const void* buf, size_t size,
                              frame_id_t* frame_id, state_hash_t* hash) {
  if (size < STATE_HASH_PACK_BYTES) return 0;
  const auto* p = static_cast<const uint8_t*>(buf);
  if (p[0] != static_cast<uint8_t>(MessageType::StateHash)) return 0;
  memcpy(frame_id, p + 1, 4);
  memcpy(hash, p + 5, 8);
  return STATE_HASH_PACK_BYTES;
}

}  // namespace frame_sync

#endif
