// 2026-10-14: headless training semantics shared by C++ and Gymnasium.
#pragma once

#include "game_env.hpp"
#include "training/checkpoint_reward.hpp"
#include "training/observation_buffer.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <span>
#include <utility>
#include <vector>

namespace football::training {
using Simple115 = std::array<float, kSimple115Features>;
struct TrainingTransition {
  // 2026-10-14: contiguous shaped output supports 115 and 460 without padded strides.
  // std::vector<Simple115> observations;
  ObservationBuffer observations;
  std::vector<float> rewards;
  bool terminated = false;
  int score_reward = 0;
};

struct TrainingBatch {
  size_t players = 0;
  // Row-major [steps, players, columns] and [steps, players].
  // std::vector<Simple115> observations;
  ObservationBuffer observations;
  std::vector<float> rewards;
  std::vector<uint8_t> terminated;
  std::vector<int> score_rewards;
};

// Owns one headless engine. No Python objects or RL algorithm dependencies.
class NativeTrainingEnv {
 public:
  // 2026-10-14: preserve the fixed layout default while adding legacy compact packing.
  // NativeTrainingEnv(int width, int height, bool builtin_ai_action = false);
  NativeTrainingEnv(int width, int height, bool builtin_ai_action = false,
                    bool fixed_positions = true, bool checkpoint_rewards = false,
                    bool stacked = false);
  ~NativeTrainingEnv();
  NativeTrainingEnv() = delete;
  NativeTrainingEnv(const NativeTrainingEnv&) = delete;
  NativeTrainingEnv& operator=(const NativeTrainingEnv&) = delete;
  NativeTrainingEnv(NativeTrainingEnv&&) = delete;
  NativeTrainingEnv& operator=(NativeTrainingEnv&&) = delete;
  // std::vector<Simple115> reset(ScenarioConfig& scenario, int physics_steps);
  ObservationBuffer reset(ScenarioConfig& scenario, int physics_steps);
  TrainingTransition step(std::span<const int> actions);
  TrainingBatch step_many(std::span<const int> actions, size_t steps);
  std::string get_state_digest();
  void close();

 private:
  // 2026-10-14: shared writers maintain native history and emit shaped flat buffers.
  // std::vector<Simple115> observations(const SharedInfo& info) const;
  // void write_observations(const SharedInfo& info, std::span<Simple115> output) const;
  ObservationBuffer observations(const SharedInfo& info, bool reset_stack = false);
  void write_observations(const SharedInfo& info, std::span<float> output, bool reset_stack = false);
  size_t observation_width() const { return kSimple115Features * (stacked_ ? kFrameStackFrames : 1); }
  void validate_actions(std::span<const int> actions) const;
  std::pair<bool, int> advance(std::span<const int> actions,
                              std::span<float> output, std::span<float> rewards);
  void require_open() const;
  GameEnv env_;
  std::mutex mutex_;
  bool closed_ = false;
  bool ready_ = false;
  bool builtin_ai_action_;
  bool fixed_positions_;
  bool checkpoint_rewards_;
  bool stacked_;
  std::array<std::vector<Simple115>, kFrameStackFrames> history_;
  size_t history_next_ = 0;
  CheckpointRewards checkpoints_;
  int previous_score_diff_ = 0;
  int previous_game_mode_ = -1;
  int previous_ball_owned_team_ = -1;
  SharedInfo info_;
};
}  // namespace football::training
