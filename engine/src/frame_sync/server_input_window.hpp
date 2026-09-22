// 2026-09-13: retain once-published future inputs until their authority boundary.
#pragma once
#include "frame_sync/protocol.hpp"
#include "frame_sync/memory_budget.hpp"
#include <array>
#include <span>
#include <utility>
namespace frame_sync {
enum class InputAdmission { Accepted, Stale, OutsideWindow, Invalid, Conflict };
// Serialized by the server owner/mutex. Fixed storage, independent of peer count.
class ServerInputWindow {
 public:
  static constexpr frame_id_t kFrames = 16;
  explicit ServerInputWindow(size_t slots, frame_id_t first = 0)
      : slots_(CheckedControlledSlots(slots)), current_(first) {}
  ~ServerInputWindow() = default;
  ServerInputWindow(const ServerInputWindow&) = delete;
  ServerInputWindow& operator=(const ServerInputWindow&) = delete;
  ServerInputWindow(ServerInputWindow&&) = delete;
  ServerInputWindow& operator=(ServerInputWindow&&) = delete;
  InputAdmission Receive(frame_id_t frame,
                         std::span<const std::pair<uint16_t, SlotInput>> inputs) {
    if (inputs.empty() || inputs.size() > slots_) return InputAdmission::Invalid;
    uint32_t mask = 0;
    for (const auto& [slot, input] : inputs) {
      if (slot >= slots_ || !IsValidSlotInput(input) || (mask & (1u << slot)))
        return InputAdmission::Invalid;
      mask |= 1u << slot;
    }
    if (frame < current_) return InputAdmission::Stale;
    if (frame - current_ >= kFrames) return InputAdmission::OutsideWindow;
    auto& row = rows_[frame % kFrames];
    if (row.valid && row.frame == frame) {
      // Validate the entire packet before any mutation: first publication is immutable.
      for (const auto& [slot, input] : inputs) {
        const auto& old = row.inputs[slot];
        if ((row.mask & (1u << slot)) &&
            (old.dir_x != input.dir_x || old.dir_y != input.dir_y || old.buttons != input.buttons))
          return InputAdmission::Conflict;
      }
    } else {
      row = Row{};
      row.valid = true; row.frame = frame;
    }
    for (const auto& [slot, input] : inputs) row.inputs[slot] = input;
    row.mask |= mask;
    return InputAdmission::Accepted;
  }
  bool Has(uint16_t slot) const {
    if (slot >= slots_) throw std::out_of_range("Input slot outside match");
    const auto& row = rows_[current_ % kFrames];
    return row.valid && row.frame == current_ && (row.mask & (1u << slot));
  }
  void RemoveSlot(uint16_t slot) {
    if (slot >= slots_) throw std::out_of_range("Input slot outside match");
    for (auto& row : rows_) {
      row.mask &= ~(1u << slot);
      row.inputs[slot] = SlotInput::Default();
    }
  }
  // Close the current frame before engine work; arrivals during stepping can
  // already target the next frame, while committed late inputs remain ignored.
  void Consume(std::span<SlotInput> output) {
    if (output.size() != slots_) throw std::invalid_argument("Input output shape differs");
    if (current_ == UINT32_MAX) throw std::overflow_error("Authority input frame exhausted");
    const auto& row = rows_[current_ % kFrames];
    for (size_t slot = 0; slot < slots_; ++slot)
      output[slot] = row.valid && row.frame == current_ && (row.mask & (1u << slot))
          ? row.inputs[slot] : SlotInput::Default();
    rows_[current_ % kFrames] = Row{};
    ++current_;
  }
  frame_id_t current() const { return current_; }
 private:
  struct Row {
    Row() = default;
    ~Row() = default;
    Row(const Row&) = default;
    Row& operator=(const Row&) = default;
    Row(Row&&) = default;
    Row& operator=(Row&&) = default;
    std::array<SlotInput, kMaxControlledSlots> inputs{};
    frame_id_t frame = 0;
    uint32_t mask = 0;
    bool valid = false;
  };
  const size_t slots_;
  frame_id_t current_;
  std::array<Row, kFrames> rows_{};
};
}  // namespace frame_sync
