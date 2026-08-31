// Copyright 2026 Google LLC & Contributors
// AI tactics system for ms-4.1: basic tactical capabilities.

#ifndef GFOOTBALL_AI_TACTICS_HPP
#define GFOOTBALL_AI_TACTICS_HPP

#include "../base/math/vector3.hpp"
#include "../onthepitch/player/controller/humancontroller.hpp"
#include "../onthepitch/match.hpp"
#include "../onthepitch/team.hpp"
#include "../onthepitch/player/playerbase.hpp"
#include "../onthepitch/ball.hpp"

namespace ai {

// AI state for a single player
struct PlayerState {
  bool has_ball = false;
  bool is_closest_to_ball = false;
  bool is_in_attack_zone = false;
  bool is_in_defense_zone = false;
  Vector3 target_position;
  Vector3 ball_position;
  Vector3 own_goal_position;
  Vector3 opponent_goal_position;
};

// AI tactics controller
class TacticsController {
 public:
  TacticsController(Match* match, Team* team, AIControlledKeyboard* hid);
  
  // Main update function - called every frame
  void Update();
  
  // Get current tactic
  enum class Tactic {
    kAttack,
    kDefend,
    kTransition,
    kSetPiece
  };
  
  Tactic GetCurrentTactic() const { return current_tactic_; }
  
 private:
  // Analyze current situation
  void AnalyzeSituation();
  
  // Decision making
  void DecideAction();
  
  // Execute actions
  void ExecuteDribble();
  void ExecutePass();
  void ExecuteShoot();
  void ExecuteDefend();
  void ExecuteSupport();
  
  // Helper functions
  PlayerBase* FindBestPassTarget();
  Vector3 FindOpenPosition();
  Vector3 GetDefensivePosition();
  bool IsInShootingRange();
  float CalculateThreatLevel();
  
  Match* match_;
  Team* team_;
  AIControlledKeyboard* hid_;
  
  PlayerState current_state_;
  Tactic current_tactic_ = Tactic::kDefend;
  
  // Decision weights
  float dribble_weight_ = 0.0f;
  float pass_weight_ = 0.0f;
  float shoot_weight_ = 0.0f;
  float defend_weight_ = 0.0f;
};

}  // namespace ai

#endif  // GFOOTBALL_AI_TACTICS_HPP
