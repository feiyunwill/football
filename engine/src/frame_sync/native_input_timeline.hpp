// 2026-09-13: bounded local input history indexed by observation time.
#pragma once
#include "frame_sync/native_input_buffer.hpp"
#include <array>
#include <cstddef>
#include <tuple>

namespace frame_sync {
// Single SDL/simulation owner. Capture complete device observations now; admit
// only observations available by each logical deadline, including during debt.
// Queue exhaustion closes this owner instead of silently dropping input edges.
class NativeInputTimeline {
 public:
  static constexpr std::size_t kCapacity = 256;
  explicit NativeInputTimeline(std::size_t capacity = kCapacity) : capacity_(capacity) {
    if (!capacity || capacity > kCapacity) throw std::invalid_argument("Invalid input timeline capacity");
  }
  ~NativeInputTimeline() = default;
  NativeInputTimeline(const NativeInputTimeline&) = delete;
  NativeInputTimeline& operator=(const NativeInputTimeline&) = delete;
  NativeInputTimeline(NativeInputTimeline&&) = delete;
  NativeInputTimeline& operator=(NativeInputTimeline&&) = delete;

  void Feed(const PythonWindowInput::Sample& sample, std::int64_t observed) {
    ValidateObservation(observed);
    buffer_.Feed(sample); // validates the full sample before changing binding state
    const auto [held, keyboard, pad] = buffer_.TakeObservation();
    const std::uint8_t cancel = (!sample.focused ? 1 : 0) |
        (!sample.focused || !sample.connected ? 2 : 0);
    const bool record = !have_observation_ || !Same(held, latest_) ||
        keyboard || pad || cancel != latest_cancel_;
    if (record && size_ == capacity_) {
      Close();
      throw std::length_error("Unconsumed local input timeline capacity exhausted");
    }
    if (record) {
      observations_[(head_ + size_) % capacity_] = {observed, held, keyboard, pad, cancel};
      ++size_;
    }
    latest_ = held; latest_cancel_ = cancel;
    observed_ = observed; have_observation_ = true;
  }
  SlotInput Take(std::int64_t deadline) {
    if (deadline < epoch_ || (have_deadline_ && deadline < deadline_))
      throw std::invalid_argument("Input deadline moved backwards");
    if (have_deadline_ && deadline == deadline_) return result_;
    std::uint16_t keyboard = 0, pad = 0;
    while (size_ && std::get<0>(observations_[head_]) <= deadline) {
      const auto& [time, held, key_edges, pad_edges, cancel] = observations_[head_];
      held_ = held;
      if (cancel & 1) keyboard = 0;
      if (cancel & 2) pad = 0;
      keyboard |= key_edges; pad |= pad_edges;
      head_ = (head_ + 1) % capacity_; --size_;
    }
    result_ = held_;
    result_.buttons |= keyboard | pad;
    deadline_ = deadline; have_deadline_ = true;
    return result_;
  }
  void SetSuspended(bool suspended, std::int64_t observed) {
    ValidateObservation(observed);
    buffer_.SetSuspended(suspended);
    if (suspended == suspended_) return;
    suspended_ = suspended;
    // The control transition starts a new local epoch; no paused work or old
    // input is carried into the restarted fixed clock.
    Clear();
    observed_ = epoch_ = observed;
    have_observation_ = false; have_deadline_ = false;
  }
  std::array<bool,3> TakeCommands() noexcept { return buffer_.TakeCommands(); }
  bool release_required() const noexcept { return buffer_.release_required(); }
  bool quit_requested() const noexcept { return buffer_.quit_requested(); }
  std::size_t size() const noexcept { return size_; }
  void Close() noexcept {
    buffer_.Close(); Clear(); result_ = SlotInput::Default();
  }
 private:
  using Observation = std::tuple<std::int64_t, SlotInput, std::uint16_t, std::uint16_t, std::uint8_t>;
  static bool Same(const SlotInput& a, const SlotInput& b) noexcept {
    return a.dir_x == b.dir_x && a.dir_y == b.dir_y && a.buttons == b.buttons;
  }
  void ValidateObservation(std::int64_t time) const {
    if (time < epoch_ || time < observed_ || (have_deadline_ && time < deadline_))
      throw std::invalid_argument("Input observation moved backwards");
  }
  void Clear() noexcept {
    head_ = size_ = 0;
    held_ = latest_ = SlotInput::Default();
    latest_cancel_ = 3;
  }
  NativeInputBuffer buffer_;
  const std::size_t capacity_;
  std::array<Observation,kCapacity> observations_{};
  std::size_t head_ = 0, size_ = 0;
  std::int64_t observed_ = 0, deadline_ = 0, epoch_ = 0;
  SlotInput held_ = SlotInput::Default(), latest_ = SlotInput::Default(), result_ = SlotInput::Default();
  std::uint8_t latest_cancel_ = 3;
  bool have_observation_ = false, have_deadline_ = false, suspended_ = false;
};
} // namespace frame_sync
