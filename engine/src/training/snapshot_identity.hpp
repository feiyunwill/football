// 2026-10-14: explicit scenario values, never padded struct bytes or mutable caches.
#pragma once
#include "main.hpp"
#include "training/training_snapshot.hpp"
namespace football::training {
inline std::string ScenarioIdentity(const ScenarioConfig& scene) {
  snapshot::Require(scene.left_team.size() <= 11 && scene.right_team.size() <= 11,
                    "Training teams exceed identity budget");
  std::string bytes;
  auto u32 = [&](uint32_t value) { snapshot::detail::Append32(bytes, value); };
  auto i32 = [&](int32_t value) { u32(std::bit_cast<uint32_t>(value)); };
  auto f32 = [&](float value) {
    snapshot::Require(std::isfinite(value), "Nonfinite training scenario identity");
    u32(std::bit_cast<uint32_t>(value));
  };
  auto vector = [&](const blunted::Vector3& value) { for (int axis = 0; axis < 3; ++axis) f32(value.coords[axis]); };
  u32(1);
  vector(scene.ball_position);
  for (const auto* team : {&scene.left_team, &scene.right_team}) {
    u32(static_cast<uint32_t>(team->size()));
    for (const auto& player : *team) {
      i32(static_cast<int32_t>(player.role)); vector(player.position); vector(player.start_position);
      u32(player.lazy); u32(player.controllable);
    }
  }
  i32(scene.left_agents); i32(scene.right_agents);
  u32(scene.use_magnet); u32(scene.offsides); u32(scene.real_time);
  u32(scene.game_engine_random_seed); u32(scene.reverse_team_processing);
  f32(scene.left_team_difficulty); f32(scene.right_team_difficulty);
  u32(scene.deterministic); u32(scene.end_episode_on_score); u32(scene.end_episode_on_possession_change);
  u32(scene.end_episode_on_out_of_play); i32(scene.game_duration); u32(scene.control_all_players); i32(scene.second_half);
  snapshot::Require(bytes.size() <= snapshot::kMaxScenarioBytes, "Training scenario exceeds identity budget");
  return bytes;
}
// Validates the actual runtime dataset against the build's resource manifest.
std::string TrainingCompatibility(const GameEnv& env);
}  // namespace football::training
