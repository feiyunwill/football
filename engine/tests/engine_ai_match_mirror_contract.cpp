#include "frame_sync/default_scenario.hpp"
#include "game_env.hpp"
#include "gametask.hpp"
#include "onthepitch/match.hpp"
#include "onthepitch/player/player.hpp"

#include <array>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
struct Result {
  std::array<int, 2> shots{};
  std::array<int, 2> kicked_shots{};
  std::array<int, 2> score{};
  bool operator==(const Result&) const = default;
};

Result Play(unsigned seed) {
  GameEnv env;
  auto scenario = frame_sync::MakeDefaultScenario(0, 0, seed);
  scenario->left_team_difficulty = 1.0f;
  scenario->right_team_difficulty = 1.0f;
  scenario->game_duration = 3001;
  env.start_game(*scenario);
  env.state = game_running;

  Match* match = nullptr;
  struct Watch {
    Player* player;
    int team;
    e_FunctionType previous;
    unsigned long touch;
    bool pending_shot = false;
  };
  std::vector<Watch> watched;
  {
    ContextHolder guard(&env);
    match = env.context->gameTask->GetMatch();
    for (int team = 0; team != 2; ++team) {
      std::vector<Player*> players;
      match->GetActiveTeamPlayers(team, players);
      for (Player* player : players)
        watched.push_back({player, team, player->GetCurrentFunctionType(),
                           player->GetLastTouchTime_ms()});
    }
  }
  if (watched.size() != 22) throw std::runtime_error("Expected 11v11 match");

  Result result;
  for (int frame = 0; frame != 3000; ++frame) {
    env.StepWithInput(nullptr, 0);
    for (auto& watch : watched) {
      const auto action = watch.player->GetCurrentFunctionType();
      const auto touch = watch.player->GetLastTouchTime_ms();
      if (touch > watch.touch && watch.pending_shot &&
          watch.player->GetLastTouchType() == e_TouchType_Intentional_Kicked) {
        ++result.kicked_shots[watch.team];
        watch.pending_shot = false;
      }
      if (action != watch.previous) {
        if (action == e_FunctionType_Shot) {
          ++result.shots[watch.team];
          watch.pending_shot = true;
        } else {
          watch.pending_shot = false;
        }
      }
      watch.previous = action;
      watch.touch = touch;
    }
  }
  result.score = {match->GetScore(0), match->GetScore(1)};
  return result;
}
}  // namespace

int main(int, char**) {
  try {
    const auto a = Play(43);
    const auto b = Play(47);
    const auto c = Play(49);
    const auto repeat = Play(43);
    const bool deterministic = a == repeat;
    const int left_shots = a.kicked_shots[0] + b.kicked_shots[0] + c.kicked_shots[0];
    const int right_shots = a.kicked_shots[1] + b.kicked_shots[1] + c.kicked_shots[1];
    const bool passed = deterministic && left_shots > 0 && right_shots > 0;
    std::cout << "{\"passed\":" << (passed ? "true" : "false")
              << ",\"assertions\":3,\"failed\":" << (3 - int(deterministic)
                  - int(left_shots > 0) - int(right_shots > 0))
              << ",\"skipped\":0,\"left_kicked_shots\":" << left_shots
              << ",\"right_kicked_shots\":" << right_shots << "}\n";
    return passed ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
