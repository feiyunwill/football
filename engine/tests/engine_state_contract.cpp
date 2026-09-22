// 2026-09-09: actual engine state/cache contracts, beyond isolated ECS tests.
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include "game_env.hpp"
#include "onthepitch/ecs_components.hpp"
#include "onthepitch/player/humanoid/humanoidbase.hpp"
#include "onthepitch/player/player.hpp"
#include "onthepitch/player/playerofficial.hpp"

#include <iostream>
#include <stdexcept>
#include <string>

namespace {
int assertions = 0;
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}

void CheckPlayerCaches(Match& match) {
  auto& world = match.GetEcsWorld();
  for (auto entity : match.GetEcsPlayerEntities()) {
    const auto* ref = world.GetComponent<PlayerRef>(entity);
    Require(ref && ref->player, "Missing player identity");
    auto* humanoid = ref->player->CastHumanoid();
    if (!humanoid) continue;
    const auto* physics = world.GetComponent<PlayerPhysicsComponent>(entity);
    const auto* player = world.GetComponent<PlayerStateComponent>(entity);
    const auto* animation = world.GetComponent<HumanoidStateComponent>(entity);
    Require(physics && player && animation, "Missing state cache");
    Require(physics->position == humanoid->GetSpatialState().position,
            "Player physics cache differs from current simulation state");
    Require(player->position == ref->player->GetPosition(), "Player position cache is stale");
    Require(animation->current_frame == humanoid->GetFrameNum(), "Animation cache is stale");
    Require(player->has_possession == ref->player->HasPossession(), "Possession cache is stale");
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    GameEnv environment;
    environment.game_config.render = false;
    const auto seed = argc > 1 ? static_cast<uint32_t>(std::stoul(argv[1])) : 42u;
    auto scenario = frame_sync::MakeDefaultScenario(1, 1, seed);
    environment.start_game(*scenario);
    environment.state = game_running;
    ContextHolder context(&environment);
    auto match = environment.context->gameTask->GetMatch();
    for (int frame = 0; frame < 20; ++frame) environment.step();
    const auto snapshot = environment.get_state("");
    const auto digest = environment.get_state_digest();
    auto& world = match->GetEcsWorld();
    for (auto entity : match->GetEcsPlayerEntities()) {
      if (auto* physics = world.GetComponent<PlayerPhysicsComponent>(entity))
        physics->position = Vector3(1000, 1000, 0);
      if (auto* player = world.GetComponent<PlayerStateComponent>(entity))
        player->position = Vector3(2000, 2000, 0);
      if (auto* animation = world.GetComponent<HumanoidStateComponent>(entity))
        animation->current_frame = -99;
    }
    environment.set_state(snapshot);
    Require(environment.get_state_digest() == digest, "Cache rebuilding changed simulation state");
    CheckPlayerCaches(*match);
    const int initial_official_frame = match->GetOfficials()->GetReferee()->CastHumanoid()->GetFrameNum();
    bool official_advanced = false;
    for (int frame = 0; frame < 30; ++frame) {
      environment.action(frame % 2 ? game_left : game_right, true, 0);
      environment.step();
      CheckPlayerCaches(*match);
      official_advanced |= match->GetOfficials()->GetReferee()->CastHumanoid()->GetFrameNum() != initial_official_frame;
    }
    Require(official_advanced, "Officials never executed their animation process");
    const auto final_digest = environment.get_state_digest();
    environment.set_state(snapshot);
    for (int frame = 0; frame < 30; ++frame) {
      environment.action(frame % 2 ? game_left : game_right, true, 0);
      environment.step();
    }
    Require(environment.get_state_digest() == final_digest, "Real gameplay diverged after rollback");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Engine state contract: " << error.what() << std::endl;
    return 1;
  }
}
