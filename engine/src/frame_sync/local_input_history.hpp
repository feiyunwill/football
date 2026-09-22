// 2026-09-13: staged bounded input history, retained independently of prediction snapshots.
#pragma once
#include "frame_sync/protocol.hpp"
#include "frame_sync/memory_budget.hpp"

#include <array>
#include <functional>
#include <limits>
#include <optional>
#include <stdexcept>
#include <utility>

namespace frame_sync {
class LocalInputHistory {
 public:
  explicit LocalInputHistory(frame_id_t starting_frame = 0,
                             std::size_t capacity = kMaxBufferedAuthorityFrames)
      : confirmed_(starting_frame), capacity_(capacity) {
    if (capacity == 0 || capacity > entries_.size())
      throw std::invalid_argument("Invalid local input history capacity");
  }
  ~LocalInputHistory() = default;
  LocalInputHistory(const LocalInputHistory&) = delete;
  LocalInputHistory& operator=(const LocalInputHistory&) = delete;
  LocalInputHistory(LocalInputHistory&&) = delete;
  LocalInputHistory& operator=(LocalInputHistory&&) = delete;

  // Authority, rather than the speculative next frame, owns eviction.

  // 2026-09-14: a verified authoritative snapshot starts a new input generation.
  void Reset(frame_id_t starting_frame) {
    if (producing_) throw std::logic_error("Input producer must not reset its history");
    if (starting_frame == UINT32_MAX) throw std::overflow_error("Local input frame lifetime exhausted");
    entries_.fill(std::nullopt);size_ = 0;confirmed_ = starting_frame;
  }

  void Confirm(frame_id_t count) {
    if (producing_) throw std::logic_error("Input producer must not mutate its history");
    if (count < confirmed_) throw std::invalid_argument("Confirmed input boundary regressed");
    const auto distance = count - confirmed_;
    if (distance >= capacity_) {
      entries_.fill(std::nullopt);
      size_ = 0;
    } else {
      for (frame_id_t frame = confirmed_; frame < count; ++frame) {
        auto& entry = entries_[frame % capacity_];
        if (entry) { entry.reset(); --size_; }
      }
    }
    confirmed_ = count;
  }

  // The flag tells the transport whether this is the first submission.
  // Repeated waits and prediction recovery return the exact previous wire value.
  template<class Producer>
  std::pair<SlotInput, bool> ForFrame(frame_id_t frame, Producer&& produce) {
    if (producing_) throw std::logic_error("Input producer must not reenter its history");
    if (frame == std::numeric_limits<frame_id_t>::max())
      throw std::overflow_error("Local input frame lifetime exhausted");
    if (frame < confirmed_ || frame - confirmed_ >= capacity_)
      throw std::out_of_range("Local input frame is outside the retained window");
    auto& entry = entries_[frame % capacity_];
    if (entry) {
      if (entry->first != frame) throw std::logic_error("Unconfirmed input would be overwritten");
      return {entry->second, false};
    }
    SlotInput value;
    producing_ = true;
    try {
      value = std::invoke(std::forward<Producer>(produce), frame);
    } catch (...) {
      producing_ = false;
      throw;
    }
    producing_ = false;
    if (!IsValidSlotInput(value)) throw std::invalid_argument("Invalid local input value");
    entry.emplace(frame, value);
    ++size_;
    return {value, true};
  }

// 2026-09-13: read a previously published input without allocating or consuming another edge.
//   frame_id_t confirmed_count() const noexcept { return confirmed_; }
  // A display/replay frame may have no published local input; reading it never samples a device.
  std::optional<SlotInput> Find(frame_id_t frame) const {
    if (frame<confirmed_ || frame-confirmed_>=capacity_) return std::nullopt;
    const auto& entry=entries_[frame%capacity_];
    return entry && entry->first==frame ? std::optional(entry->second) : std::nullopt;
  }
  frame_id_t confirmed_count() const noexcept { return confirmed_; }
  std::size_t size() const noexcept { return size_; }
  std::size_t capacity() const noexcept { return capacity_; }

 private:
  std::array<std::optional<std::pair<frame_id_t, SlotInput>>, kMaxBufferedAuthorityFrames> entries_{};
  frame_id_t confirmed_ = 0;
  std::size_t capacity_, size_ = 0;
  bool producing_ = false;
};
}  // namespace frame_sync
