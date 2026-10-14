#include "training/native_training.hpp"
#include "frame_sync/default_scenario.hpp"
#include <array>
#include <cstdio>
#include <stdexcept>
#include <algorithm>

void require(bool condition) {
  if (!condition) throw std::runtime_error("Native training contract failed");
}
int main(int, char**) {
  try {
    football::training::CheckpointRewards checkpoints;
    SharedInfo checkpoint_info{};
    checkpoint_info.left_controllers = {ControllerInfo(0), ControllerInfo(1)};
    checkpoint_info.right_controllers = {ControllerInfo(0), ControllerInfo(1)};
    checkpoint_info.ball_owned_team = 0;
    checkpoint_info.ball_owned_player = 1;
    checkpoint_info.ball_position = Position(0.4f, 0.0f, 0.0f, true);
    checkpoints.reset(2);
    std::array<float, 2> rewards{};
    checkpoints.apply(checkpoint_info, false, rewards);
    require(rewards[0] == 0 && rewards[1] > 0.49f && rewards[1] < 0.51f);
    require(checkpoints.collected()[0] == 0 && checkpoints.collected()[1] == 5);
    rewards = {1.0f, 1.0f};
    checkpoints.apply(checkpoint_info, false, rewards);
    require(rewards[0] == 2.0f && rewards[1] == 1.5f);
    checkpoints.reset(2);
    checkpoint_info.ball_owned_team = 1;
    rewards = {-1.0f, -1.0f};
    checkpoints.apply(checkpoint_info, false, rewards);
    require(rewards[0] == -1.0f && rewards[1] == -1.0f);
    require(checkpoints.collected()[0] == 0 && checkpoints.collected()[1] == 0);
    checkpoint_info.ball_owned_team = 0;
    constexpr std::array<float, 10> goal_credit = {1.9f, 1.8f, 1.7f, 1.6f, 1.5f,
                                                 1.4f, 1.3f, 1.2f, 1.1f, 1.0f};
    for (int boundary = 0; boundary < 10; ++boundary) {
      checkpoints.reset(1);
      checkpoint_info.ball_owned_player = 0;
      const double threshold = 0.99 - 0.8 / 9 * boundary;
      checkpoint_info.ball_position = Position(1.0 - threshold - 1e-5, 0, 0, true);
      std::array<float, 1> value{};
      checkpoints.apply(checkpoint_info, false, value);
      require(checkpoints.collected()[0] == boundary);
      checkpoint_info.ball_position = Position(1.0 - threshold + 1e-5, 0, 0, true);
      value[0] = 0;
      checkpoints.apply(checkpoint_info, false, value);
      require(checkpoints.collected()[0] == boundary + 1 && value[0] == 0.1f);
      value[0] = 0;
      checkpoints.apply(checkpoint_info, false, value);
      require(value[0] == 0);
      value[0] = 1;
      checkpoints.apply(checkpoint_info, false, value);
      require(value[0] == goal_credit[boundary] && checkpoints.collected()[0] == 10);
    }
    auto scenario = frame_sync::MakeDefaultScenario(2, 0, 42);
    scenario->game_duration = 10;
    football::training::NativeTrainingEnv env(160, 90);
    auto initial = env.reset(*scenario, 10);
    require(initial.size() == 2 && initial[0].size() == 115);
    const auto digest = env.get_state_digest();
    auto invalid_scenario = *scenario;
    invalid_scenario.left_agents = -1;
    try {
      env.reset(invalid_scenario, 20);
      throw std::runtime_error("Negative controlled-player count was accepted");
    } catch (const std::invalid_argument&) {}
    require(digest == env.get_state_digest());
    try {
      env.step(std::array<int, 2>{1, 19});
      throw std::runtime_error("Invalid joint input was accepted");
    } catch (const std::invalid_argument&) {}
    require(digest == env.get_state_digest());
    football::training::TrainingTransition final;
    for (int frame = 0; frame < 32; ++frame) {
      final = env.step(std::array<int, 2>{0, 0});
      require(final.observations.size() == 2 && final.rewards.size() == 2);
      if (final.terminated) break;
    }
    require(final.terminated);
    const auto end_digest = env.get_state_digest();
    require(initial == env.reset(*scenario, 10));
    for (int frame = 0; frame < 32; ++frame) {
      final = env.step(std::array<int, 2>{0, 0});
      if (final.terminated) break;
    }
    require(end_digest == env.get_state_digest());
    env.reset(*scenario, 10);
    std::vector<int> actions(64, 0);
    actions.back() = 19;
    const auto batch_origin = env.get_state_digest();
    try {
      env.step_many(actions, 32);
      throw std::runtime_error("Invalid batch suffix was accepted");
    } catch (const std::invalid_argument&) {}
    require(batch_origin == env.get_state_digest());
    actions.back() = 0;
    auto batch = env.step_many(actions, 32);
    require(batch.players == 2 && batch.terminated.size() < 32 && batch.terminated.back());
    require(batch.observations.size() == batch.terminated.size() * 2);
    require(end_digest == env.get_state_digest());
    // 2026-10-14: shaped output rows are spans, not fixed-size array objects.
    // require(batch.observations[batch.observations.size() - 2] == final.observations[0]);
    // require(batch.observations.back() == final.observations[1]);
    require(std::ranges::equal(batch.observations[batch.observations.size() - 2], final.observations[0]));
    require(std::ranges::equal(batch.observations.back(), final.observations[1]));
    auto sparse = frame_sync::MakeDefaultScenario(1, 0, 42);
    sparse->left_team.resize(2);
    sparse->right_team.resize(1);
    football::training::NativeTrainingEnv fixed(160, 90);
    football::training::NativeTrainingEnv compact(160, 90, false, false);
    auto fixed_rows = fixed.reset(*sparse, 10);
    auto compact_rows = compact.reset(*sparse, 10);
    require(fixed_rows.size() == 1 && compact_rows.size() == 1);
    require(fixed_rows[0][4] == -1.0f && compact_rows[0][4] != -1.0f);
    require(fixed.get_state_digest() == compact.get_state_digest());
    for (size_t i = 88; i < 115; ++i) require(fixed_rows[0][i] == compact_rows[0][i]);
    for (int frame = 0; frame < 5; ++frame) {
      auto a = fixed.step(std::array<int, 1>{frame});
      auto b = compact.step(std::array<int, 1>{frame});
      require(a.rewards == b.rewards && a.terminated == b.terminated);
      require(fixed.get_state_digest() == compact.get_state_digest());
    }
    football::training::NativeTrainingEnv stacked(160, 90, false, true, false, true);
    auto stack_initial = stacked.reset(*scenario, 10);
    auto plain_initial = env.reset(*scenario, 10);
    require(stack_initial.size() == 2 && stack_initial.columns() == 460);
    for (size_t player = 0; player < 2; ++player)
      for (size_t age = 0; age < 4; ++age)
        require(std::ranges::equal(stack_initial[player].subspan(age * 115, 115), plain_initial[player]));
    std::vector<football::training::TrainingTransition> stack_frames;
    for (int frame = 0; frame < 32; ++frame) {
      auto a = env.step(std::array<int, 2>{0, 0});
      auto b = stacked.step(std::array<int, 2>{0, 0});
      const auto& previous = stack_frames.empty() ? stack_initial : stack_frames.back().observations;
      for (size_t player = 0; player < 2; ++player) {
        require(std::ranges::equal(b.observations[player].first(345), previous[player].subspan(115)));
        require(std::ranges::equal(b.observations[player].last(115), a.observations[player]));
      }
      require(a.rewards == b.rewards && a.terminated == b.terminated);
      require(env.get_state_digest() == stacked.get_state_digest());
      stack_frames.push_back(std::move(b));
      if (a.terminated) break;
    }
    require(stack_frames.back().terminated);
    require(stack_initial == stacked.reset(*scenario, 10));
    auto stack_batch = stacked.step_many(std::vector<int>(64, 0), 32);
    require(stack_batch.terminated.size() == stack_frames.size() && stack_batch.observations.columns() == 460);
    for (size_t frame = 0; frame < stack_frames.size(); ++frame)
      for (size_t player = 0; player < 2; ++player)
        require(std::ranges::equal(stack_batch.observations[frame * 2 + player], stack_frames[frame].observations[player]));
    env.close();
    env.close();
    try {
      env.reset(*scenario, 10);
      throw std::runtime_error("Closed environment restarted");
    } catch (const std::logic_error&) {}
    // 2026-10-14: the native contract now covers bounded batches and terminal prefixes.
    // std::puts("Native training: joint admission, termination and deterministic reset passed");
    // std::puts("Native training: joint/batch admission, termination and deterministic reset passed");
    // std::puts("Native training: admission, termination, deterministic reset and both 115 layouts passed");
    // std::puts("Native training: admission, termination, reset, both layouts and checkpoint thresholds passed");
    std::puts("Native training: admission, termination, reset, layouts, checkpoints and frame stacks passed");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
