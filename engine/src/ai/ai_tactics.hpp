// 2026-09-14: bounded shared decisions for real controlled players.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>
class Match;
class Team;
class AIControlledKeyboard;
struct GameEnv;
namespace ai {
struct TacticalPlayer {
  TacticalPlayer() = default;
  ~TacticalPlayer() = default;
  TacticalPlayer(const TacticalPlayer&) = default;
  TacticalPlayer& operator=(const TacticalPlayer&) = default;
  TacticalPlayer(TacticalPlayer&&) = default;
  TacticalPlayer& operator=(TacticalPlayer&&) = default;
  std::array<float, 2> position{}, velocity{};
  float stamina = 1;
  int role = 0;
  bool active = false;
};
struct TacticalFrame {
  TacticalFrame() = default;
  ~TacticalFrame() = default;
  TacticalFrame(const TacticalFrame&) = default;
  TacticalFrame& operator=(const TacticalFrame&) = default;
  TacticalFrame(TacticalFrame&&) = default;
  TacticalFrame& operator=(TacticalFrame&&) = default;
  std::array<std::array<TacticalPlayer, 11>, 2> players{};
  std::array<unsigned, 2> player_count{};
  std::array<int, 22> controlled_player = [] {
    std::array<int, 22> a{};
    a.fill(-1);
    return a;
  }();
  std::array<unsigned, 22> controlled_team{};
  std::array<int, 2> scores{};
  std::array<float, 2> own_goal_x{-55.f, 55.f};
  std::array<float, 2> ball{}, ball_velocity{};
  unsigned slots = 0;
  float pitch_half_y = 36, goal_half_width = 3.7f;
  float remaining_seconds = 0, duration_seconds = 0;
  std::uint64_t time_ms = 0;
  std::uint32_t seed = 0;
  int owner_team = -1, owner_player = -1;
  int restart_team = -1, restart_player = -1;
  bool in_play = false, set_piece = false, restart_ready = false,
       second_half = false, offsides = true;
  void Validate() const {
    auto bounded = [](float x) {
      return std::isfinite(x) && std::abs(x) <= 1000000.f;
    };
    if (slots > 22 || player_count[0] > 11 || player_count[1] > 11 ||
        !bounded(own_goal_x[0]) || !bounded(own_goal_x[1]) ||
        std::abs(own_goal_x[0] - own_goal_x[1]) <= 1.f ||
        !bounded(pitch_half_y) || pitch_half_y <= .5f ||
        !bounded(goal_half_width) || goal_half_width <= 0 ||
        goal_half_width > pitch_half_y || !std::isfinite(duration_seconds) ||
        duration_seconds <= 0 || !std::isfinite(remaining_seconds) ||
        remaining_seconds < 0 || remaining_seconds > duration_seconds ||
        time_ms > std::numeric_limits<std::uint64_t>::max() - 500 ||
        scores[0] < 0 || scores[1] < 0)
      throw std::invalid_argument("Invalid tactical match bounds");
    for (auto value : ball)
      if (!bounded(value)) throw std::invalid_argument("Invalid tactical ball");
    for (auto value : ball_velocity)
      if (!bounded(value))
        throw std::invalid_argument("Invalid tactical ball velocity");
    auto identity = [&](int side, int player) {
      return (side == -1 && player == -1) ||
             (side >= 0 && side < 2 && player >= 0 &&
              unsigned(player) < player_count[side]);
    };
    if (!identity(owner_team, owner_player) ||
        !identity(restart_team, restart_player))
      throw std::invalid_argument("Invalid tactical player identity");
    for (unsigned side = 0; side < 2; ++side)
      for (unsigned i = 0; i < player_count[side]; ++i) {
        const auto& p = players[side][i];
        for (float x : p.position)
          if (!bounded(x))
            throw std::invalid_argument("Invalid tactical player position");
        for (float x : p.velocity)
          if (!bounded(x))
            throw std::invalid_argument("Invalid tactical player velocity");
        if (!std::isfinite(p.stamina) || p.stamina < 0 || p.stamina > 1 ||
            p.role < 0 || p.role > 9)
          throw std::invalid_argument("Invalid tactical player attributes");
      }
    for (unsigned i = 0; i < slots; ++i)
      if (controlled_team[i] > 1 || controlled_player[i] < -1 ||
          (controlled_player[i] >= 0 &&
           unsigned(controlled_player[i]) >= player_count[controlled_team[i]]))
        throw std::invalid_argument("Invalid tactical controlled slot");
  }
};
enum class TacticalAction {
  Neutral,
  Dribble,
  Pass,
  Shoot,
  Defend,
  Support,
  Restart
};
struct TacticalDecision {
  TacticalDecision() = default;
  ~TacticalDecision() = default;
  TacticalDecision(const TacticalDecision&) = default;
  TacticalDecision& operator=(const TacticalDecision&) = default;
  TacticalDecision(TacticalDecision&&) = default;
  TacticalDecision& operator=(TacticalDecision&&) = default;
  std::array<float, 2> direction{};
  std::array<float, 4>
      weights{};  // dribble, pass, shoot, defend; rebuilt every call
  std::uint16_t buttons = 0;
  int pass_target = -1;
  TacticalAction action = TacticalAction::Neutral;
};
TacticalFrame ObserveTacticalFrame(GameEnv& env);
class TacticsController {
 public:
  TacticsController() = default;
  TacticsController(Match* match, Team* team, AIControlledKeyboard* hid);
  ~TacticsController() = default;
  TacticsController(const TacticsController&) = default;
  TacticsController& operator=(const TacticsController&) = default;
  TacticsController(TacticsController&&) = default;
  TacticsController& operator=(TacticsController&&) = default;
  enum class Tactic { kAttack, kDefend, kTransition, kSetPiece };
  Tactic GetCurrentTactic() const { return current_tactic_; }
  void Update();  // Actual bound-HID adapter; network owners consume the pure
                  // decision below.
  TacticalDecision Update(const TacticalFrame& f, unsigned team, int actor,
                          bool kick_ready = true) {
    f.Validate();
    if (team > 1 || actor < -1 ||
        (actor >= 0 && unsigned(actor) >= f.player_count[team]))
      throw std::invalid_argument("Invalid tactical actor");
    TacticalDecision result;
    current_tactic_ = Tactic::kDefend;
    if (actor < 0 || !f.players[team][actor].active || f.remaining_seconds == 0)
      return result;
    const auto& self = f.players[team][actor];
    const float own = f.own_goal_x[team], goal = f.own_goal_x[1 - team];
    const float sign = goal > own ? 1.f : -1.f, center = (own + goal) * .5f;
    const auto goal_target = std::array<float, 2>{
        goal, std::clamp(-self.position[1] * .15f, -f.goal_half_width * .6f,
                         f.goal_half_width * .6f)};
    const float ball_distance = Distance(self.position, f.ball);
    auto point = [&](std::array<float, 2> target) {
      target[0] = std::clamp(target[0], std::min(own, goal) + .5f,
                             std::max(own, goal) - .5f);
      target[1] =
          std::clamp(target[1], -f.pitch_half_y + .5f, f.pitch_half_y - .5f);
      result.direction = Direction(self.position, target);
    };
    if (f.set_piece) {
      current_tactic_ = Tactic::kSetPiece;
      if (!f.restart_ready || f.restart_team != int(team) ||
          f.restart_player != actor)
        return result;
      result.action = TacticalAction::Restart;
      if (ball_distance > 1.5f) {
        point(f.ball);
        return result;
      }
      point(goal_target);
      if (kick_ready) result.buttons = std::uint16_t(1u << 2);
      return result;
    }
    if (!f.in_play) return result;
    const bool has_ball = f.owner_team == int(team) && f.owner_player == actor;
    if (!has_ball) {
      unsigned nearest = unsigned(actor);
      float nearest_distance = ball_distance;
      for (unsigned i = 0; i < f.player_count[team]; ++i) {
        const auto& teammate = f.players[team][i];
        if (!teammate.active) continue;
        const float distance = Distance(teammate.position, f.ball);
        // A keeper guarding a distant ball must not prevent an outfielder
        // pressing.
        if (teammate.role == 0 && distance > 10.f) continue;
        if (distance < nearest_distance ||
            (distance == nearest_distance && i < nearest)) {
          nearest = i;
          nearest_distance = distance;
        }
      }
      if (self.role == 0 &&
          (ball_distance > 10.f || nearest != unsigned(actor) ||
           f.owner_team == int(team))) {
        result.action = TacticalAction::Defend;
        result.weights[3] = 1;
        point(
            {own + sign * 4.f, std::clamp(f.ball[1] * .35f, -f.goal_half_width,
                                          f.goal_half_width)});
        return result;
      }
      if (f.owner_team == int(team) || nearest != unsigned(actor)) {
        const bool attacking = f.owner_team == int(team);
        result.action =
            attacking ? TacticalAction::Support : TacticalAction::Defend;
        current_tactic_ = attacking ? Tactic::kAttack : Tactic::kDefend;
        if (!attacking) result.weights[3] = 1;
        const float offset =
            self.role <= 4 ? -18.f : (self.role <= 8 ? -8.f : 5.f);
        const float lane = (actor % 2 ? 1.f : -1.f) * 6.f * sign;
        float target_x = f.ball[0] + sign * offset;
        // Stay level with the allowed line while waiting for a teammate's pass.
        if (attacking) {
          const float limit = std::max(0.f, OffsideLine(f, team, sign, center));
          target_x =
              center + sign * std::min((target_x - center) * sign, limit);
        }
        point({target_x, f.ball[1] * .35f + self.position[1] * .35f + lane});
      } else {
        result.action = TacticalAction::Defend;
        current_tactic_ = Tactic::kTransition;
        result.weights[3] = 1;
        point({f.ball[0] + f.ball_velocity[0] * .2f,
               f.ball[1] + f.ball_velocity[1] * .2f});
        if (self.stamina > .25f && ball_distance > 3.f)
          result.buttons |= std::uint16_t(1u << 9);
        if (f.owner_team == int(1 - team) && ball_distance < 4.f)
          result.buttons |= std::uint16_t(1u << 6);
      }
      return result;
    }
    current_tactic_ = Tactic::kAttack;
    const float goal_distance = Distance(self.position, goal_target);
    const bool late = f.remaining_seconds <= f.duration_seconds * .1f;
    const int score_diff = f.scores[team] - f.scores[1 - team];
    const auto [target, pass_score] =
        PassTarget(f, team, unsigned(actor), sign, center);
    const float pressure =
        1.f -
        std::clamp(NearestOpponent(f, team, self.position) / 7.f, 0.f, 1.f);
    result.weights[0] = .50f + (1.f - pressure) * .15f;
    if (target >= 0 && kick_ready)
      result.weights[1] = .35f + .40f * pass_score + .20f * pressure;
    if (goal_distance < 26.f && std::abs(self.position[1]) < 18.f && kick_ready)
      result.weights[2] = .55f + .4f * (1.f - goal_distance / 26.f);
    if (late && score_diff > 0) {
      result.weights[1] *= 1.2f;
      result.weights[2] *= .8f;
    }
    if (late && score_diff < 0) {
      result.weights[2] *= 1.2f;
      result.weights[0] *= .9f;
    }
    float sum = 0;
    for (float w : result.weights) sum += w;
    for (auto& w : result.weights) w /= sum;
    const unsigned action = unsigned(
        std::max_element(result.weights.begin(), result.weights.end()) -
        result.weights.begin());
    if (action == 1) {
      result.action = TacticalAction::Pass;
      result.pass_target = target;
      point(f.players[team][target].position);
      result.buttons = std::uint16_t(1u << 2);
    } else if (action == 2) {
      result.action = TacticalAction::Shoot;
      point(goal_target);
      result.buttons = std::uint16_t(1u << 3);
    } else {
      result.action = TacticalAction::Dribble;
      point(goal_target);
      if (self.stamina > .5f && pressure < .4f)
        result.buttons = std::uint16_t(1u << 9);
    }
    return result;
  }

