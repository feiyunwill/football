// Copyright 2026 Google LLC & Contributors
// AI tactics system for ms-4.1: basic tactical capabilities.
// Enhanced with ms-4.2: advanced decision making.

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
  float stamina = 1.0f;  // 0-100%
  int tactical_role = 0;  // 0=defender, 1=midfielder, 2=attacker
};

// Match context for decision making
struct MatchContext {
  float time_remaining = 0.0f;  // seconds
  int score_diff = 0;  // positive = winning
  bool is_second_half = false;
  float possession_time = 0.0f;  // team possession percentage
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
  void ExecuteTacticalFoul();
  
  // Helper functions
  PlayerBase* FindBestPassTarget();
  Vector3 FindOpenPosition();
  Vector3 GetDefensivePosition();
  bool IsInShootingRange();
  float CalculateThreatLevel();
  
  // Advanced decision making (ms-4.2)
  void UpdateMatchContext();
  void CalculateDecisionWeights();
  void AdjustForMatchSituation();
  void OptimizeTeamPositioning();
  
  // Team coordination
  void MaintainFormation();
  void RotatePositions();
  void CoordinatePressure();
  
  // Match awareness
  bool ShouldPressHigh();
  bool ShouldDropDeep();
  bool ShouldTimeWaste();
  bool ShouldRiskAttack();
  
  Match* match_;
  Team* team_;
  AIControlledKeyboard* hid_;
  
  PlayerState current_state_;
  MatchContext match_context_;
  Tactic current_tactic_ = Tactic::kDefend;
  
  // Decision weights
  float dribble_weight_ = 0.0f;
  float pass_weight_ = 0.0f;
  float shoot_weight_ = 0.0f;
  float defend_weight_ = 0.0f;
  float foul_weight_ = 0.0f;
  
  // Performance optimization
  int decision_cache_frame_ = -1;
  Tactic cached_decision_ = Tactic::kDefend;
};

}  // namespace ai

#endif  // GFOOTBALL_AI_TACTICS_HPP
