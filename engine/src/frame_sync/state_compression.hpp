// Copyright 2019 Google LLC & Contributors
// State compression: delta encoding for SlotInput and state blobs.
// Reduces bandwidth by encoding only changes between frames.

#ifndef GFOOTBALL_FRAME_SYNC_STATE_COMPRESSION_HPP
#define GFOOTBALL_FRAME_SYNC_STATE_COMPRESSION_HPP

#include "frame_sync/protocol.hpp"
#include <cstdint>
#include <cstring>
#include <vector>

namespace frame_sync {

// Delta-compressed SlotInput: stores only changes from previous frame.
// Layout: flags (1 byte) + [changed fields...]
// Bit 0: dir_x changed
// Bit 1: dir_y changed
// Bit 2: buttons changed
struct DeltaSlotInput {
  uint8_t flags = 0;
  float dir_x = 0.f;
  float dir_y = 0.f;
  uint16_t buttons = 0;

  static constexpr size_t MAX_BYTES = 1 + 4 + 4 + 2;  // 11 bytes worst case
  static constexpr size_t MIN_BYTES = 1;  // no changes: just flags=0

  // Compute delta from previous input
  static DeltaSlotInput Compute(const SlotInput& current, const SlotInput& previous) {
    DeltaSlotInput delta;
    delta.flags = 0;
    delta.dir_x = current.dir_x;
    delta.dir_y = current.dir_y;
    delta.buttons = current.buttons;

    if (current.dir_x != previous.dir_x) delta.flags |= 0x01;
    if (current.dir_y != previous.dir_y) delta.flags |= 0x02;
    if (current.buttons != previous.buttons) delta.flags |= 0x04;

    return delta;
  }

  // Apply delta to previous input to reconstruct current
  SlotInput Apply(const SlotInput& previous) const {
    SlotInput result = previous;
    if (flags & 0x01) result.dir_x = dir_x;
    if (flags & 0x02) result.dir_y = dir_y;
    if (flags & 0x04) result.buttons = buttons;
    return result;
  }

  // Pack into buffer
  size_t Pack(uint8_t* buf, size_t buf_size) const {
    size_t offset = 0;
    if (offset + 1 > buf_size) return 0;
    buf[offset++] = flags;
    if (flags & 0x01) {
      if (offset + 4 > buf_size) return 0;
      std::memcpy(buf + offset, &dir_x, 4);
      offset += 4;
    }
    if (flags & 0x02) {
      if (offset + 4 > buf_size) return 0;
      std::memcpy(buf + offset, &dir_y, 4);
      offset += 4;
    }
    if (flags & 0x04) {
      if (offset + 2 > buf_size) return 0;
      std::memcpy(buf + offset, &buttons, 2);
      offset += 2;
    }
    return offset;
  }

  // Unpack from buffer
  size_t Unpack(const uint8_t* buf, size_t buf_size) {
    size_t offset = 0;
    if (offset + 1 > buf_size) return 0;
    flags = buf[offset++];
    if (flags & 0x01) {
      if (offset + 4 > buf_size) return 0;
      std::memcpy(&dir_x, buf + offset, 4);
      offset += 4;
    }
    if (flags & 0x02) {
      if (offset + 4 > buf_size) return 0;
      std::memcpy(&dir_y, buf + offset, 4);
      offset += 4;
    }
    if (flags & 0x04) {
      if (offset + 2 > buf_size) return 0;
      std::memcpy(&buttons, buf + offset, 2);
      offset += 2;
    }
    return offset;
  }

  // Check if delta is empty (no changes)
  bool is_empty() const { return flags == 0; }

  // Estimated bytes saved vs full SlotInput
  size_t bytes_saved() const {
    return SLOT_INPUT_BYTES - packed_size();
  }

  size_t packed_size() const {
    size_t size = 1;  // flags
    if (flags & 0x01) size += 4;
    if (flags & 0x02) size += 4;
    if (flags & 0x04) size += 2;
    return size;
  }
};

// Delta encoder for a vector of slot inputs
class DeltaEncoder {
 public:
  DeltaEncoder(size_t num_slots) : num_slots_(num_slots), previous_(num_slots) {}

  // Encode current inputs as deltas from previous
  std::vector<DeltaSlotInput> Encode(const std::vector<SlotInput>& current) {
    std::vector<DeltaSlotInput> deltas;
    deltas.reserve(num_slots_);
    for (size_t i = 0; i < num_slots_ && i < current.size(); ++i) {
      deltas.push_back(DeltaSlotInput::Compute(current[i], previous_[i]));
    }
    return deltas;
  }

  // Decode deltas back to full inputs
  std::vector<SlotInput> Decode(const std::vector<DeltaSlotInput>& deltas) {
    std::vector<SlotInput> result;
    result.reserve(num_slots_);
    for (size_t i = 0; i < num_slots_ && i < deltas.size(); ++i) {
      SlotInput input = deltas[i].Apply(previous_[i]);
      result.push_back(input);
      previous_[i] = input;
    }
    return result;
  }

  // Reset previous state
  void Reset() {
    for (auto& p : previous_) {
      p = SlotInput::Default();
    }
  }

  // Get compression ratio
  float compression_ratio(size_t total_delta_bytes, size_t total_full_bytes) const {
    if (total_full_bytes == 0) return 1.0f;
    return static_cast<float>(total_delta_bytes) / total_full_bytes;
  }

 private:
  size_t num_slots_;
  std::vector<SlotInput> previous_;
};

}  // namespace frame_sync

#endif