 private:
  static float Distance(const std::array<float, 2>& a,
                        const std::array<float, 2>& b) {
    return std::hypot(a[0] - b[0], a[1] - b[1]);
  }
  static std::array<float, 2> Direction(const std::array<float, 2>& a,
                                        const std::array<float, 2>& b) {
    const float d = Distance(a, b);
    return d > .001f
               ? std::array<float, 2>{(b[0] - a[0]) / d, (b[1] - a[1]) / d}
               : std::array<float, 2>{};
  }
  static float NearestOpponent(const TacticalFrame& f, unsigned team,
                               const std::array<float, 2>& p) {
    float distance = 1000;
    for (unsigned i = 0; i < f.player_count[1 - team]; ++i)
      if (f.players[1 - team][i].active)
        distance =
            std::min(distance, Distance(p, f.players[1 - team][i].position));
    return distance;
  }
  static float OffsideLine(const TacticalFrame& f, unsigned team, float sign,
                           float center) {
    float front = -1000000, second = -1000000;
    unsigned defenders = 0;
    for (unsigned i = 0; i < f.player_count[1 - team]; ++i)
      if (f.players[1 - team][i].active) {
        ++defenders;
        const float x = (f.players[1 - team][i].position[0] - center) * sign;
        if (x > front) {
          second = front;
          front = x;
        } else if (x > second)
          second = x;
      }
    // The actual referee disables offside when the scenario requests it or
    // when fewer than two opponents are active (keeper-only debug scenarios).
    return f.offsides && defenders >= 2
               ? std::max(second, (f.ball[0] - center) * sign)
               : 1000000.f;
  }
  static std::pair<int, float> PassTarget(const TacticalFrame& f, unsigned team,
                                          unsigned actor, float sign,
                                          float center) {
    const auto& origin = f.players[team][actor].position;
    const float offside = OffsideLine(f, team, sign, center);
    int best = -1;
    float best_score = -1;
    for (unsigned i = 0; i < f.player_count[team]; ++i) {
      const auto& candidate = f.players[team][i];
      if (i == actor || !candidate.active) continue;
      const float distance = Distance(origin, candidate.position);
      const float progress = (candidate.position[0] - origin[0]) * sign;
      const float x = (candidate.position[0] - center) * sign;
      if (distance < 3 || distance > 30 || progress < -8 ||
          (x > 0 && x > offside))
        continue;
      float lane = 1;
      const float dx = candidate.position[0] - origin[0],
                  dy = candidate.position[1] - origin[1];
      for (unsigned j = 0; j < f.player_count[1 - team]; ++j)
        if (f.players[1 - team][j].active) {
          const auto& enemy = f.players[1 - team][j].position;
          const float projection =
              ((enemy[0] - origin[0]) * dx + (enemy[1] - origin[1]) * dy) /
              (distance * distance);
          if (projection <= 0 || projection >= 1) continue;
          const std::array<float, 2> nearest{origin[0] + projection * dx,
                                             origin[1] + projection * dy};
          lane = std::min(lane,
                          std::clamp(Distance(enemy, nearest) / 3.f, 0.f, 1.f));
        }
      if (lane < .4f) continue;
      const float open = std::clamp(
          NearestOpponent(f, team, candidate.position) / 8.f, 0.f, 1.f);
      const float score = .4f * open + .3f * lane +
                          .2f * std::clamp(progress / 20.f, 0.f, 1.f) +
                          .1f * (1 - distance / 30.f);
      if (score > best_score) {
        best = int(i);
        best_score = score;
      }
    }
    return {best, best_score};
  }
  Match* match_ = nullptr;
  Team* team_ = nullptr;
  AIControlledKeyboard* hid_ = nullptr;
  Tactic current_tactic_ = Tactic::kDefend;
};
}  // namespace ai

