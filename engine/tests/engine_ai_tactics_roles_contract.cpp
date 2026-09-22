
#include <iostream>

#include "ai/ai_tactics.hpp"
using namespace ai;
unsigned assertions = 0, failed = 0;
void Require(bool value, const char* label) {
  ++assertions;
  if (!value) {
    ++failed;
    if (failed < 6) std::cout << "{\"failed\":\"" << label << "\"}\n";
  }
}
TacticalFrame Base() {
  TacticalFrame f;
  f.player_count = {3, 3};
  f.duration_seconds = 300;
  f.remaining_seconds = 200;
  f.in_play = true;
  f.owner_team = 0;
  f.owner_player = 1;
  for (unsigned side = 0; side < 2; ++side)
    for (unsigned i = 0; i < 3; ++i) {
      auto& p = f.players[side][i];
      p.active = true;
      p.role = i ? 9 : 0;
      p.position = {float(side ? 40 : -40), float(i) * 10};
    }
  f.players[0][0].position = {-50, 0};
  f.players[0][1].position = {0, 0};
  f.players[0][2].position = {20, 0};
  f.ball = {0, 0};
  return f;
}
TacticalFrame Mirror(TacticalFrame f) {
  std::swap(f.players[0], f.players[1]);
  std::swap(f.player_count[0], f.player_count[1]);
  std::swap(f.scores[0], f.scores[1]);
  for (auto& side : f.players)
    for (auto& p : side)
      for (unsigned axis = 0; axis < 2; ++axis) {
        p.position[axis] *= -1;
        p.velocity[axis] *= -1;
      }
  for (auto& v : f.ball) v *= -1;
  for (auto& v : f.ball_velocity) v *= -1;
  f.owner_team = f.owner_team < 0 ? -1 : 1 - f.owner_team;
  f.restart_team = f.restart_team < 0 ? -1 : 1 - f.restart_team;
  f.own_goal_x = {-f.own_goal_x[1], -f.own_goal_x[0]};
  return f;
}
int main() {
  auto f = Base();
  auto keeper = TacticsController{}.Update(f, 0, 0);
  Require(keeper.action == TacticalAction::Defend && keeper.direction[0] < 0,
          "Keeper left its goal to support");
  for (unsigned index = 0; index < 600; ++index) {
    f = Base();
    f.ball = {float(int(index % 81) - 40), float(int(index % 51) - 25)};
    f.ball_velocity = {2, -1};
    f.owner_team = int(index % 3) - 1;
    f.owner_player = f.owner_team < 0 ? -1 : 1;
    for (int actor = 0; actor < 3; ++actor) {
      auto a = TacticsController{}.Update(f, 0, actor);
      auto b = TacticsController{}.Update(Mirror(f), 1, actor);
      Require(a.action == b.action && a.buttons == b.buttons &&
                  a.pass_target == b.pass_target && a.weights == b.weights,
              "Mirroring changed role or action");
      Require(std::abs(a.direction[0] + b.direction[0]) < 1e-6 &&
                  std::abs(a.direction[1] + b.direction[1]) < 1e-6,
              "Mirroring changed relative direction");
    }
  }
  std::cout << "{\"passed\":" << (failed ? "false" : "true")
            << ",\"assertions\":" << assertions << ",\"failed\":" << failed
            << ",\"skipped\":0,\"role_mirror_cases\":1800}\n";
  if (failed) {
    std::cerr << "Role or mirror invariants failed\n";
    return 1;
  }
}
