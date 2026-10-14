// Optional diagnostic timing, excluded from simulation state and snapshots.
#pragma once
#include <chrono>
#include <cstdint>
namespace football::training {
struct TrainingProfile {
  uint64_t transitions = 0, engine_calls = 0;
  uint64_t action_ns = 0, engine_ns = 0, info_ns = 0;
  uint64_t transition_ns = 0, encoding_ns = 0, reward_ns = 0;
  uint64_t binding_output_ns = 0;
};
class ProfileTimer {
 public:
  ProfileTimer(uint64_t& value, bool enabled) : value_(enabled ? &value : nullptr) {
    if (value_) start_ = std::chrono::steady_clock::now();
  }
  ~ProfileTimer() {
    if (value_) *value_ += std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - start_).count();
  }
  ProfileTimer(const ProfileTimer&) = delete;
  ProfileTimer& operator=(const ProfileTimer&) = delete;
 private:
  uint64_t* value_;
  std::chrono::steady_clock::time_point start_{};
};
}
