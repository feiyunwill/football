// 2026-09-13: transfer sampled input to the game worker without holding its engine lock.
#pragma once
#include "frame_sync/native_input_timeline.hpp"
#include <chrono>
#include <cstdint>
#include <mutex>
#include <stdexcept>
namespace frame_sync {
class NativeSharedInputTimeline {
 public:
  using Clock = std::int64_t (*)();
  explicit NativeSharedInputTimeline(Clock clock = Now) : clock_(clock) {
    if (!clock_) throw std::invalid_argument("Input observation clock is required");
  }
  ~NativeSharedInputTimeline() = default;
  NativeSharedInputTimeline(const NativeSharedInputTimeline&) = delete;
  NativeSharedInputTimeline& operator=(const NativeSharedInputTimeline&) = delete;
  NativeSharedInputTimeline(NativeSharedInputTimeline&&) = delete;
  NativeSharedInputTimeline& operator=(NativeSharedInputTimeline&&) = delete;

  void Feed(const PythonWindowInput::Sample& sample) {
    std::lock_guard lock(mutex_);
    // Timestamp the serialized observation after polling. A pause on the worker
    // cannot overtake an earlier pre-lock timestamp and make the timeline go backwards.
    timeline_.Feed(sample, clock_());
  }
  SlotInput Take(std::int64_t deadline) {
    std::lock_guard lock(mutex_);
    return timeline_.Take(deadline);
  }
  auto TakeCommands() {
    std::lock_guard lock(mutex_);
    return timeline_.TakeCommands();
  }
  void SetSuspended(bool suspended) {
    std::lock_guard lock(mutex_);
    timeline_.SetSuspended(suspended, clock_());
  }
 private:
  static std::int64_t Now() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
  }
  const Clock clock_;
  std::mutex mutex_;
  NativeInputTimeline timeline_;
};
}  // namespace frame_sync
