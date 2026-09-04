// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// 2026-09-02 Phase 9: ECS 系统批处理实现

#include "system_batch.hpp"
#include "../onthepitch/match.hpp"
#include "../onthepitch/team.hpp"
#include "../onthepitch/referee.hpp"
#include "../onthepitch/ecs_components.hpp"
#include "../onthepitch/player/player.hpp"
#include "../onthepitch/player/humanoid/humanoidbase.hpp"
#include "../onthepitch/player/playerofficial.hpp"
#include "../onthepitch/AIsupport/mentalimage.hpp"

namespace blunted {

void PlayerSystemBatch::Execute(World& world) {
  // 使用查询接口获取所有拥有 PlayerMeta 和 PlayerRef 的实体
  auto result = Query<PlayerMeta, PlayerRef>(world).Execute();
  
  bool needs_sort = false;
  
  for (Entity e : result) {
    PlayerMeta* meta = world.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = world.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    
    // 批量更新 PlayerStateComponent
    PlayerStateComponent* comp = world.GetComponent<PlayerStateComponent>(e);
    if (!comp) {
      PlayerStateComponent fresh;
      fresh.stable_id = meta->stable_id;
      fresh.team_id = meta->team_id;
      fresh.is_active = meta->is_active;
      
      fresh.position = pref->player->GetPosition();
      fresh.geom_position = pref->player->GetGeomPosition();
      fresh.direction_vec = pref->player->GetDirectionVec();
      fresh.body_direction_vec = pref->player->GetBodyDirectionVec();
      fresh.rel_body_angle = pref->player->GetRelBodyAngle();
      fresh.enum_velocity = pref->player->GetEnumVelocity();
      fresh.float_velocity = pref->player->GetFloatVelocity();
      fresh.movement = pref->player->GetMovement();
      
      fresh.has_possession = pref->player->HasPossession();
      fresh.has_best_possession = pref->player->HasBestPossession();
      fresh.has_unique_possession = pref->player->HasUniquePossession();
      fresh.possession_duration_ms = pref->player->GetPossessionDuration_ms();
      
      fresh.last_touch_time_ms = pref->player->GetLastTouchTime_ms();
      fresh.last_touch_type = static_cast<int>(pref->player->GetLastTouchType());
      
      fresh.fatigue_factor_inv = pref->player->GetFatigueFactorInv();
      
      world.AddComponent(e, fresh);
      needs_sort = true;
    } else {
      comp->stable_id = meta->stable_id;
      comp->team_id = meta->team_id;
      comp->is_active = meta->is_active;
      
      comp->position = pref->player->GetPosition();
      comp->geom_position = pref->player->GetGeomPosition();
      comp->direction_vec = pref->player->GetDirectionVec();
      comp->body_direction_vec = pref->player->GetBodyDirectionVec();
      comp->rel_body_angle = pref->player->GetRelBodyAngle();
      comp->enum_velocity = pref->player->GetEnumVelocity();
      comp->float_velocity = pref->player->GetFloatVelocity();
      comp->movement = pref->player->GetMovement();
      
      comp->has_possession = pref->player->HasPossession();
      comp->has_best_possession = pref->player->HasBestPossession();
      comp->has_unique_possession = pref->player->HasUniquePossession();
      comp->possession_duration_ms = pref->player->GetPossessionDuration_ms();
      
      comp->last_touch_time_ms = pref->player->GetLastTouchTime_ms();
      comp->last_touch_type = static_cast<int>(pref->player->GetLastTouchType());
      
      comp->fatigue_factor_inv = pref->player->GetFatigueFactorInv();
    }
    
    // 批量更新 HumanoidStateComponent（同一次遍历）
    auto* humanoid = pref->player->CastHumanoid();
    if (humanoid) {
      HumanoidStateComponent* hcomp = world.GetComponent<HumanoidStateComponent>(e);
      if (!hcomp) {
        HumanoidStateComponent fresh;
        fresh.current_frame = humanoid->GetFrameNum();
        fresh.frame_count = humanoid->GetFrameCount();
        fresh.current_anim_id = humanoid->GetCurrentAnim() ? humanoid->GetCurrentAnim()->id : -1;
        fresh.current_function_type = humanoid->GetCurrentFunctionType();
        fresh.previous_function_type = humanoid->GetPreviousFunctionType();
        
        fresh.position = humanoid->GetPosition();
        fresh.direction_vec = humanoid->GetDirectionVec();
        fresh.body_direction_vec = humanoid->GetBodyDirectionVec();
        fresh.rel_body_angle = humanoid->GetRelBodyAngle();
        
        world.AddComponent(e, fresh);
        needs_sort = true;
      } else {
        hcomp->current_frame = humanoid->GetFrameNum();
        hcomp->frame_count = humanoid->GetFrameCount();
        hcomp->current_anim_id = humanoid->GetCurrentAnim() ? humanoid->GetCurrentAnim()->id : -1;
        hcomp->current_function_type = humanoid->GetCurrentFunctionType();
        hcomp->previous_function_type = humanoid->GetPreviousFunctionType();
        
        hcomp->position = humanoid->GetPosition();
        hcomp->direction_vec = humanoid->GetDirectionVec();
        hcomp->body_direction_vec = humanoid->GetBodyDirectionVec();
        hcomp->rel_body_angle = humanoid->GetRelBodyAngle();
      }
    }
  }
  
  // 批量添加后统一排序
  if (needs_sort) {
    world.FlushBatchAdds<PlayerStateComponent>();
    world.FlushBatchAdds<HumanoidStateComponent>();
  }
}

void OfficialsSystemBatch::Execute(World& world, Match* match) {
  Officials* officials = match->GetOfficials();
  if (!officials) return;
  
  Entity e = match->GetEcsOfficialsEntity();
  if (e == kNullEntity) return;
  
  // 批量更新裁判组状态
  OfficialsComponent* comp = world.GetComponent<OfficialsComponent>(e);
  if (!comp) {
    OfficialsComponent fresh;
    fresh.is_referee_active = officials->GetReferee() ? officials->GetReferee()->IsActive() : false;
    fresh.are_linesmen_active = true;
    
    world.AddComponent(e, fresh);
  } else {
    comp->is_referee_active = officials->GetReferee() ? officials->GetReferee()->IsActive() : false;
    comp->are_linesmen_active = true;
  }
}

void PossessionStatsBatch::Execute(World& world, Match* match, int first_team, int second_team) {
  // 使用查询接口获取所有拥有 PlayerMeta 的实体
  auto result = Query<PlayerMeta>(world).Execute();
  
  for (Entity e : result) {
    PlayerMeta* meta = world.GetComponent<PlayerMeta>(e);
    if (!meta) continue;
    
    // 批量更新两个队伍的控球状态
    PossessionComponent* poss = world.GetComponent<PossessionComponent>(e);
    if (!poss) {
      PossessionComponent fresh;
      fresh.hasPossession = false;
      fresh.hasBestPossession = false;
      fresh.hasUniquePossession = false;
      fresh.possessionDuration_ms = 0;
      fresh.timeNeededToGetToBall_ms = 1000;
      fresh.timeNeededToGetToBall_optimistic_ms = 1000;
      fresh.timeNeededToGetToBall_previous_ms = 1000;
      fresh.desiredTimeToBall_ms = 0;
      
      world.AddComponent(e, fresh);
    }
  }
}

void TeamSystemBatch::Execute(World& world, Match* match, int team_id) {
  // 批量处理 Team 相关系统
  // 1. TeamState 填充
  // 2. TeamProcess 系统
  // 3. TeamPossessionDecision 系统
  
  Team* team = match->GetTeam(team_id);
  if (!team) return;
  
  // 获取或创建队伍实体
  Entity team_entity = kNullEntity;
  auto* tsc_pool = world.GetPool<TeamStateComponent>();
  if (tsc_pool) {
    for (Entity e : tsc_pool->Entities()) {
      TeamStateComponent* tsc = world.GetComponent<TeamStateComponent>(e);
      if (tsc && tsc->team_id == team_id) {
        team_entity = e;
        break;
      }
    }
  }
  
  if (team_entity == kNullEntity) {
    team_entity = world.CreateEntity();
    TeamStateComponent fresh;
    world.AddComponent(team_entity, fresh);
    TacticsComponent tact_fresh;
    world.AddComponent(team_entity, tact_fresh);
  }
  
  // 填充队伍状态组件
  TeamStateComponent* tsc = world.GetComponent<TeamStateComponent>(team_entity);
  if (tsc) {
    team->FillTeamStateComponent(*tsc);
  }
  
  // 填充战术组件
  TacticsComponent* tact = world.GetComponent<TacticsComponent>(team_entity);
  if (tact) {
    team->FillTacticsComponent(*tact);
  }
}

void RefereeSystemBatch::Execute(World& world, Match* match) {
  // 批量处理 Referee 相关系统
  Referee* referee = match->GetReferee();
  if (!referee) return;
  
  Entity e = match->GetEcsRefereeEntity();
  if (e == kNullEntity) return;
  
  // 获取 RefereeStateComponent
  RefereeStateComponent* comp = world.GetComponent<RefereeStateComponent>(e);
  if (!comp) {
    // 创建新的 RefereeStateComponent
    RefereeStateComponent fresh;
    referee->FillRefereeStateComponent(fresh);
    world.AddComponent(e, fresh);
  } else {
    // 使用 FillRefereeStateComponent 更新
    referee->FillRefereeStateComponent(*comp);
  }
}

void MentalImageSystemBatch::Execute(World& world, Match* match) {
  // 批量处理 MentalImage 相关系统
  auto* pool = world.GetPool<MentalImageComponent>();
  if (!pool) return;
  
  for (Entity e : pool->Entities()) {
    MentalImageComponent* comp = world.GetComponent<MentalImageComponent>(e);
    if (!comp) continue;
    
    // 更新 MentalImageComponent 状态
    comp->time_stamp_ms = match->GetActualTime_ms();
    
    Ball* ball = match->GetBall();
    if (ball) {
      comp->ball_position = ball->Predict(0);
      comp->ball_momentum = ball->GetMovement();
    }
    
    Team* team0 = match->GetTeam(0);
    Team* team1 = match->GetTeam(1);
    
    if (team0 && team1) {
      comp->last_touch_team_id = match->GetLastTouchTeamID();
      
      Team* bestTeam = match->GetBestPossessionTeam();
      if (bestTeam) {
        comp->best_possession_team_id = bestTeam->GetID();
      }
    }
  }
}

void GameLogicBatch::Execute(World& world, Match* match) {
  // 批量处理所有游戏逻辑系统
  int first_team = match->FirstTeam();
  int second_team = match->SecondTeam();
  
  // 1. 球员系统批处理
  PlayerSystemBatch player_batch;
  player_batch.Execute(world);
  
  // 2. Team 系统批处理
  TeamSystemBatch team_batch;
  team_batch.Execute(world, match, first_team);
  team_batch.Execute(world, match, second_team);
  
  // 3. 裁判组系统批处理
  OfficialsSystemBatch officials_batch;
  officials_batch.Execute(world, match);
  
  // 4. Referee 系统批处理
  RefereeSystemBatch referee_batch;
  referee_batch.Execute(world, match);
  
  // 5. MentalImage 系统批处理
  MentalImageSystemBatch mental_batch;
  mental_batch.Execute(world, match);
  
  // 6. 控球统计批处理
  PossessionStatsBatch possession_batch;
  possession_batch.Execute(world, match, first_team, second_team);
}

}  // namespace blunted
