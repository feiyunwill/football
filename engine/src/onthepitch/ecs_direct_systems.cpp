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

// 2026-09-02 Phase 9: ECS 直接驱动系统
// 移除 OOP 包装层，使 ECS 直接驱动游戏逻辑

#include "ecs_direct_systems.hpp"
#include "match.hpp"
#include "team.hpp"
#include "referee.hpp"
#include "ecs_components.hpp"
#include "player/player.hpp"
#include "player/humanoid/humanoidbase.hpp"
#include "player/playerofficial.hpp"
#include "AIsupport/mentalimage.hpp"
#include "../ecs/query.hpp"

void PlayerStateSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  bool needs_sort = false;
  
  // 使用新的查询接口获取所有拥有 PlayerMeta 和 PlayerRef 的实体
  auto result = blunted::Query<PlayerMeta, PlayerRef>(w).Execute();
  
  for (blunted::Entity e : result) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    
    // 直接从 ECS 查询球员状态
    PlayerStateComponent* comp = w.GetComponent<PlayerStateComponent>(e);
    if (!comp) {
      // 创建新的 PlayerStateComponent
      PlayerStateComponent fresh;
      pref->player->FillPlayerStateComponent(fresh);
      w.AddComponent(e, fresh);
      needs_sort = true;
    } else {
      // 更新现有 PlayerStateComponent
      pref->player->FillPlayerStateComponent(*comp);
    }
  }
  
  // 批量添加后统一排序
  if (needs_sort) {
    w.FlushBatchAdds<PlayerStateComponent>();
  }
}

void HumanoidStateSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  bool needs_sort = false;
  
  // 使用新的查询接口获取所有拥有 PlayerMeta 和 PlayerRef 的实体
  auto result = blunted::Query<PlayerMeta, PlayerRef>(w).Execute();
  
  for (blunted::Entity e : result) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    
    auto* humanoid = pref->player->CastHumanoid();
    if (!humanoid) continue;
    
    // 直接从 ECS 查询 Humanoid 状态
    HumanoidStateComponent* comp = w.GetComponent<HumanoidStateComponent>(e);
    if (!comp) {
      // 创建新的 HumanoidStateComponent
      HumanoidStateComponent fresh;
      humanoid->FillHumanoidStateComponent(fresh);
      w.AddComponent(e, fresh);
      needs_sort = true;
    } else {
      // 更新现有 HumanoidStateComponent
      humanoid->FillHumanoidStateComponent(*comp);
    }
  }
  
  // 批量添加后统一排序
  if (needs_sort) {
    w.FlushBatchAdds<HumanoidStateComponent>();
  }
}

void BallPhysicsSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  Ball* ball = match->GetBall();
  if (!ball) return;
  
  blunted::Entity e = match->GetEcsBallEntity();
  if (e == blunted::kNullEntity) return;
  
  // 直接从 ECS 查询球物理状态
  BallPhysicsComponent* bpc = w.GetComponent<BallPhysicsComponent>(e);
  if (!bpc) {
    // 创建新的 BallPhysicsComponent
    BallPhysicsComponent fresh;
    ball->FillBallPhysicsComponent(fresh);
    w.AddComponent(e, fresh);
  } else {
    // 更新现有 BallPhysicsComponent
    ball->FillBallPhysicsComponent(*bpc);
  }
}

void OfficialsSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  Officials* officials = match->GetOfficials();
  if (!officials) return;
  
  blunted::Entity e = match->GetEcsOfficialsEntity();
  if (e == blunted::kNullEntity) return;
  
  // 直接从 ECS 查询裁判组状态
  OfficialsComponent* comp = w.GetComponent<OfficialsComponent>(e);
  if (!comp) {
    // 创建新的 OfficialsComponent
    OfficialsComponent fresh;
    officials->FillOfficialsComponent(fresh);
    w.AddComponent(e, fresh);
  } else {
    // 更新现有 OfficialsComponent
    officials->FillOfficialsComponent(*comp);
  }
}

void TeamTacticsSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  // 直接从 ECS 查询队伍战术状态
  // 注意：队伍战术状态目前存储在 Team 对象中
  // 需要通过 TeamRef 组件访问
  blunted::World& w = match->GetEcsWorld();
  
  // 使用新的查询接口获取所有拥有 PlayerMeta 的实体
  auto result = blunted::Query<PlayerMeta>(w).Execute();
  
  for (blunted::Entity e : result) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    if (!meta || meta->team_id != team_id) continue;
    
    // 更新队伍战术状态
    TacticsComponent* tact = w.GetComponent<TacticsComponent>(e);
    if (!tact) {
      TacticsComponent fresh;
      fresh.team_id = team_id;
      fresh.hasPossession = false;
      fresh.timeNeededToGetToBall_ms = 0;
      fresh.teamPossessionAmount = 0.0f;
      fresh.fadingTeamPossessionAmount = 0.0f;
      fresh.side = -1;
      
      w.AddComponent(e, fresh);
    }
  }
}

void TeamSwitchSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  // 直接从 ECS 查询队伍切换状态
  // 注意：队伍切换状态目前存储在 Team 对象中
  // 需要通过 TeamRef 组件访问
  blunted::World& w = match->GetEcsWorld();
  
  // 使用新的查询接口获取所有拥有 PlayerMeta 和 PlayerRef 的实体
  auto result = blunted::Query<PlayerMeta, PlayerRef>(w).Execute();
  
  for (blunted::Entity e : result) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    if (!meta || meta->team_id != team_id) continue;
    
    // 更新球员活跃状态
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (pref && pref->player) {
      meta->is_active = pref->player->IsActive();
    }
  }
}

void PossessionStatsSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  // 直接从 ECS 查询控球统计状态
  blunted::World& w = match->GetEcsWorld();
  
  // 使用新的查询接口获取所有拥有 PlayerMeta 的实体
  auto result = blunted::Query<PlayerMeta>(w).Execute();
  
  for (blunted::Entity e : result) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    if (!meta || meta->team_id != team_id) continue;
    
    // 更新控球状态
    PossessionComponent* poss = w.GetComponent<PossessionComponent>(e);
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
      
      w.AddComponent(e, fresh);
    }
  }
}

void TeamProcessSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  
  // 获取 Team 对象
  Team* team = match->GetTeam(team_id);
  if (!team) return;
  
  // 获取队伍实体
  blunted::Entity team_entity = blunted::kNullEntity;
  for (blunted::Entity e : w.GetPool<TeamStateComponent>()->Entities()) {
    TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(e);
    if (tsc && tsc->team_id == team_id) {
      team_entity = e;
      break;
    }
  }
  
  if (team_entity == blunted::kNullEntity) return;
  
  // 更新队伍状态
  TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(team_entity);
  if (tsc) {
    // 从 Team 对象读取状态
    tsc->team_id = team->GetID();
    tsc->side = team->GetDynamicSide();
    tsc->static_side = team->GetStaticSide();
    tsc->mirrored = team->isMirrored();
    tsc->ai_difficulty = team->GetAiDifficulty();
    tsc->player_count = team->GetAllPlayers().size();
    
    // 计算活跃球员数量
    int active_count = 0;
    for (auto* player : team->GetAllPlayers()) {
      if (player->IsActive()) active_count++;
    }
    tsc->active_player_count = active_count;
    
    // 人类玩家数量
    tsc->human_gamer_count = team->GetHumanGamerCount();
  }
  
  // 更新战术状态
  TacticsComponent* tact = w.GetComponent<TacticsComponent>(team_entity);
  if (tact) {
    tact->team_id = team_id;
    tact->hasPossession = team->HasPossession();
    tact->timeNeededToGetToBall_ms = team->GetTimeNeededToGetToBall_ms();
    tact->teamPossessionAmount = team->GetTeamPossessionAmount();
    tact->fadingTeamPossessionAmount = team->GetFadingTeamPossessionAmount();
    tact->side = team->GetDynamicSide();
  }
}

void TeamPossessionDecisionSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  
  // 获取 Team 对象
  Team* team = match->GetTeam(team_id);
  if (!team) return;
  
  // 获取队伍实体
  blunted::Entity team_entity = blunted::kNullEntity;
  for (blunted::Entity e : w.GetPool<TeamStateComponent>()->Entities()) {
    TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(e);
    if (tsc && tsc->team_id == team_id) {
      team_entity = e;
      break;
    }
  }
  
  if (team_entity == blunted::kNullEntity) return;
  
  // 更新控球决策状态
  TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(team_entity);
  if (tsc) {
    // 更新指定控球球员
    Player* designated = team->GetDesignatedTeamPossessionPlayer();
    if (designated) {
      tsc->designated_possession_player_id = designated->GetStableID();
    }
    
    // 更新最后触球球员
    Player* last_touch = team->GetLastTouchPlayer();
    if (last_touch) {
      tsc->last_touch_player_id = last_touch->GetStableID();
    }
  }
}

