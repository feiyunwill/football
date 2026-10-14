// 2026-10-14: numerical/state contract of Python CheckpointRewardWrapper.
#pragma once
#include "defines.hpp"
#include <cmath>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <vector>

namespace football::training {
class CheckpointRewards {
 public:
  CheckpointRewards() = default;
  ~CheckpointRewards() = default;
  CheckpointRewards(const CheckpointRewards&) = default;
  CheckpointRewards& operator=(const CheckpointRewards&) = default;
  CheckpointRewards(CheckpointRewards&&) noexcept = default;
  CheckpointRewards& operator=(CheckpointRewards&&) noexcept = default;

  void reset(size_t agents) {
    if (agents < 1 || agents > 11) throw std::invalid_argument("Checkpoint agent count must be 1..11");
    collected_.assign(agents, 0);
  }
  std::span<const uint8_t> collected() const { return collected_; }
  void restore(std::span<const uint8_t> counts) {
    if (counts.size() > 11) throw std::invalid_argument("Checkpoint state exceeds eleven agents");
    for (auto value : counts) if (value > 10) throw std::invalid_argument("Invalid checkpoint state count");
    std::vector<uint8_t> prepared(counts.begin(), counts.end());
    collected_.swap(prepared);
  }
  void swap(CheckpointRewards& other) noexcept { collected_.swap(other.collected_); }

  void apply(const SharedInfo& info, bool right, std::span<float> rewards) {
    if (rewards.size() != collected_.size()) throw std::invalid_argument("Checkpoint reward size mismatch");
    const auto& controllers = right ? info.right_controllers : info.left_controllers;
    const int owner = right && info.ball_owned_team >= 0 ? 1 - info.ball_owned_team : info.ball_owned_team;
    const double ball_x = static_cast<double>(info.ball_position.env_coord(0)) * (right ? -1.0 : 1.0);
    const double ball_y = static_cast<double>(info.ball_position.env_coord(1)) * (right ? -1.0 : 1.0);
    const double dx = ball_x - 1.0;
    const double distance = std::sqrt(dx * dx + ball_y * ball_y);
    for (size_t agent = 0; agent < rewards.size(); ++agent) {
      auto& count = collected_[agent];
      if (rewards[agent] == 1.0f) {
        // Python computes the remaining-goal bonus in double before adding to float32.
        rewards[agent] += static_cast<float>(0.1 * (10 - count));
        count = 10;
        continue;
      }
      const int active = agent < controllers.size() ? controllers[agent].controlled_player : -1;
      if (owner != 0 || info.ball_owned_player != active) continue;
      while (count < 10) {
        const double threshold = 0.99 - 0.8 / 9 * count;
        if (distance > threshold) break;
        rewards[agent] += 0.1f;
        ++count;
      }
    }
  }

 private:
  std::vector<uint8_t> collected_;
};
}  // namespace football::training
