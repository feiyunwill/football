// 2026-09-09: one initial state for headless, TCP and UDP engine entry points.
#ifndef GFOOTBALL_FRAME_SYNC_DEFAULT_SCENARIO_HPP
#define GFOOTBALL_FRAME_SYNC_DEFAULT_SCENARIO_HPP
#include "main.hpp"
#include <stdexcept>
namespace frame_sync {
inline std::shared_ptr<ScenarioConfig> MakeDefaultScenario(uint16_t left_agents,
                                           uint16_t right_agents,
                                           uint32_t seed) {
  if (left_agents > 11 || right_agents > 11)
    throw std::invalid_argument("each team supports at most 11 controlled players");
  auto sc = ScenarioConfig::make();
  sc->left_agents = left_agents;
  sc->right_agents = right_agents;
  sc->game_engine_random_seed = seed;
  sc->real_time = false;
  sc->deterministic = true;
  sc->end_episode_on_score = false;
  sc->game_duration = 3000;
  sc->reverse_team_processing = bool(seed % 2);

  // Default 4-4-2 formation
  sc->left_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };
  sc->right_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, false),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };

  // Both teams need controllable players for their assigned slots.
  for (auto& player : sc->left_team) player.controllable = true;
  for (auto& player : sc->right_team) player.controllable = true;
  return sc;
}

}
#endif