void TeamStateFillSystemDirect(Match* match, int team_id) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  
  // 获取 Team 对象
  Team* team = match->GetTeam(team_id);
  if (!team) return;
  
  // 获取队伍实体
  blunted::Entity team_entity = blunted::kNullEntity;
  for (blunted::Entity e : w.GetPool<TeamStateComponent>()->Entities()) {
    TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(e);
    if (tsc && tsc->team_id == team_id) {
      team_entity = e;
      break;
    }
  }
  
  // 如果没有队伍实体，创建一个
  if (team_entity == blunted::kNullEntity) {
    team_entity = w.CreateEntity();
    TeamStateComponent fresh;
    w.AddComponent(team_entity, fresh);
    TacticsComponent tact_fresh;
    w.AddComponent(team_entity, tact_fresh);
  }
  
  // 填充队伍状态组件
  TeamStateComponent* tsc = w.GetComponent<TeamStateComponent>(team_entity);
  if (tsc) {
    team->FillTeamStateComponent(*tsc);
  }
  
  // 填充战术组件
  TacticsComponent* tact = w.GetComponent<TacticsComponent>(team_entity);
  if (tact) {
    team->FillTacticsComponent(*tact);
  }
}

void RefereeProcessSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  Referee* referee = match->GetReferee();
  if (!referee) return;
  
  blunted::Entity e = match->GetEcsRefereeEntity();
  if (e == blunted::kNullEntity) return;
  
  // 获取 RefereeStateComponent
  RefereeStateComponent* comp = w.GetComponent<RefereeStateComponent>(e);
  if (!comp) {
    // 创建新的 RefereeStateComponent
    RefereeStateComponent fresh;
    fresh.buffer_active = referee->GetBuffer().active;
    fresh.desired_set_piece = static_cast<int>(referee->GetBuffer().desiredSetPiece);
    fresh.buffer_team_id = referee->GetBuffer().teamID;
    fresh.stop_time = referee->GetBuffer().stopTime;
    fresh.prepare_time = referee->GetBuffer().prepareTime;
    fresh.start_time = referee->GetBuffer().startTime;
    fresh.end_phase = referee->GetBuffer().endPhase;
    
    // 犯规状态
    fresh.foul_type = referee->GetCurrentFoulType();
    
    w.AddComponent(e, fresh);
  } else {
    // 更新现有 RefereeStateComponent
    comp->buffer_active = referee->GetBuffer().active;
    comp->desired_set_piece = static_cast<int>(referee->GetBuffer().desiredSetPiece);
    comp->buffer_team_id = referee->GetBuffer().teamID;
    comp->stop_time = referee->GetBuffer().stopTime;
    comp->prepare_time = referee->GetBuffer().prepareTime;
    comp->start_time = referee->GetBuffer().startTime;
    comp->end_phase = referee->GetBuffer().endPhase;
    
    comp->foul_type = referee->GetCurrentFoulType();
  }
}

void RefereeStateFillSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  Referee* referee = match->GetReferee();
  if (!referee) return;
  
  blunted::Entity e = match->GetEcsRefereeEntity();
  if (e == blunted::kNullEntity) return;
  
  // 获取 RefereeStateComponent
  RefereeStateComponent* comp = w.GetComponent<RefereeStateComponent>(e);
  if (!comp) {
    // 创建新的 RefereeStateComponent
    RefereeStateComponent fresh;
    referee->FillRefereeStateComponent(fresh);
    w.AddComponent(e, fresh);
  } else {
    // 使用 FillRefereeStateComponent 更新
    referee->FillRefereeStateComponent(*comp);
  }
}

void MentalImageSyncSystemDirect(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  
  // 获取所有 MentalImage 实体
  auto* pool = w.GetPool<MentalImageComponent>();
  if (!pool) return;
  
  for (blunted::Entity e : pool->Entities()) {
    MentalImageComponent* comp = w.GetComponent<MentalImageComponent>(e);
    if (!comp) continue;
    
    // 更新 MentalImageComponent 状态
    // 注意：MentalImage 对象存储在 Match 中，这里只是同步状态到 ECS
    // 实际的 MentalImage 逻辑仍然在 MentalImage 类中
    
    // 获取时间戳
    comp->time_stamp_ms = match->GetActualTime_ms();
    
    // 获取球预测
    Ball* ball = match->GetBall();
    if (ball) {
      comp->ball_position = ball->Predict(0);
      comp->ball_momentum = ball->GetMovement();
    }
    
    // 获取队伍状态
    Team* team0 = match->GetTeam(0);
    Team* team1 = match->GetTeam(1);
    
    if (team0 && team1) {
      // 更新最后触球队伍
      comp->last_touch_team_id = match->GetLastTouchTeamID();
      
      // 更新最佳控球队伍
      Team* bestTeam = match->GetBestPossessionTeam();
      if (bestTeam) {
        comp->best_possession_team_id = bestTeam->GetID();
      }
    }
  }
}
