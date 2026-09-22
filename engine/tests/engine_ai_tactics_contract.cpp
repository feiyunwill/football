
#include <iostream>
#include <type_traits>

#include "ai/ai_tactics.hpp"
#include "frame_sync/bot_takeover.hpp"
using namespace ai;
namespace fs = frame_sync;
unsigned assertions = 0;
void Require(bool v, const char* m) {
  ++assertions;
  if (!v) throw std::runtime_error(m);
}
bool Same(const TacticalDecision& a, const TacticalDecision& b) {
  return a.direction == b.direction && a.weights == b.weights &&
         a.buttons == b.buttons && a.pass_target == b.pass_target &&
         a.action == b.action;
}
void Valid(const TacticalDecision& d) {
  Require(std::isfinite(d.direction[0]) && std::isfinite(d.direction[1]),
          "Nonfinite direction");
  const float len = std::hypot(d.direction[0], d.direction[1]);
  Require(len < .00001f || std::abs(len - 1.f) < .00001f, "Nonunit movement");
  Require((d.buttons & ~std::uint16_t(0x7ff)) == 0, "Unknown button");
  float sum = 0;
  for (auto w : d.weights) {
    Require(std::isfinite(w) && w >= 0 && w <= 1, "Invalid weight");
    sum += w;
  }
  Require(sum == 0 || std::abs(sum - 1) < .00001, "Invalid probability sum");
}
TacticalFrame Fixture() {
  TacticalFrame f;
  f.slots = 2;
  f.controlled_team = {0, 1};
  f.controlled_player[0] = 1;
  f.controlled_player[1] = 1;
  f.player_count = {3, 3};
  f.duration_seconds = 300;
  f.remaining_seconds = 200;
  f.in_play = true;
  f.owner_team = 0;
  f.owner_player = 1;
  f.ball = {0, 0};
  for (unsigned side = 0; side < 2; ++side)
    for (unsigned i = 0; i < 3; ++i) {
      auto& p = f.players[side][i];
      p.active = true;
      p.role = 9;
      p.position = {side ? 45.f : -40.f, float(i) * 10.f};
    }
  f.players[0][1].position = {0, 0};
  f.players[0][2].position = {20, 0};
  return f;
}
void Policy() {
  static_assert(std::is_trivially_copyable_v<TacticalFrame>);
  TacticsController controller;
  auto f = Fixture();
  auto pass = controller.Update(f, 0, 1);
  Valid(pass);
  Require(pass.action == TacticalAction::Pass && pass.pass_target == 2 &&
              pass.buttons == 4,
          "Available progressive pass not selected");
  f.players[0][2].position = {50, 0};
  auto offside = controller.Update(f, 0, 1);
  Require(
      offside.pass_target == -1 && offside.action == TacticalAction::Dribble,
      "Offside receiver accepted");
  f.players[0][2].position = {20, 0};
  f.players[1][0].position = {10, 0};
  Require(controller.Update(f, 0, 1).pass_target == -1,
          "Blocked passing lane accepted");
  f = Fixture();
  f.players[0][2].active = false;
  Require(controller.Update(f, 0, 1).pass_target == -1,
          "Self or inactive teammate selected");
  f.players[0][1].position = {42, 0};
  f.ball = {42, 0};
  f.players[1][0].position = {45, 15};
  auto shot = controller.Update(f, 0, 1);
  Valid(shot);
  Require(shot.action == TacticalAction::Shoot && shot.buttons == 8,
          "Clear close shot missing");
  f.in_play = false;
  auto stopped = controller.Update(f, 0, 1);
  Valid(stopped);
  Require(stopped.buttons == 0 && stopped.direction == std::array<float, 2>{} &&
              stopped.weights == std::array<float, 4>{},
          "Stale shooting state during stoppage");
  f.in_play = true;
  Require(Same(shot, controller.Update(f, 0, 1)),
          "Repeated frame accumulated decision weights");
  auto cooling = controller.Update(f, 0, 1, false);
  Require((cooling.buttons & 15) == 0, "Kick cooldown ignored");
  f.players[0][1].stamina = 0;
  auto tired = controller.Update(f, 0, 1, false);
  Require((tired.buttons & 512) == 0, "Exhausted player sprints");
  f.set_piece = true;
  f.restart_team = 0;
  f.restart_player = 1;
  f.restart_ready = false;
  Require(controller.Update(f, 0, 1).buttons == 0, "Premature restart");
  f.restart_ready = true;
  Require(controller.Update(f, 0, 1).buttons == 4,
          "Actual restart taker did not restart");
  Require(controller.Update(f, 0, 2).buttons == 0,
          "Non-taker performs restart");
  Require(controller.Update(f, 1, 1).buttons == 0, "Opponent performs restart");
  f.remaining_seconds = 0;
  Require(controller.Update(f, 0, 1).action == TacticalAction::Neutral,
          "Finished match not neutral");
  f = Fixture();
  f.owner_team = 1;
  f.owner_player = 0;
  f.ball = {2, 0};
  f.players[1][0].position = f.ball;
  auto defend = controller.Update(f, 0, 1);
  Require(defend.action == TacticalAction::Defend && (defend.buttons & 64),
          "Opponent possession ignored");
  f.owner_team = -1;
  f.owner_player = -1;
  Require((controller.Update(f, 0, 1).buttons & 64) == 0,
          "Pressure command for free ball");
  // Symmetry includes swapped score, possession, controller and player
  // identities.
  for (unsigned i = 0; i < 600; ++i) {
    f = Fixture();
    f.players[0][1].position = {float(int(i % 101) - 50),
                                float(int(i % 51) - 25)};
    f.ball = f.players[0][1].position;
    f.remaining_seconds = i % 2 ? 20 : 200;
    f.scores = {int(i % 3), int((i + 1) % 3)};
    f.players[0][1].stamina = float(i % 11) / 10;
    auto a = controller.Update(f, 0, 1);
    auto fresh = TacticsController{}.Update(f, 0, 1);
    Require(Same(a, fresh), "History affected decision");
    Valid(a);
    Require(a.pass_target != 1, "Self pass emitted");
    auto mirrored = f;
    std::swap(mirrored.players[0], mirrored.players[1]);
    std::swap(mirrored.player_count[0], mirrored.player_count[1]);
    std::swap(mirrored.scores[0], mirrored.scores[1]);
    for (auto& side : mirrored.players)
      for (auto& p : side)
        for (unsigned xy = 0; xy < 2; ++xy) {
          p.position[xy] *= -1;
          p.velocity[xy] *= -1;
        }
    for (auto& x : mirrored.ball) x *= -1;
    for (auto& x : mirrored.ball_velocity) x *= -1;
    mirrored.owner_team = 1;
    auto b = TacticsController{}.Update(mirrored, 1, 1);
    Require(a.action == b.action && a.buttons == b.buttons &&
                a.pass_target == b.pass_target && a.weights == b.weights,
            "Team side changed tactical choice");
    Require(std::abs(a.direction[0] + b.direction[0]) < 1e-6 &&
                std::abs(a.direction[1] + b.direction[1]) < 1e-6,
            "Team direction failed symmetry");
  }
  for (unsigned variant = 0; variant < 9; ++variant) {
    f = Fixture();
    switch (variant) {
      case 0:
        f.players[0][0].position[0] = NAN;
        break;
      case 1:
        f.slots = 23;
        break;
      case 2:
        f.player_count[0] = 12;
        break;
      case 3:
        f.controlled_player[0] = 3;
        break;
      case 4:
        f.players[0][0].stamina = 1.1;
        break;
      case 5:
        f.duration_seconds = 0;
        break;
      case 6:
        f.own_goal_x = {0, .5};
        break;
      case 7:
        f.owner_team = 2;
        break;
      case 8:
        f.pitch_half_y = .1;
        break;
    }
    bool rejected = false;
    try {
      controller.Update(f, 0, 1);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    Require(rejected, "Invalid observation accepted");
  }
  fs::BotTakeoverManager bots(50);
  bots.Takeover(0, 0);
  fs::BotGameSnapshot snapshot;
  snapshot.tactics = Fixture();
  auto first = bots.GenerateInput(0, snapshot);
  Require(first.buttons == 4, "Takeover did not use tactical pass");
  snapshot.tactics->time_ms = 20;
  Require((bots.GenerateInput(0, snapshot).buttons & 15) == 0,
          "Takeover cooldown missing");
  snapshot.tactics->time_ms = 500;
  Require(bots.GenerateInput(0, snapshot).buttons == 4,
          "Simulation cooldown failed to expire");
  snapshot.unavailable_slots = 1;
  Require(bots.GenerateInput(0, snapshot).buttons == 0,
          "Unavailable takeover not neutral");
  Require(bots.GenerateInput(1, snapshot).buttons == 0,
          "Unassigned slot taken over");
  f = Fixture();
  f.players[0][1].position = {25, 0};
  f.ball = {25, 0};
  f.players[0][2].position = {50, 0};
  for (unsigned i = 0; i < 3; ++i)
    f.players[1][i].position = {45, 20.f + i * 5};
  Require(controller.Update(f, 0, 1).pass_target == -1,
          "Offside receiver accepted within pass range and with an open lane");
  f.offsides = false;
  Require(controller.Update(f, 0, 1).pass_target == 2,
          "Disabled offside rule blocked an otherwise legal pass");
  f.offsides = true;
  f.player_count[1] = 1;
  f.controlled_player[1] = 0;  // The keeper-only fixture has only roster index zero.
  Require(controller.Update(f, 0, 1).pass_target == 2,
          "Keeper-only referee mode incorrectly applied offside");
  Require(sizeof(TacticalFrame) <= 2048,
          "Unbounded tactical observation storage");
  fs::BotTakeoverManager bounded_bots;
  for (unsigned slot = 0; slot < 22; ++slot)
    bounded_bots.Takeover(slot, slot < 11 ? 0 : 1);
  Require(bounded_bots.bot_count() == 22, "Complete fixed roster not retained");
  const auto ordered = bounded_bots.GetBotSlots();
  for (unsigned slot = 0; slot < 22; ++slot)
    Require(ordered[slot] == slot, "Bot iteration is not stable");
  for (auto [slot, side] : {std::pair{22, 0}, std::pair{65535, 1},
                            std::pair{0, -1}, std::pair{0, 2}}) {
    bool rejected = false;
    try {
      bounded_bots.Takeover(slot, side);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    Require(rejected && bounded_bots.bot_count() == 22,
            "Invalid identity changed retained AI roster");
  }
  snapshot = fs::BotGameSnapshot{};
  snapshot.num_slots = 1;
  bool malformed = false;
  try {
    bots.GenerateInput(0, snapshot);
  } catch (const std::invalid_argument&) {
    malformed = true;
  }
  Require(malformed, "Truncated legacy position array accepted");
  snapshot.player_positions = {0, 0};
  snapshot.ball_x = NAN;
  malformed = false;
  try {
    bots.GenerateInput(0, snapshot);
  } catch (const std::invalid_argument&) {
    malformed = true;
  }
  Require(malformed, "Nonfinite legacy observation accepted");
  snapshot = fs::BotGameSnapshot{};
  snapshot.tactics = Fixture();
  snapshot.tactics->time_ms = UINT64_MAX;
  malformed = false;
  try {
    bots.GenerateInput(0, snapshot);
  } catch (const std::invalid_argument&) {
    malformed = true;
  }
  Require(malformed, "Tactical cooldown overflow accepted");
}
int main() {
  try {
    Policy();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"symmetry_cases\":600}\n";
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
