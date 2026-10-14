#include "training/native_training.hpp"
#include "training/snapshot_identity.hpp"
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
                                   bool fixed_positions, bool checkpoint_rewards, bool stacked)
    : builtin_ai_action_(builtin_ai_action), fixed_positions_(fixed_positions),
      checkpoint_rewards_(checkpoint_rewards), stacked_(stacked) {
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

// 2026-10-14: expose dynamic feature width with one contiguous output allocation.
// std::vector<Simple115> NativeTrainingEnv::observations(const SharedInfo& info) const {
ObservationBuffer NativeTrainingEnv::observations(const SharedInfo& info, bool reset_stack) {
  // 2026-10-14: share direct output writing with bounded rollout buffers.
  // std::vector<Simple115> result;
  // result.reserve(scenario.left_agents + scenario.right_agents);
  // std::vector<Simple115> result(env_.scenario_config.left_agents + env_.scenario_config.right_agents);
  // write_observations(info, result);
  ObservationBuffer result(env_.scenario_config.left_agents + env_.scenario_config.right_agents, observation_width());
  write_observations(info, result.buffer(), reset_stack);
  return result;
}

// void NativeTrainingEnv::write_observations(const SharedInfo& info, std::span<Simple115> output) const {
void NativeTrainingEnv::write_observations(const SharedInfo& info, std::span<float> output, bool reset_stack) {
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
      // 2026-10-14: encode once, then write plain output or the bounded ring.
      // auto& row = output[index++];
      // row = shared;
      auto row = shared;
      if (active != -1) row[97 + active] = 1.0f;
      if (!stacked_) {
        std::copy(row.begin(), row.end(), output.begin() + index * kSimple115Features);
      } else if (reset_stack) {
        for (auto& frame : history_) frame[index] = row;
      } else {
        history_[history_next_][index] = row;
      }
      ++index;
    }
  }
  if (stacked_) {
    if (!reset_stack) history_next_ = (history_next_ + 1) % kFrameStackFrames;
    for (size_t player = 0; player < index; ++player) {
      for (size_t age = 0; age < kFrameStackFrames; ++age) {
        const auto& row = history_[(history_next_ + age) % kFrameStackFrames][player];
        std::copy(row.begin(), row.end(), output.begin() + player * observation_width() + age * kSimple115Features);
      }
    }
  }
}

