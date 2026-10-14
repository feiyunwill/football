#include "training/native_training.hpp"
#include "gfootball_actions.h"
#include <algorithm>
#include <stdexcept>

namespace football::training {
namespace {
constexpr std::array<int, 20> kActions = {
    game_idle, game_left, game_top_left, game_top, game_top_right,
    game_right, game_bottom_right, game_bottom, game_bottom_left,
    game_long_pass, game_high_pass, game_short_pass, game_shot, game_sprint,
    game_release_direction, game_release_sprint, game_sliding, game_dribble,
    game_release_dribble, game_builtin_ai};

// 2026-10-14: both 115 layouts share ball/owner/active/mode encoding.
// Simple115 encode(const SharedInfo& info, bool right, int active) {
Simple115 encode(const SharedInfo& info, bool right, int active, bool fixed_positions) {
  Simple115 result{};
  std::fill_n(result.begin(), 88, -1.0f);
  const auto& left = right ? info.right_team : info.left_team;
  const auto& other = right ? info.left_team : info.right_team;
  const float sign = right ? -1.0f : 1.0f;
  auto team = [&](const auto& players, size_t offset) {
    if (players.size() > 11) throw std::runtime_error("Training team exceeds eleven players");
    for (size_t i = 0; i < players.size(); ++i) {
      for (int axis = 0; axis < 2; ++axis) {
        result[offset + i * 2 + axis] = sign * players[i].player_position.env_coord(axis);
        // Legacy simple115 packs each team block immediately after its positions.
        // result[offset + 22 + i * 2 + axis] = sign * players[i].player_direction.env_coord(axis);
        const size_t direction_offset = offset + (fixed_positions ? 22 : players.size() * 2);
        result[direction_offset + i * 2 + axis] = sign * players[i].player_direction.env_coord(axis);
      }
    }
  };
  team(left, 0);
  // 2026-10-14: simple115 pads only the entire 88-feature prefix, not each team block.
  // team(other, 44);
  team(other, fixed_positions ? 44 : left.size() * 4);
  for (int axis = 0; axis < 3; ++axis) {
    const float rotation = axis == 2 ? 1.0f : sign;
    result[88 + axis] = rotation * info.ball_position.env_coord(axis);
    result[91 + axis] = rotation * info.ball_direction.env_coord(axis);
  }
  int owner = info.ball_owned_team;
  if (right && owner >= 0) owner = 1 - owner;
  const int mode = static_cast<int>(info.game_mode);
  if (owner < -1 || owner > 1 || active < -1 || active > 10 || mode < 0 || mode > 6)
    throw std::runtime_error("Invalid training observation metadata");
  result[94 + owner + 1] = 1.0f;
  if (active != -1) result[97 + active] = 1.0f;
  result[108 + mode] = 1.0f;
  return result;
}
}  // namespace

// 2026-10-14: layout is immutable across episodes, just like the action set.
// NativeTrainingEnv::NativeTrainingEnv(int width, int height, bool builtin_ai_action)
//     : builtin_ai_action_(builtin_ai_action) {
// 2026-10-14: checkpoint state is per-agent and reset per episode.
// NativeTrainingEnv::NativeTrainingEnv(int width, int height, bool builtin_ai_action, bool fixed_positions)
//     : builtin_ai_action_(builtin_ai_action), fixed_positions_(fixed_positions) {
NativeTrainingEnv::NativeTrainingEnv(int width, int height, bool builtin_ai_action,
                                   bool fixed_positions, bool checkpoint_rewards)
    : builtin_ai_action_(builtin_ai_action), fixed_positions_(fixed_positions),
      checkpoint_rewards_(checkpoint_rewards) {
  if (width < 1 || width > 8192 || height < 1 || height > 8192 ||
      static_cast<int64_t>(width) * height > 16777216)
    throw std::invalid_argument("Invalid training render dimensions");
  env_.game_config.render = false;
  env_.game_config.render_resolution_x = width;
  env_.game_config.render_resolution_y = height;
}
NativeTrainingEnv::~NativeTrainingEnv() = default;
void NativeTrainingEnv::require_open() const {
  if (closed_) throw std::logic_error("Native training environment is closed");
}

std::vector<Simple115> NativeTrainingEnv::observations(const SharedInfo& info) const {
  // 2026-10-14: share direct output writing with bounded rollout buffers.
  // std::vector<Simple115> result;
  // result.reserve(scenario.left_agents + scenario.right_agents);
  std::vector<Simple115> result(env_.scenario_config.left_agents + env_.scenario_config.right_agents);
  write_observations(info, result);
  return result;
}

void NativeTrainingEnv::write_observations(const SharedInfo& info, std::span<Simple115> output) const {
  const auto& scenario = env_.scenario_config;
  size_t index = 0;
  for (bool right : {false, true}) {
    const auto& controllers = right ? info.right_controllers : info.left_controllers;
    int count = right ? scenario.right_agents : scenario.left_agents;
    if (count == 0) continue;
    // 2026-10-14: team/ball/mode features are identical for every agent on a team.
    // output[index++] = encode(info, right, i < static_cast<int>(controllers.size())
    //                                       ? controllers[i].controlled_player : -1);
    // const auto shared = encode(info, right, -1);
    const auto shared = encode(info, right, -1, fixed_positions_);
    for (int i = 0; i < count; ++i) {
      const int active = i < static_cast<int>(controllers.size()) ? controllers[i].controlled_player : -1;
      if (active < -1 || active > 10) throw std::runtime_error("Invalid training active player");
      auto& row = output[index++];
      row = shared;
      if (active != -1) row[97 + active] = 1.0f;
    }
  }
}

std::vector<Simple115> NativeTrainingEnv::reset(ScenarioConfig& scenario, int physics_steps) {
  std::lock_guard lock(mutex_);
  require_open();
  if (physics_steps < 1 || physics_steps > 1000)
    throw std::invalid_argument("physics_steps_per_frame must be in [1, 1000]");
  if (scenario.control_all_players || scenario.real_time ||
      (scenario.left_agents == 0) == (scenario.right_agents == 0) ||
      scenario.left_agents > 11 || scenario.right_agents > 11)
    throw std::invalid_argument("Native training requires single-team control without control_all_players or real_time");
  ready_ = false;
  env_.game_config.physics_steps_per_frame = physics_steps;
  // Match Core startup/reset order, including the initial default match.
  if (!env_.context) env_.start_game();
  env_.state = game_running;
  env_.reset(scenario, false);
  do {
    info_ = env_.get_info();
    if (info_.is_in_play) break;
    env_.step();
  } while (true);
  previous_score_diff_ = 0;
  previous_game_mode_ = -1;
  previous_ball_owned_team_ = -1;
  if (checkpoint_rewards_) checkpoints_.reset(scenario.left_agents + scenario.right_agents);
  auto result = observations(info_);
  ready_ = true;
  return result;
}

TrainingTransition NativeTrainingEnv::step(std::span<const int> actions) {
  std::lock_guard lock(mutex_);
  require_open();
  if (!ready_) throw std::logic_error("Reset before stepping a new or finished match");
  const size_t count = env_.scenario_config.left_agents + env_.scenario_config.right_agents;
  if (actions.size() != count) throw std::invalid_argument("Incorrect joint action count");
  validate_actions(actions);
  // 2026-10-14: scalar and batched stepping share one transition implementation.
  TrainingTransition result{std::vector<Simple115>(count), std::vector<float>(count)};
  auto [terminated, reward] = advance(actions, result.observations, result.rewards);
  result.terminated = terminated;
  result.score_reward = reward;
  return result;
}

void NativeTrainingEnv::validate_actions(std::span<const int> actions) const {
  for (int action : actions)
    if (action < 0 || action >= (builtin_ai_action_ ? 20 : 19))
      throw std::invalid_argument("Action outside training action set");
}

TrainingBatch NativeTrainingEnv::step_many(std::span<const int> actions, size_t steps) {
  std::lock_guard lock(mutex_);
  require_open();
  if (!ready_) throw std::logic_error("Reset before stepping a new or finished match");
  if (steps < 1 || steps > kMaxTrainingBatchSteps)
    throw std::invalid_argument("Batch must contain 1..256 steps");
  const size_t count = env_.scenario_config.left_agents + env_.scenario_config.right_agents;
  if (actions.size() != steps * count) throw std::invalid_argument("Incorrect batched joint action count");
  // Reject even an invalid suffix before the first transition mutates the match.
  validate_actions(actions);
  TrainingBatch result{count, std::vector<Simple115>(steps * count),
                       std::vector<float>(steps * count),
                       std::vector<uint8_t>(steps), std::vector<int>(steps)};
  size_t completed = 0;
  for (; completed < steps; ++completed) {
    const auto [terminated, reward] = advance(
        actions.subspan(completed * count, count),
        std::span(result.observations).subspan(completed * count, count),
        std::span(result.rewards).subspan(completed * count, count));
    result.terminated[completed] = terminated;
    result.score_rewards[completed] = reward;
    if (terminated) { ++completed; break; }
  }
  result.observations.resize(completed * count);
  result.rewards.resize(completed * count);
  result.terminated.resize(completed);
  result.score_rewards.resize(completed);
  return result;
}

std::pair<bool, int> NativeTrainingEnv::advance(std::span<const int> actions,
                                             std::span<Simple115> output,
                                             std::span<float> rewards) {
  const auto& scenario = env_.scenario_config;
  try {
    size_t index = 0;
    for (bool left : {true, false}) {
      int agents = left ? scenario.left_agents : scenario.right_agents;
      const auto& controllers = left ? info_.left_controllers : info_.right_controllers;
      for (int player = 0; player < agents; ++player) {
        int action = kActions[actions[index++]];
        if (!left && action >= game_left && action <= game_bottom_left)
          action = 1 + (action - 1 + 4) % 8;
        if (env_.waiting_for_game_count == 20) action = game_short_pass;
        else if (env_.waiting_for_game_count > 20) {
          action = game_idle;
          const int controlled = player < static_cast<int>(controllers.size())
                                     ? controllers[player].controlled_player : -1;
          if (info_.ball_owned_team != -1 && (info_.ball_owned_team ^ left) &&
              controlled == info_.ball_owned_player)
            action = (env_.waiting_for_game_count < 30) != left ? game_left : game_right;
        }
        env_.action(action, left, player);
      }
    }
    do {
      env_.step();
      info_ = env_.get_info();
    } while (!info_.is_in_play);
    const int mode = static_cast<int>(info_.game_mode);
    bool terminated =
        (scenario.end_episode_on_score && (info_.left_goals > 0 || info_.right_goals > 0)) ||
        (scenario.end_episode_on_out_of_play && mode != e_GameMode_Normal &&
         previous_game_mode_ == e_GameMode_Normal) ||
        (scenario.end_episode_on_possession_change && info_.ball_owned_team != -1 &&
         previous_ball_owned_team_ != -1 && info_.ball_owned_team != previous_ball_owned_team_) ||
        info_.step >= scenario.game_duration || env_.state == game_done;
    previous_game_mode_ = mode;
    if (info_.ball_owned_team != -1) previous_ball_owned_team_ = info_.ball_owned_team;
    int score = info_.left_goals - info_.right_goals;
    int reward = score - previous_score_diff_;
    previous_score_diff_ = score;
    env_.waiting_for_game_count = mode == e_GameMode_Normal ? 0 : env_.waiting_for_game_count + 1;
    if (terminated) env_.state = game_done;
    // 2026-10-14: write into caller-owned buffers, without per-frame allocations.
    // TrainingTransition result{observations(info_), {}, terminated, reward};
    // result.rewards.assign(count, static_cast<float>(scenario.left_agents ? reward : -reward));
    write_observations(info_, output);
    std::fill(rewards.begin(), rewards.end(), static_cast<float>(scenario.left_agents ? reward : -reward));
    if (checkpoint_rewards_) checkpoints_.apply(info_, scenario.right_agents != 0, rewards);
    ready_ = !terminated;
    return {terminated, reward};
  } catch (...) {
    ready_ = false;
    throw;
  }
}

std::string NativeTrainingEnv::get_state_digest() {
  std::lock_guard lock(mutex_);
  require_open();
  return env_.get_state_digest();
}
void NativeTrainingEnv::close() {
  std::lock_guard lock(mutex_);
  closed_ = true;
  ready_ = false;
  env_.close();
}
}  // namespace football::training