// 2026-09-14: superseded implementation retained for milestone review.
// // Copyright 2026 Google LLC & Contributors
// // AI tactics system for ms-4.1: basic tactical capabilities.
// // Enhanced with ms-4.2: advanced decision making.
// 
// #ifndef GFOOTBALL_AI_TACTICS_HPP
// #define GFOOTBALL_AI_TACTICS_HPP
// 
// #include "../base/math/vector3.hpp"
// #include "../onthepitch/player/controller/humancontroller.hpp"
// #include "../onthepitch/match.hpp"
// #include "../onthepitch/team.hpp"
// #include "../onthepitch/player/playerbase.hpp"
// #include "../onthepitch/ball.hpp"
// 
// namespace ai {
// 
// // AI state for a single player
// struct PlayerState {
//   bool has_ball = false;
//   bool is_closest_to_ball = false;
//   bool is_in_attack_zone = false;
//   bool is_in_defense_zone = false;
//   Vector3 target_position;
//   Vector3 ball_position;
//   Vector3 own_goal_position;
//   Vector3 opponent_goal_position;
//   float stamina = 1.0f;  // 0-100%
//   int tactical_role = 0;  // 0=defender, 1=midfielder, 2=attacker
// };
// 
// // Match context for decision making
// struct MatchContext {
//   float time_remaining = 0.0f;  // seconds
//   int score_diff = 0;  // positive = winning
//   bool is_second_half = false;
//   float possession_time = 0.0f;  // team possession percentage
// };
// 
// // AI tactics controller
// class TacticsController {
//  public:
//   TacticsController(Match* match, Team* team, AIControlledKeyboard* hid);
//   
//   // Main update function - called every frame
//   void Update();
//   
//   // Get current tactic
//   enum class Tactic {
//     kAttack,
//     kDefend,
//     kTransition,
//     kSetPiece
//   };
//   
//   Tactic GetCurrentTactic() const { return current_tactic_; }
//   
//  private:
//   // Analyze current situation
//   void AnalyzeSituation();
//   
//   // Decision making
//   void DecideAction();
//   
//   // Execute actions
//   void ExecuteAction();
//   void ExecuteDribble();
//   void ExecutePass();
//   void ExecuteShoot();
//   void ExecuteDefend();
//   void ExecuteSupport();
//   void ExecuteTacticalFoul();
//   
//   // Helper functions
//   PlayerBase* FindBestPassTarget();
//   Vector3 FindOpenPosition();
//   Vector3 GetDefensivePosition();
//   bool IsInShootingRange();
//   float CalculateThreatLevel();
//   
//   // Advanced decision making (ms-4.2)
//   void UpdateMatchContext();
//   void CalculateDecisionWeights();
//   void AdjustForMatchSituation();
//   void OptimizeTeamPositioning();
//   
//   // Team coordination
//   void MaintainFormation();
//   void RotatePositions();
//   void CoordinatePressure();
//   
//   // Match awareness
//   bool ShouldPressHigh();
//   bool ShouldDropDeep();
//   bool ShouldTimeWaste();
//   bool ShouldRiskAttack();
//   
//   Match* match_;
//   Team* team_;
//   AIControlledKeyboard* hid_;
//   
//   PlayerState current_state_;
//   MatchContext match_context_;
//   Tactic current_tactic_ = Tactic::kDefend;
//   
//   // Decision weights
//   float dribble_weight_ = 0.0f;
//   float pass_weight_ = 0.0f;
//   float shoot_weight_ = 0.0f;
//   float defend_weight_ = 0.0f;
//   float foul_weight_ = 0.0f;
//   
//   // Performance optimization
//   int decision_cache_frame_ = -1;
//   Tactic cached_decision_ = Tactic::kDefend;
// };
// 
// }  // namespace ai
// 
// #endif  // GFOOTBALL_AI_TACTICS_HPP
