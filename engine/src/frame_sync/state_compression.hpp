// Copyright 2019 Google LLC & Contributors
// State compression: delta encoding for SlotInput and state blobs.
// Reduces bandwidth by encoding only changes between frames.
// 2026-08-31 Modernized with C++23 features.

#ifndef GFOOTBALL_FRAME_SYNC_STATE_COMPRESSION_HPP
#define GFOOTBALL_FRAME_SYNC_STATE_COMPRESSION_HPP

#include "frame_sync/protocol.hpp"
#include <cstdint>
#include <cstring>
#include <vector>
#include <array>
#include <algorithm>

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

  // C++23: Using inline constexpr for constants
  static inline constexpr size_t MAX_BYTES = 1 + 4 + 4 + 2;  // 11 bytes worst case
  static inline constexpr size_t MIN_BYTES = 1;  // no changes: just flags=0

  // Compute delta from previous input (optimized: branchless comparison)
  [[nodiscard]] static constexpr DeltaSlotInput Compute(
      const SlotInput& current, const SlotInput& previous) noexcept {
    DeltaSlotInput delta;
    delta.flags = 0;
    delta.dir_x = current.dir_x;
    delta.dir_y = current.dir_y;
    delta.buttons = current.buttons;

    // Branchless comparison using bitwise operations
    // XOR produces non-zero if values differ, then we check the result
    uint32_t dx_xor, dy_xor;
    std::memcpy(&dx_xor, &current.dir_x, 4);
    std::memcpy(&dy_xor, &current.dir_y, 4);
    uint32_t prev_dx, prev_dy;
    std::memcpy(&prev_dx, &previous.dir_x, 4);
    std::memcpy(&prev_dy, &previous.dir_y, 4);
    
    delta.flags |= ((dx_xor != prev_dx) ? 0x01 : 0);
    delta.flags |= ((dy_xor != prev_dy) ? 0x02 : 0);
    delta.flags |= ((current.buttons != previous.buttons) ? 0x04 : 0);

    return delta;
  }

  // Apply delta to previous input to reconstruct current
  [[nodiscard]] constexpr SlotInput Apply(const SlotInput& previous) const noexcept {
    SlotInput result = previous;
    if (flags & 0x01) result.dir_x = dir_x;
    if (flags & 0x02) result.dir_y = dir_y;
    if (flags & 0x04) result.buttons = buttons;
    return result;
  }

  // Pack into buffer (optimized: single memcpy when possible)
  [[nodiscard]] size_t Pack(uint8_t* buf, size_t buf_size) const noexcept {
    // Fast path: no changes (most common case during idle)
    if (flags == 0) {
      if (buf_size < 1) return 0;
      buf[0] = 0;
      return 1;
    }
    
    // Fast path: all fields changed (common during active play)
    if (flags == 0x07) {
      if (buf_size < MAX_BYTES) return 0;
      buf[0] = flags;
      std::memcpy(buf + 1, &dir_x, 4);
      std::memcpy(buf + 5, &dir_y, 4);
      std::memcpy(buf + 9, &buttons, 2);
      return MAX_BYTES;
    }
    
    // Slow path: partial changes
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
  [[nodiscard]] size_t Unpack(const uint8_t* buf, size_t buf_size) noexcept {
    size_t offset = 0;
    if (offset + 1 > buf_size) return 0;
    flags = buf[offset++];
    
    // Fast path: no changes
    if (flags == 0) {
      return 1;
    }
    
    // Fast path: all fields changed
    if (flags == 0x07) {
      if (offset + 10 > buf_size) return 0;
      std::memcpy(&dir_x, buf + offset, 4);
      std::memcpy(&dir_y, buf + offset + 4, 4);
      std::memcpy(&buttons, buf + offset + 8, 2);
      return 11;
    }
    
    // Slow path: partial changes
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
  [[nodiscard]] constexpr bool is_empty() const noexcept { return flags == 0; }

  // Estimated bytes saved vs full SlotInput
  [[nodiscard]] constexpr size_t bytes_saved() const noexcept {
    return SLOT_INPUT_BYTES - packed_size();
  }

  // C++23: Using std::array for lookup table
  [[nodiscard]] constexpr size_t packed_size() const noexcept {
    // Fast lookup table for common cases
    const std::array<size_t, 8> kSizeTable = {
      1,   // 000: no changes
      5,   // 001: dir_x only
      5,   // 010: dir_y only
      9,   // 011: dir_x + dir_y
      3,   // 100: buttons only
      7,   // 101: dir_x + buttons
      7,   // 110: dir_y + buttons
      11   // 111: all fields
    };
    return kSizeTable[flags & 0x07];
  }
};

// Delta encoder for a vector of slot inputs (optimized for batch processing)
class DeltaEncoder {
 public:
  explicit DeltaEncoder(size_t num_slots) : num_slots_(num_slots), previous_(num_slots) {}

  // Encode current inputs as deltas from previous (optimized: reserve exact size)
  [[nodiscard]] std::vector<DeltaSlotInput> Encode(const std::vector<SlotInput>& current) {
    std::vector<DeltaSlotInput> deltas;
    deltas.reserve(num_slots_);
    for (size_t i = 0; i < num_slots_ && i < current.size(); ++i) {
      deltas.push_back(DeltaSlotInput::Compute(current[i], previous_[i]));
    }
    return deltas;
  }

  // Decode deltas back to full inputs (optimized: in-place reconstruction)
  [[nodiscard]] std::vector<SlotInput> Decode(const std::vector<DeltaSlotInput>& deltas) {
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
  void Reset() noexcept {
    for (auto& p : previous_) {
      p = SlotInput::Default();
    }
  }

  // Get compression ratio
  [[nodiscard]] constexpr float compression_ratio(
      size_t total_delta_bytes, size_t total_full_bytes) const noexcept {
    if (total_full_bytes == 0) return 1.0f;
    return static_cast<float>(total_delta_bytes) / total_full_bytes;
  }

  // Get previous input for a slot (for batch encoding)
  [[nodiscard]] const SlotInput& GetPrevious(size_t slot_index) const {
    return previous_[slot_index < num_slots_ ? slot_index : 0];
  }

  // Update previous input for a slot (for batch decoding)
  void UpdatePrevious(size_t slot_index, const SlotInput& input) {
    if (slot_index < num_slots_) {
      previous_[slot_index] = input;
    }
  }

 private:
  size_t num_slots_;
  std::vector<SlotInput> previous_;
};

}  // namespace frame_sync

#endif
