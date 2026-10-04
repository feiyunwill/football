#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include "game_env.hpp"
#include "gametask.hpp"
#include "onthepitch/match.hpp"
#include "onthepitch/player/player.hpp"

#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace {

enum class Intent { none, pass, shot };

Intent Classify(e_FunctionType action) {
  if (action == e_FunctionType_ShortPass ||
      action == e_FunctionType_LongPass ||
      action == e_FunctionType_HighPass)
    return Intent::pass;
  if (action == e_FunctionType_Shot) return Intent::shot;
  return Intent::none;
}

struct PlayerWatch {
  Player* player = nullptr;
  int team = 0;
  e_FunctionType previous = e_FunctionType_None;
  unsigned long last_touch = 0;
  Intent pending = Intent::none;
};

struct Metrics {
  unsigned seed = 0;
  int frames = 0;
  unsigned long match_time_ms = 0;
  std::array<int, 2> score{};
  std::array<int, 2> pass_attempts{};
  std::array<int, 2> kicked_passes{};
  std::array<int, 2> shot_attempts{};
  std::array<int, 2> kicked_shots{};
  std::array<int, 2> fouls{};
  std::array<int, 2> invalid_intents{};
  int unattributed_fouls = 0;
  uint64_t final_hash = 0;
};

Metrics Play(unsigned seed, int frames) {
  GameEnv env;
  auto scenario = frame_sync::MakeDefaultScenario(0, 0, seed);
  scenario->left_team_difficulty = 1.0f;
  scenario->right_team_difficulty = 1.0f;
  scenario->game_duration = 3001;
  env.start_game(*scenario);
  env.state = game_running;

  Match* match = nullptr;
  std::vector<PlayerWatch> players;
  {
    ContextHolder guard(&env);
    match = env.context->gameTask->GetMatch();
    if (!match || !match->GetReferee())
      throw std::runtime_error("Missing real match or referee");
    for (int team = 0; team != 2; ++team) {
      std::vector<Player*> active;
      match->GetActiveTeamPlayers(team, active);
      for (Player* player : active)
        players.push_back({player, team, player->GetCurrentFunctionType(),
                           player->GetLastTouchTime_ms(), Intent::none});
    }
  }
  if (players.size() != 22)
    throw std::runtime_error("Expected two active 11-player teams");

  Metrics result;
  result.seed = seed;
  result.frames = frames;
  int previous_foul_type = 0;
  Player* previous_fouler = nullptr;
  for (int frame = 0; frame != frames; ++frame) {
    env.StepWithInput(nullptr, 0);
    for (auto& watch : players) {
      const auto action = watch.player->GetCurrentFunctionType();
      const auto touch = watch.player->GetLastTouchTime_ms();
      if (touch > watch.last_touch && watch.pending != Intent::none &&
          watch.player->GetLastTouchType() == e_TouchType_Intentional_Kicked) {
        if (watch.pending == Intent::pass)
          ++result.kicked_passes[watch.team];
        else
          ++result.kicked_shots[watch.team];
        watch.pending = Intent::none;
      }
      if (action != watch.previous) {
        if (watch.pending != Intent::none) {
          ++result.invalid_intents[watch.team];
          watch.pending = Intent::none;
        }
        watch.pending = Classify(action);
        if (watch.pending == Intent::pass)
          ++result.pass_attempts[watch.team];
        else if (watch.pending == Intent::shot)
          ++result.shot_attempts[watch.team];
      }
      watch.previous = action;
      watch.last_touch = touch;
    }
    const int foul_type = match->GetReferee()->GetCurrentFoulType();
    Player* fouler = foul_type ? match->GetReferee()->GetCurrentFoulPlayer()
                               : nullptr;
    if (foul_type && (!previous_foul_type || fouler != previous_fouler)) {
      bool attributed = false;
      for (const auto& watch : players) {
        if (watch.player == fouler) {
          ++result.fouls[watch.team];
          attributed = true;
          break;
        }
      }
      if (!attributed) ++result.unattributed_fouls;
    }
    previous_foul_type = foul_type;
    previous_fouler = fouler;
  }
  result.score = {match->GetScore(0), match->GetScore(1)};
  result.match_time_ms = match->GetMatchTime_ms();
  const auto digest = env.get_state_digest();
  result.final_hash = frame_sync::ComputeStateHash(digest.data(), digest.size());
  return result;
}

template <typename T>
void PrintPair(const char* name, const std::array<T, 2>& values) {
  std::cout << ",\"" << name << "\":[" << values[0] << ',' << values[1]
            << ']';
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 3) throw std::runtime_error("Usage: engine_ai_match_metrics SEED FRAMES");
    const auto seed = static_cast<unsigned>(std::stoul(argv[1]));
    const int frames = std::stoi(argv[2]);
    if (seed == 0 || frames < 3000 || frames > 12000)
      throw std::runtime_error("Seed or frame count outside acceptance range");
    const auto metrics = Play(seed, frames);
    std::ostringstream hash;
    hash << std::hex << std::setw(16) << std::setfill('0') << metrics.final_hash;
    std::cout << "{\"schema\":\"ai-match-metrics-v1\",\"seed\":" << seed
              << ",\"frames\":" << frames
              << ",\"match_time_ms\":" << metrics.match_time_ms
              << ",\"final_hash\":\"" << hash.str() << '"';
    PrintPair("score", metrics.score);
    PrintPair("pass_attempts", metrics.pass_attempts);
    PrintPair("kicked_passes", metrics.kicked_passes);
    PrintPair("shot_attempts", metrics.shot_attempts);
    PrintPair("kicked_shots", metrics.kicked_shots);
    PrintPair("fouls", metrics.fouls);
    PrintPair("invalid_intents", metrics.invalid_intents);
    std::cout << ",\"unattributed_fouls\":" << metrics.unattributed_fouls
              << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