// std::vector<Simple115> NativeTrainingEnv::reset(ScenarioConfig& scenario, int physics_steps) {
ObservationBuffer NativeTrainingEnv::reset(ScenarioConfig& scenario, int physics_steps) {
  std::lock_guard lock(mutex_);
  require_open();
  if (physics_steps < 1 || physics_steps > 1000)
    throw std::invalid_argument("physics_steps_per_frame must be in [1, 1000]");
  if (scenario.control_all_players || scenario.real_time ||
      (scenario.left_agents == 0) == (scenario.right_agents == 0) ||
      // 2026-10-14: signed counts must reject negatives before touching cadence/ready state.
      scenario.left_agents < 0 || scenario.right_agents < 0 ||
      scenario.left_agents > 11 || scenario.right_agents > 11)
    throw std::invalid_argument("Native training requires single-team control without control_all_players or real_time");
  auto identity = ScenarioIdentity(scenario);
  ready_ = false;
  snapshot_available_ = false;
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
  if (stacked_) {
    for (auto& frame : history_) frame.resize(scenario.left_agents + scenario.right_agents);
    history_next_ = 0;
  }
  // auto result = observations(info_);
  auto result = observations(info_, true);
  ready_ = true;
  scenario_identity_.swap(identity);
  snapshot_available_ = true;
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
  // TrainingTransition result{std::vector<Simple115>(count), std::vector<float>(count)};
  // auto [terminated, reward] = advance(actions, result.observations, result.rewards);
  TrainingTransition result{ObservationBuffer(count, observation_width()), std::vector<float>(count)};
  auto [terminated, reward] = advance(actions, result.observations.buffer(), result.rewards);
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
  // TrainingBatch result{count, std::vector<Simple115>(steps * count),
  TrainingBatch result{count, ObservationBuffer(steps * count, observation_width()),
                       std::vector<float>(steps * count),
                       std::vector<uint8_t>(steps), std::vector<int>(steps)};
  size_t completed = 0;
  for (; completed < steps; ++completed) {
    const auto [terminated, reward] = advance(
        actions.subspan(completed * count, count),
        // std::span(result.observations).subspan(completed * count, count),
        result.observations.buffer().subspan(completed * count * observation_width(), count * observation_width()),
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
                                             std::span<float> output,
                                             std::span<float> rewards) {
  const auto& scenario = env_.scenario_config;
  try {
    const bool profiling = profiling_enabled();
    {
    ProfileTimer timer(profile_.action_ns, profiling);
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
    }
    do {
      { ProfileTimer timer(profile_.engine_ns, profiling); env_.step(); }
      { ProfileTimer timer(profile_.info_ns, profiling); info_ = env_.get_info(); }
      if (profiling) ++profile_.engine_calls;
    } while (!info_.is_in_play);
    const int mode = static_cast<int>(info_.game_mode);
    bool terminated;
    int reward;
    {
    ProfileTimer timer(profile_.transition_ns, profiling);
    terminated =
        (scenario.end_episode_on_score && (info_.left_goals > 0 || info_.right_goals > 0)) ||
        (scenario.end_episode_on_out_of_play && mode != e_GameMode_Normal &&
         previous_game_mode_ == e_GameMode_Normal) ||
        (scenario.end_episode_on_possession_change && info_.ball_owned_team != -1 &&
         previous_ball_owned_team_ != -1 && info_.ball_owned_team != previous_ball_owned_team_) ||
        info_.step >= scenario.game_duration || env_.state == game_done;
    previous_game_mode_ = mode;
    if (info_.ball_owned_team != -1) previous_ball_owned_team_ = info_.ball_owned_team;
    int score = info_.left_goals - info_.right_goals;
    reward = score - previous_score_diff_;
    previous_score_diff_ = score;
    if (mode == e_GameMode_Normal) env_.waiting_for_game_count = 0;
    else {
      if (env_.waiting_for_game_count == std::numeric_limits<int>::max())
        throw std::overflow_error("Training restart counter capacity exceeded");
      ++env_.waiting_for_game_count;
    }
    if (terminated) env_.state = game_done;
    }
    // 2026-10-14: write into caller-owned buffers, without per-frame allocations.
    // TrainingTransition result{observations(info_), {}, terminated, reward};
    // result.rewards.assign(count, static_cast<float>(scenario.left_agents ? reward : -reward));
    { ProfileTimer timer(profile_.encoding_ns, profiling); write_observations(info_, output); }
    {
      ProfileTimer timer(profile_.reward_ns, profiling);
      std::fill(rewards.begin(), rewards.end(), static_cast<float>(scenario.left_agents ? reward : -reward));
      if (checkpoint_rewards_) checkpoints_.apply(info_, scenario.right_agents != 0, rewards);
    }
    ready_ = !terminated;
    if (profiling) ++profile_.transitions;
    return {terminated, reward};
  } catch (...) {
    ready_ = false;
    snapshot_available_ = false;
    throw;
  }
}

std::string NativeTrainingEnv::get_state_digest() {
  std::lock_guard lock(mutex_);
  require_open();
  return env_.get_state_digest();
}

std::string NativeTrainingEnv::get_state() {
  std::lock_guard lock(mutex_);
  require_open();
  if (!snapshot_available_) throw std::logic_error("Reset before saving training state");
  snapshot::State state;
  state.compatibility = TrainingCompatibility(env_);
  state.scenario = scenario_identity_;
  state.kernel = env_.get_state("");
  state.builtin_ai_action = builtin_ai_action_;
  state.fixed_positions = fixed_positions_;
  state.checkpoint_rewards = checkpoint_rewards_;
  state.stacked = stacked_;
  state.ready = ready_;
  state.left_agents = env_.scenario_config.left_agents;
  state.right_agents = env_.scenario_config.right_agents;
  state.physics_steps = env_.game_config.physics_steps_per_frame;
  state.previous_score_diff = previous_score_diff_;
  state.previous_game_mode = previous_game_mode_;
  state.previous_ball_owned_team = previous_ball_owned_team_;
  if (checkpoint_rewards_) state.checkpoints.assign(checkpoints_.collected().begin(), checkpoints_.collected().end());
  if (stacked_) {
    const size_t players = state.left_agents + state.right_agents;
    state.history.reserve(kFrameStackFrames * players * kSimple115Features);
    for (size_t age = 0; age < kFrameStackFrames; ++age)
      for (const auto& row : history_[(history_next_ + age) % kFrameStackFrames])
        state.history.insert(state.history.end(), row.begin(), row.end());
  }
  return snapshot::Encode(state);
}

void NativeTrainingEnv::set_state(std::string_view bytes) {
  std::lock_guard lock(mutex_);
  require_open();
  if (!snapshot_available_) throw std::logic_error("Reset before restoring training state");
  auto state = snapshot::Decode(bytes);
  snapshot::Require(state.compatibility == TrainingCompatibility(env_), "Incompatible training build or runtime dimensions");
  snapshot::Require(state.scenario == scenario_identity_, "Training scenario identity mismatch");
  snapshot::Require(state.builtin_ai_action == builtin_ai_action_ && state.fixed_positions == fixed_positions_ &&
                    state.checkpoint_rewards == checkpoint_rewards_ && state.stacked == stacked_,
                    "Training options mismatch");
  snapshot::Require(state.left_agents == static_cast<uint32_t>(env_.scenario_config.left_agents) &&
                    state.right_agents == static_cast<uint32_t>(env_.scenario_config.right_agents) &&
                    state.physics_steps == static_cast<uint32_t>(env_.game_config.physics_steps_per_frame),
                    "Training controller count or cadence mismatch");
  // Prepare every allocating training object before entering the kernel transaction.
  CheckpointRewards prepared_checkpoints;
  prepared_checkpoints.restore(state.checkpoints);
  std::array<std::vector<Simple115>, kFrameStackFrames> prepared_history;
  const size_t players = state.left_agents + state.right_agents;
  if (stacked_) for (size_t age = 0; age < kFrameStackFrames; ++age) {
    prepared_history[age].resize(players);
    for (size_t player = 0; player < players; ++player)
      std::copy_n(state.history.begin() + (age * players + player) * kSimple115Features,
                  kSimple115Features, prepared_history[age][player].begin());
  }
  const auto backup = env_.get_state("");
  const auto backup_config = env_.scenario_config;
  try {
    snapshot::Require(env_.set_state(state.kernel).empty(), "Training kernel contains unexpected external state");
    auto restored_info = env_.get_info();
    snapshot::Require(restored_info.step >= -1 && env_.waiting_for_game_count >= 0 &&
                      int64_t(env_.waiting_for_game_count) <= int64_t(restored_info.step) + 1 &&
                      (restored_info.game_mode != e_GameMode_Normal || env_.waiting_for_game_count == 0) &&
                      (!state.ready || env_.waiting_for_game_count < std::numeric_limits<int>::max()),
                      "Training restart counter disagrees with kernel step/mode");
    snapshot::Require((state.ready && env_.state == game_running) || (!state.ready && env_.state == game_done),
                      "Training readiness disagrees with kernel state");
    // Incoming goal integers must not overflow while checking their difference.
    snapshot::Require(restored_info.left_goals >= 0 && restored_info.right_goals >= 0 && restored_info.is_in_play &&
                      int64_t(state.previous_score_diff) == int64_t(restored_info.left_goals) - restored_info.right_goals,
                      "Training score history disagrees with kernel state");
    snapshot::Require(state.previous_game_mode == -1 || state.previous_game_mode == static_cast<int>(restored_info.game_mode),
                      "Training game-mode history disagrees with kernel state");
    if (restored_info.ball_owned_team != -1 && state.previous_game_mode != -1)
      snapshot::Require(state.previous_ball_owned_team == restored_info.ball_owned_team,
                        "Training possession history disagrees with kernel state");
    if (stacked_) {
      const bool right = state.right_agents != 0;
      const auto& controllers = right ? restored_info.right_controllers : restored_info.left_controllers;
      for (size_t player = 0; player < players; ++player) {
        const int active = player < controllers.size() ? controllers[player].controlled_player : -1;
        snapshot::Require(prepared_history.back()[player] == encode(restored_info, right, active, fixed_positions_),
                          "Newest frame disagrees with kernel observation");
      }
    }
    // No throwing operations after this point: commit prepared owned data together.
    static_assert(std::is_nothrow_move_assignable_v<SharedInfo>);
    info_ = std::move(restored_info);
    checkpoints_.swap(prepared_checkpoints);
    history_.swap(prepared_history);
    history_next_ = 0;
    previous_score_diff_ = state.previous_score_diff;
    previous_game_mode_ = state.previous_game_mode;
    previous_ball_owned_team_ = state.previous_ball_owned_team;
    ready_ = state.ready;
  } catch (...) {
    const auto failure = std::current_exception();
    try {
      env_.scenario_config = backup_config;
      env_.set_state(backup);
    } catch (...) {
      closed_ = true; ready_ = snapshot_available_ = false;
      env_.close();
      throw std::runtime_error("Training snapshot rollback failed; environment was closed");
    }
    std::rethrow_exception(failure);
  }
}
void NativeTrainingEnv::close() {
  std::lock_guard lock(mutex_);
  closed_ = true;
  ready_ = false;
  snapshot_available_ = false;
  env_.close();
}
bool NativeTrainingEnv::is_closed() {
  std::lock_guard lock(mutex_);
  return closed_;
}
void NativeTrainingEnv::enable_profiling(bool enabled) {
  std::lock_guard lock(mutex_);
  require_open();
  profiling_enabled_ = enabled;
  profile_ = {};
}
TrainingProfile NativeTrainingEnv::get_profile() {
  std::lock_guard lock(mutex_);
  require_open();
  return profile_;
}
void NativeTrainingEnv::record_binding_output(uint64_t nanoseconds) {
  std::lock_guard lock(mutex_);
  if (profiling_enabled()) profile_.binding_output_ns += nanoseconds;
}
}  // namespace football::training
