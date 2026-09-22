
#include <cmath>
#include <iostream>

#include "frame_sync/engine_tcp_bridge.hpp"
#include "gametask.hpp"
#include "onthepitch/player/player.hpp"
namespace fs = frame_sync;
static_assert(e_ButtonFunction_ShortPass == 2 && e_ButtonFunction_Shot == 3 &&
              e_ButtonFunction_Pressure == 6 && e_ButtonFunction_Sprint == 9);
static_assert(e_PlayerRole_GK == 0 && e_PlayerRole_DM == 4 &&
              e_PlayerRole_AM == 8 && e_PlayerRole_CF == 9);
unsigned assertions = 0, frames = 0, nonzero_actors = 0, restarts = 0;
void Require(bool v, const char* m) {
  ++assertions;
  if (!v) throw std::runtime_error(m);
}
void Check(unsigned seed, unsigned physics) {
  GameEnv env;
  env.game_config.render = false;
  env.game_config.physics_steps_per_frame = physics;
  auto scenario =
      fs::MakeNativeMatchScenario(fs::NativeMatchContract(seed, 2, 2));
  env.start_game(*scenario);
  env.state = game_running;
  bool mismatch = false;
  try {
    fs::MakeGameEnvBotObserver(&env, 1, 1)();
  } catch (const std::invalid_argument&) {
    mismatch = true;
  }
  Require(mismatch, "Observer accepted foreign slot layout");
  auto engine = fs::MakeGameEnvCallbacks(&env);
  auto observe = fs::MakeGameEnvBotObserver(&env, 2, 2);
  fs::BotTakeoverManager bots(100 / physics);
  for (unsigned i = 0; i < 4; ++i) bots.Takeover(i, i < 2 ? 0 : 1);
  for (unsigned tick = 0; tick < 240; ++tick) {
    const auto info = env.get_info();
    const auto digest = env.get_state_digest();
    const auto f = ai::ObserveTacticalFrame(env);
    const auto snapshot = observe();
    Require(f.offsides == scenario->offsides,
            "Offside configuration not observed");
    Require(env.get_state_digest() == digest,
            "Observation mutated actual match");
    Require(snapshot.tactics.has_value(),
            "Production observer omitted tactical frame");
    Require(f.slots == 4 && f.player_count[0] == 11 && f.player_count[1] == 11,
            "Roster or controller count mismatch");
    Require(f.own_goal_x == std::array<float, 2>{-pitchHalfW, pitchHalfW},
            "Goal direction differs in normal/reverse engine");
    Require(f.time_ms == std::uint64_t(std::max(0, info.step)) * physics * 10,
            "Simulation time mismatch");
    Require(std::abs(f.remaining_seconds -
                     float(scenario->game_duration - std::max(0, info.step)) *
                         physics * .01f) < .001,
            "Remaining duration mismatch");
    Require(f.scores == std::array<int, 2>{info.left_goals, info.right_goals},
            "Score mismatch");
    Require(f.owner_team == info.ball_owned_team &&
                f.owner_player == info.ball_owned_player,
            "Ownership mismatch");
    std::array<fs::SlotInput, 4> inputs;
    for (unsigned slot = 0; slot < 4; ++slot) {
      unsigned side = slot / 2, index = slot % 2;
      const auto& controls =
          side ? info.right_controllers : info.left_controllers;
      const auto& team = side ? info.right_team : info.left_team;
      Require(f.controlled_player[slot] == controls[index].controlled_player &&
                  f.controlled_team[slot] == side,
              "Wrong actual selected actor");
      if (f.controlled_player[slot] >= 0) {
        unsigned actor = f.controlled_player[slot];
        const auto& p = team[actor];
        nonzero_actors += actor != 0;
        Require(f.players[side][actor].position ==
                    std::array<float, 2>{p.player_position[0],
                                         p.player_position[1]},
                "Actor coordinates changed");
        Require(f.players[side][actor].stamina == 1 - p.tired_factor,
                "Stamina not actual fatigue");
        Require(f.players[side][actor].velocity ==
                    std::array<float, 2>{p.player_direction[0] * physics,
                                         p.player_direction[1] * physics},
                "Velocity scale mismatch");
      }
      inputs[slot] = bots.GenerateInput(slot, snapshot);
      Require(fs::IsValidSlotInput(inputs[slot]),
              "Generated actual input invalid");
      if (f.controlled_player[slot] < 0)
        Require(inputs[slot] == fs::SlotInput::Default(),
                "No selection generated action");
    }
    restarts += f.set_piece;
    engine.step_frame(inputs);
    ++frames;
  }
  {
    ContextHolder guard(&env);
    auto* match = env.context->gameTask->GetMatch();
    auto saved = env.get_state("");
    auto digest = env.get_state_digest();
    match->SetMatchPhase(e_MatchPhase_2ndHalf);
    Require(ai::ObserveTacticalFrame(env).second_half,
            "Second half not observed");
    env.set_state(saved);
    Require(env.get_state_digest() == digest, "Phase test failed to restore");
    match->StopPlay();
    match->StopSetPiece();
    for (unsigned side = 0; side < 2; ++side) {
      auto* hid = GetControllers()[side * MAX_PLAYERS];
      for (unsigned b = 0; b < unsigned(e_ButtonFunction_Size); ++b)
        hid->SetButton(static_cast<e_ButtonFunction>(b), true);
      hid->SetDirection(Vector3(1, 0, 0));
      ai::TacticsController legacy(match, match->GetTeam(side), hid);
      legacy.Update();
      Require(hid->GetOriginalDirection() == Vector3(0.f),
              "Bound HID left stale direction");
      for (unsigned b = 0; b < unsigned(e_ButtonFunction_Size); ++b)
        Require(!hid->GetButton(static_cast<e_ButtonFunction>(b)),
                "Bound HID left stale button");
    }
    env.set_state(saved);
    Require(env.get_state_digest() == digest, "HID test failed to restore");
  }
  std::cout << "{\"seed\":" << seed << ",\"physics\":" << physics
            << ",\"actual_frames\":240}\n";
}
int main(int, char**) {
  try {
    GameEnv unopened;
    bool rejected = false;
    try {
      ai::ObserveTacticalFrame(unopened);
    } catch (const std::logic_error&) {
      rejected = true;
    }
    Require(rejected, "Unstarted observer accepted");
    for (unsigned seed : {42u, 43u})
      for (unsigned physics : {2u, 10u}) Check(seed, physics);
    Require(nonzero_actors > 0,
            "Fixture did not control a nonzero roster index");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"actual_gameenv\":true,\"frames\":" << frames
              << ",\"nonzero_actors\":" << nonzero_actors
              << ",\"restarts\":" << restarts << "}\n";
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
