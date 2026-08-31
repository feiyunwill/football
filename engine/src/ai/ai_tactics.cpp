// Copyright 2026 Google LLC & Contributors
// AI tactics system implementation.
// Enhanced with ms-4.2: advanced decision making.

#include "ai_tactics.hpp"
#include <algorithm>
#include <cmath>

namespace ai {

TacticsController::TacticsController(Match* match, Team* team, AIControlledKeyboard* hid)
    : match_(match), team_(team), hid_(hid) {
  // Initialize positions
  current_state_.own_goal_position = Vector3(0.0f, 0.0f, 0.0f);  // Will be updated
  current_state_.opponent_goal_position = Vector3(100.0f, 0.0f, 0.0f);  // Will be updated
}

void TacticsController::Update() {
  AnalyzeSituation();
  UpdateMatchContext();
  DecideAction();
}

void TacticsController::AnalyzeSituation() {
  // Get ball position
  current_state_.ball_position = match_->GetBall()->GetPosition();
  
  // Get player position
  PlayerBase* player = team_->GetClosestPlayerToBall();
  if (player) {
    current_state_.has_ball = (player->GetDistanceToBall() < 2.0f);
    current_state_.is_closest_to_ball = true;
    
    // Determine zone
    float player_x = player->GetGeomPosition().x;
    float pitch_center = 50.0f;  // Assuming 100m pitch
    
    current_state_.is_in_attack_zone = (player_x > pitch_center);
    current_state_.is_in_defense_zone = (player_x < pitch_center);
    
    // Update stamina (simplified)
    current_state_.stamina = 1.0f;  // Would come from player data
    
    // Determine tactical role based on position
    if (current_state_.is_in_defense_zone) {
      current_state_.tactical_role = 0;  // Defender
    } else if (current_state_.is_in_attack_zone) {
      current_state_.tactical_role = 2;  // Attacker
    } else {
      current_state_.tactical_role = 1;  // Midfielder
    }
  }
}

void TacticsController::UpdateMatchContext() {
  // Update match context for decision making
  match_context_.time_remaining = match_->GetTime() * 60.0f;  // Convert to seconds
  match_context_.score_diff = match_->GetScoreLeft() - match_->GetScoreRight();
  match_context_.is_second_half = match_->IsSecondHalf();
  match_context_.possession_time = 0.5f;  // Would come from match stats
}

void TacticsController::DecideAction() {
  // Calculate decision weights based on situation
  CalculateDecisionWeights();
  
  // Adjust weights based on match situation
  AdjustForMatchSituation();
  
  // Execute the action with highest weight
  ExecuteAction();
}

void TacticsController::CalculateDecisionWeights() {
  if (current_state_.has_ball) {
    // Player has the ball
    if (IsInShootingRange()) {
      shoot_weight_ = 0.7f;
      pass_weight_ = 0.2f;
      dribble_weight_ = 0.1f;
    } else {
      // Check for open teammates
      PlayerBase* target = FindBestPassTarget();
      if (target) {
        pass_weight_ = 0.6f;
        dribble_weight_ = 0.3f;
        shoot_weight_ = 0.1f;
      } else {
        dribble_weight_ = 0.7f;
        pass_weight_ = 0.2f;
        shoot_weight_ = 0.1f;
      }
    }
    current_tactic_ = Tactic::kAttack;
  } else if (current_state_.is_closest_to_ball) {
    // Player is closest to ball but doesn't have it
    float threat = CalculateThreatLevel();
    
    if (threat > 0.6f) {
      defend_weight_ = 0.8f;
      current_tactic_ = Tactic::kDefend;
    } else {
      // Try to win the ball
      defend_weight_ = 0.5f;
      current_tactic_ = Tactic::kTransition;
    }
  } else {
    // Support player
    current_tactic_ = Tactic::kAttack;
  }
}

void TacticsController::AdjustForMatchSituation() {
  // Adjust based on score and time
  if (match_context_.score_diff > 0) {
    // Winning - be more defensive
    if (match_context_.time_remaining < 300) {  // Last 5 minutes
      defend_weight_ += 0.3f;
      pass_weight_ += 0.2f;
      dribble_weight_ -= 0.3f;
      shoot_weight_ -= 0.2f;
    }
  } else if (match_context_.score_diff < 0) {
    // Losing - be more aggressive
    shoot_weight_ += 0.3f;
    pass_weight_ += 0.1f;
    dribble_weight_ += 0.1f;
    defend_weight_ -= 0.3f;
  }
  
  // Adjust based on possession
  if (match_context_.possession_time > 0.6f) {
    // High possession - patient build-up
    pass_weight_ += 0.2f;
    dribble_weight_ -= 0.1f;
  } else {
    // Low possession - direct play
    shoot_weight_ += 0.1f;
    pass_weight_ -= 0.1f;
  }
  
  // Normalize weights
  float total = dribble_weight_ + pass_weight_ + shoot_weight_ + defend_weight_;
  if (total > 0) {
    dribble_weight_ /= total;
    pass_weight_ /= total;
    shoot_weight_ /= total;
    defend_weight_ /= total;
  }
}

void TacticsController::ExecuteAction() {
  // Find the action with highest weight
  float max_weight = std::max({dribble_weight_, pass_weight_, shoot_weight_, defend_weight_});
  
  if (max_weight < 0.1f) {
    // No clear action, default to support
    ExecuteSupport();
    return;
  }
  
  if (max_weight == dribble_weight_) {
    ExecuteDribble();
  } else if (max_weight == pass_weight_) {
    ExecutePass();
  } else if (max_weight == shoot_weight_) {
    ExecuteShoot();
  } else if (max_weight == defend_weight_) {
    ExecuteDefend();
  }
}

void TacticsController::ExecuteDribble() {
  // Move towards opponent goal with ball
  Vector3 target = current_state_.opponent_goal_position;
  Vector3 direction = (target - current_state_.ball_position).Normalize();
  
  hid_->SetDirection(direction);
  // No special button needed for basic dribble
}

void TacticsController::ExecutePass() {
  PlayerBase* target = FindBestPassTarget();
  if (target) {
    Vector3 pass_direction = (target->GetGeomPosition() - current_state_.ball_position).Normalize();
    hid_->SetDirection(pass_direction);
    hid_->SetButton(e_ButtonFunction_ShortPass, true);
  }
}

void TacticsController::ExecuteShoot() {
  Vector3 shoot_direction = (current_state_.opponent_goal_position - current_state_.ball_position).Normalize();
  hid_->SetDirection(shoot_direction);
  hid_->SetButton(e_ButtonFunction_Shot, true);
}

void TacticsController::ExecuteDefend() {
  // Move towards ball to intercept
  Vector3 ball_direction = (current_state_.ball_position - match_->GetPlayer()->GetGeomPosition()).Normalize();
  hid_->SetDirection(ball_direction);
  hid_->SetButton(e_ButtonFunction_Pressure, true);
}

void TacticsController::ExecuteSupport() {
  // Find open position and move there
  Vector3 open_pos = FindOpenPosition();
  Vector3 move_direction = (open_pos - match_->GetPlayer()->GetGeomPosition()).Normalize();
  hid_->SetDirection(move_direction);
}

void TacticsController::ExecuteTacticalFoul() {
  // Tactical foul when losing and late in game
  if (match_context_.score_diff < 0 && match_context_.time_remaining < 600) {
    hid_->SetButton(e_ButtonFunction_Sliding, true);
  }
}

PlayerBase* TacticsController::FindBestPassTarget() {
  PlayerBase* best_target = nullptr;
  float best_score = -1.0f;
  
  for (int i = 0; i < team_->GetNumPlayers(); ++i) {
    PlayerBase* player = team_->GetPlayer(i);
    if (!player || !player->IsActive()) continue;
    
    // Calculate pass score based on distance and openness
    float distance = (player->GetGeomPosition() - current_state_.ball_position).GetLength();
    float openness = 1.0f;  // Simplified - check for opponents nearby
    
    float score = openness / (distance + 1.0f);
    
    if (score > best_score) {
      best_score = score;
      best_target = player;
    }
  }
  
  return best_target;
}

Vector3 TacticsController::FindOpenPosition() {
  // Simple implementation: move towards opponent goal
  return current_state_.opponent_goal_position;
}

Vector3 TacticsController::GetDefensivePosition() {
  // Simple implementation: move towards own goal
  return current_state_.own_goal_position;
}

bool TacticsController::IsInShootingRange() {
  float distance_to_goal = (current_state_.opponent_goal_position - current_state_.ball_position).GetLength();
  return distance_to_goal < 30.0f;  // Within 30 meters of goal
}

float TacticsController::CalculateThreatLevel() {
  // Simplified threat calculation
  float ball_distance = (current_state_.ball_position - current_state_.own_goal_position).GetLength();
  return 1.0f - (ball_distance / 100.0f);  // Normalize to 0-1
}

// Advanced decision making methods (ms-4.2)

void TacticsController::MaintainFormation() {
  // Maintain team formation based on tactical role
  Vector3 target_pos;
  
  switch (current_state_.tactical_role) {
    case 0:  // Defender
      target_pos = GetDefensivePosition();
      break;
    case 1:  // Midfielder
      target_pos = (current_state_.own_goal_position + current_state_.opponent_goal_position) * 0.5f;
      break;
    case 2:  // Attacker
      target_pos = current_state_.opponent_goal_position;
      break;
  }
  
  current_state_.target_position = target_pos;
}

void TacticsController::RotatePositions() {
  // Simple position rotation based on game situation
  if (match_context_.score_diff > 0) {
    // Winning - rotate to maintain freshness
    current_state_.tactical_role = (current_state_.tactical_role + 1) % 3;
  }
}

void TacticsController::CoordinatePressure() {
  // Coordinate pressure with teammates
  if (current_state_.is_closest_to_ball) {
    // Apply pressure
    hid_->SetButton(e_ButtonFunction_Pressure, true);
  } else {
    // Support position
    ExecuteSupport();
  }
}

bool TacticsController::ShouldPressHigh() {
  // Press high when winning and early in game
  return match_context_.score_diff > 0 && match_context_.time_remaining > 1800;
}

bool TacticsController::ShouldDropDeep() {
  // Drop deep when losing and late in game
  return match_context_.score_diff < 0 && match_context_.time_remaining < 600;
}

bool TacticsController::ShouldTimeWaste() {
  // Time waste when winning and very late in game
  return match_context_.score_diff > 0 && match_context_.time_remaining < 300;
}

bool TacticsController::ShouldRiskAttack() {
  // Risk attack when losing and late in game
  return match_context_.score_diff < 0 && match_context_.time_remaining < 900;
}

}  // namespace ai
