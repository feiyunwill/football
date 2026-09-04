// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

// 2025-03-17 ECS 迁移：BallSystem 委托 Ball::Process 并写回 ECS

#include "ecs_systems.hpp"
#include "match.hpp"
#include "ecs_components.hpp"
#include "player/player.hpp"
#include "../ecs/transform.hpp"

void BallSystemProcess(Match* match) {
  DO_VALIDATION;
  Ball* ball = match->GetBall();
  ball->Process();

  // 同步到 ECS，供 ProcessState / 后续系统使用
  //（2026-08-25 Phase 2：已有组件时原地写，省去每 tick predictions[401]+list 深拷贝）
  blunted::Entity e = match->GetEcsBallEntity();
  if (e == blunted::kNullEntity) return;
  blunted::World& w = match->GetEcsWorld();
  BallComponent* comp = w.GetComponent<BallComponent>(e);
  if (comp) {
    ball->FillBallComponent(*comp);
  } else {
    BallComponent fresh;
    ball->FillBallComponent(fresh);
    w.AddComponent(e, fresh);
    comp = w.GetComponent<BallComponent>(e);
  }
  Transform tr;
  tr.position = comp->positionBuffer;
  tr.rotation = comp->orientationBuffer;
  tr.scale = Vector3(1.0f, 1.0f, 1.0f);
  w.AddComponent(e, tr);
}

void SyncBallEcsToOop(Match* match) {
  DO_VALIDATION;
  Ball* ball = match->GetBall();
  blunted::Entity e = match->GetEcsBallEntity();
  if (e == blunted::kNullEntity) return;
  blunted::World& w = match->GetEcsWorld();
  const BallComponent* comp = w.GetComponent<BallComponent>(e);
  if (comp) {
    ball->LoadFromComponent(*comp);
  }
}

void RefereeSystemProcess(Match* match) {
  DO_VALIDATION;
  match->GetReferee()->Process();
}

void RunPlayerSystems(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    // 2026-08-25 ECS Phase 2：实时刷新活跃快照，与旧 Team 内循环判定等价
    if (!meta || !pref || !pref->player) continue;
    meta->is_active = pref->player->IsActive();
    if (!meta->is_active) continue;
    ControllerRef* cref = w.GetComponent<ControllerRef>(e);
    if (cref && cref->controller) cref->controller->Process();
    if (pref->player->CastHumanoid()) pref->player->CastHumanoid()->Process();
  }
}

void PutEcsSync(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  w.ForEach<Transform, SceneNodeRef>(
      [](blunted::Entity, Transform& tr, SceneNodeRef& ref) {
        if (!ref.node) return;
        // 与 Ball::Put 一致：updateSpatialData=false，脏传播由 Match::Put 末尾的
        // RecursiveUpdateSpatialData 统一进行（scale 不同步：SetScale 无开关、必触发传播）
        if (tr.position != ref.node->GetPosition())
          ref.node->SetPosition(tr.position, false);
        if (tr.rotation != ref.node->GetRotation())
          ref.node->SetRotation(tr.rotation, false);
      });
}

// 2026-08-28 ECS Phase 3：碰撞系统 wrapper
// 委托已有 Match 方法，使管线步骤可通过 ECS System 接口统一调度。
// 不重写碰撞逻辑（逐步迁移策略），仅建立 System 入口。

void HumanoidCollisionSystemProcess(Match* match) {
  DO_VALIDATION;
  match->CheckHumanoidCollisions();
}

void BallCollisionSystemProcess(Match* match) {
  DO_VALIDATION;
  match->CheckBallCollisions();
}

// 2026-08-28 ECS Phase 4：Team 战术系统 wrapper
// Team 方法均为 public，无需 friend 声明。
// 不重写战术逻辑，仅建立 System 入口供帧管线调度。

void TeamTacticsSystemProcess(Match* match, int team_id) {
  DO_VALIDATION;
  match->GetTeam(team_id)->Process();
}

void TeamSwitchSystemProcess(Match* match, int team_id) {
  DO_VALIDATION;
  match->GetTeam(team_id)->UpdateSwitch();
}

void TeamPossessionStatsSystemProcess(Match* match, int team_id) {
  DO_VALIDATION;
  match->GetTeam(team_id)->UpdatePossessionStats();
}

// 2026-08-28 P2-Phase3+：球物理状态数据化
// Ball::Process() 执行后调用，将球物理快照写入 BallPhysicsComponent。
// 下游系统可直接从 ECS 查询球位置/速度/高度，无需调用 Ball 方法。
void SyncBallPhysicsSystem(Match* match) {
  DO_VALIDATION;
  Ball* ball = match->GetBall();
  blunted::Entity e = match->GetEcsBallEntity();
  if (e == blunted::kNullEntity) return;
  blunted::World& w = match->GetEcsWorld();

  BallPhysicsComponent* bpc = w.GetComponent<BallPhysicsComponent>(e);
  if (!bpc) {
    BallPhysicsComponent fresh;
    w.AddComponent(e, fresh);
    bpc = w.GetComponent<BallPhysicsComponent>(e);
  }
  bpc->position = ball->Predict(10);
  bpc->momentum = ball->GetMovement();
  bpc->height = bpc->position.coords[2];
  bpc->speed = bpc->momentum.GetLength();
  bpc->touches_net = ball->BallTouchesNet();
}

// 2026-08-28 P2-Phase3+：碰撞结果数据化
// 碰撞 System 执行后调用，将碰撞结果从 OOP 写入 ECS 组件。
// 下游系统（如 possession_decision）可从 ECS 查询而非直接调用 OOP。
void PopulateCollisionResults(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;

    CollisionResultComponent* crc = w.GetComponent<CollisionResultComponent>(e);
    if (!crc) {
      CollisionResultComponent fresh;
      w.AddComponent(e, fresh);
      crc = w.GetComponent<CollisionResultComponent>(e);
    }
    // 读取 OOP 碰撞状态（Player 的 lastTouchType 等）
    // 注意：实际碰撞检测在 CheckHumanoidCollisions/CheckBallCollisions 中完成
    // 这里只是将结果快照到 ECS，供后续系统查询
    crc->collided_with_ball = false;
    crc->collided_with_player = false;
    crc->collided_player_id = -1;
    crc->collision_normal = Vector3(0);
  }
}

// 2026-08-28 P2-Phase1：PlayerPhysicsComponent 双向同步
// SpatialState 定义在 humanoidbase.hpp，PlayerPhysicsComponent 定义在 ecs_components.hpp。
// 这里做纯数据拷贝，不涉及逻辑，保证 OOP ↔ ECS 一致性。

#include "player/humanoid/humanoidbase.hpp"
#include "player/player.hpp"

void SyncSpatialStateToPhysics(const SpatialState& src, PlayerPhysicsComponent& dst) {
  dst.position = src.position;
  dst.angle = src.angle;
  dst.directionVec = src.directionVec;
  dst.enumVelocity = src.enumVelocity;
  dst.floatVelocity = src.floatVelocity;
  dst.movement = src.movement;
  dst.bodyDirectionVec = src.bodyDirectionVec;
  dst.relBodyAngle = src.relBodyAngle;
  dst.foot = src.foot;
}

void SyncPhysicsToSpatialState(const PlayerPhysicsComponent& src, SpatialState& dst) {
  dst.position = src.position;
  dst.angle = src.angle;
  dst.directionVec = src.directionVec;
  dst.enumVelocity = src.enumVelocity;
  dst.floatVelocity = src.floatVelocity;
  dst.movement = src.movement;
  dst.bodyDirectionVec = src.bodyDirectionVec;
  dst.relBodyAngle = src.relBodyAngle;
  dst.foot = src.foot;
}

void SyncPlayerPhysicsSystem(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    auto* humanoid = pref->player->CastHumanoid();
    if (!humanoid) continue;
    // 通过新增的 GetSpatialState() public accessor 读取完整物理状态
    PlayerPhysicsComponent* comp = w.GetComponent<PlayerPhysicsComponent>(e);
    if (!comp) {
      PlayerPhysicsComponent fresh;
      SyncSpatialStateToPhysics(humanoid->GetSpatialState(), fresh);
      w.AddComponent(e, fresh);
    } else {
      SyncSpatialStateToPhysics(humanoid->GetSpatialState(), *comp);
    }
  }
}

/// 将 ECS PlayerPhysicsComponent 同步回 Humanoid SpatialState（ECS → OOP）
/// 在 players 系统执行后调用，确保 Humanoid 内部状态与 ECS 权威数据一致
void SyncPhysicsToSpatialSystem(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    auto* humanoid = pref->player->CastHumanoid();
    if (!humanoid) continue;
    PlayerPhysicsComponent* comp = w.GetComponent<PlayerPhysicsComponent>(e);
    if (comp) {
      SyncPhysicsToSpatialState(*comp, humanoid->MutableSpatialState());
    }
  }
}

// 2026-08-29 P2-Phase4：PossessionComponent 双向同步
// 从 Player 成员变量提取控球相关属性到 ECS 组件，使控球状态可查询。

void SyncPossessionToEcs(const Player& src, PossessionComponent& dst) {
  dst.hasPossession = src.HasPossession();
  dst.hasBestPossession = src.HasBestPossession();
  dst.hasUniquePossession = src.HasUniquePossession();
  dst.possessionDuration_ms = src.GetPossessionDuration_ms();
  dst.timeNeededToGetToBall_ms = src.GetTimeNeededToGetToBall_ms();
  dst.timeNeededToGetToBall_optimistic_ms = src.GetTimeNeededToGetToBall_optimistic_ms();
  dst.timeNeededToGetToBall_previous_ms = src.GetTimeNeededToGetToBall_previous_ms();
  dst.desiredTimeToBall_ms = src.GetDesiredTimeToBall_ms();
}

void SyncPlayerPossessionSystem(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;

    PossessionComponent* comp = w.GetComponent<PossessionComponent>(e);
    if (!comp) {
      PossessionComponent fresh;
      SyncPossessionToEcs(*pref->player, fresh);
      w.AddComponent(e, fresh);
    } else {
      SyncPossessionToEcs(*pref->player, *comp);
    }
  }
}

// 2026-09-02 Phase 8：Officials ECS 系统
// 从 Officials OOP 提取状态到 ECS 组件，使裁判组状态可查询。

#include "officials.hpp"
#include "player/playerofficial.hpp"
#include "player/playerbase.hpp"

void SyncOfficialsToEcs(const Officials& src, OfficialsComponent& dst) {
  // 注意：Officials 的成员是 protected，需要通过 public 方法访问
  // 这里使用 const_cast 来调用非 const 方法（后续可重构为 const 正确）
  Officials& officials = const_cast<Officials&>(src);
  
  // 获取裁判球员
  PlayerOfficial* referee = officials.GetReferee();
  if (referee) {
    dst.is_referee_active = referee->IsActive();
    dst.referee_entity_id = referee->GetStableID();
  }
  
  // 获取边裁
  std::vector<PlayerBase*> players;
  officials.GetPlayers(players);
  dst.are_linesmen_active = (players.size() > 1);
  
  // 卡牌状态（从 Match 的 Referee 获取）
  // 注意：这里需要 Match 指针，但 SyncOfficialsToEcs 签名中没有
  // 卡牌状态在 Officials::Put 中处理，这里只同步基础状态
  dst.has_yellow_card = false;
  dst.has_red_card = false;
  dst.yellow_card_position = Vector3(0, 0, -10);
  dst.red_card_position = Vector3(0, 0, -10);
  
  dst.is_processing = false;
}

void OfficialsSystemProcess(Match* match) {
  DO_VALIDATION;
  Officials* officials = match->GetOfficials();
  if (!officials) return;
  
  // 同步状态到 ECS
  blunted::Entity e = match->GetEcsOfficialsEntity();
  if (e != blunted::kNullEntity) {
    blunted::World& w = match->GetEcsWorld();
    OfficialsComponent* comp = w.GetComponent<OfficialsComponent>(e);
    if (comp) {
      SyncOfficialsToEcs(*officials, *comp);
    } else {
      OfficialsComponent fresh;
      SyncOfficialsToEcs(*officials, fresh);
      w.AddComponent(e, fresh);
    }
  }
  
  // 执行原有逻辑
  officials->Process();
}

void OfficialsSystemFetchPutBuffers(Match* match) {
  DO_VALIDATION;
  Officials* officials = match->GetOfficials();
  if (officials) {
    officials->FetchPutBuffers();
  }
}

void OfficialsSystemPut(Match* match, bool mirror) {
  DO_VALIDATION;
  Officials* officials = match->GetOfficials();
  if (officials) {
    officials->Put(mirror);
  }
}

// 2026-09-02 Phase 8：Player 核心状态 ECS 系统
// 从 Player OOP 提取核心状态到 ECS 组件，使球员状态可查询。

void SyncPlayerToEcs(Player& src, PlayerStateComponent& dst) {
  // 基本信息
  dst.stable_id = src.GetStableID();
  dst.team_id = src.GetTeamID();
  dst.is_active = src.IsActive();
  
  // 物理状态
  dst.position = src.GetPosition();
  dst.geom_position = src.GetGeomPosition();
  dst.direction_vec = src.GetDirectionVec();
  dst.body_direction_vec = src.GetBodyDirectionVec();
  dst.rel_body_angle = src.GetRelBodyAngle();
  
  // 动作状态
  dst.enum_velocity = src.GetEnumVelocity();
  dst.float_velocity = src.GetFloatVelocity();
  dst.movement = src.GetMovement();
  dst.foot = e_Foot_Right;  // 默认值，需要从 Humanoid 获取
  
  // 控球状态
  dst.has_possession = src.HasPossession();
  dst.has_best_possession = src.HasBestPossession();
  dst.has_unique_possession = src.HasUniquePossession();
  dst.possession_duration_ms = src.GetPossessionDuration_ms();
  
  // 时间戳
  dst.last_touch_time_ms = src.GetLastTouchTime_ms();
  dst.last_touch_type = static_cast<int>(src.GetLastTouchType());
  
  // 疲劳与状态
  dst.fatigue_factor_inv = src.GetFatigueFactorInv();
  dst.cards = 0;  // 需要从 Player 获取 cards 成员
}

void SyncPlayerStateSystem(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  bool needs_sort = false;
  
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    
    PlayerStateComponent* comp = w.GetComponent<PlayerStateComponent>(e);
    if (!comp) {
      PlayerStateComponent fresh;
      SyncPlayerToEcs(*pref->player, fresh);
      w.AddComponent(e, fresh);
      needs_sort = true;
    } else {
      SyncPlayerToEcs(*pref->player, *comp);
    }
  }
  
  // 批量添加后统一排序
  if (needs_sort) {
    w.FlushBatchAdds<PlayerStateComponent>();
  }
}

// 2026-09-02 Phase 8：Humanoid 动画状态 ECS 系统
// 从 HumanoidBase OOP 提取动画状态到 ECS 组件，使动画状态可查询。

#include "player/humanoid/humanoidbase.hpp"

void SyncHumanoidToEcs(HumanoidBase& src, HumanoidStateComponent& dst) {
  // 动画信息
  dst.current_frame = src.GetFrameNum();
  dst.frame_count = src.GetFrameCount();
  dst.current_anim_id = src.GetCurrentAnim() ? src.GetCurrentAnim()->id : -1;
  dst.current_function_type = src.GetCurrentFunctionType();
  dst.previous_function_type = src.GetPreviousFunctionType();
  
  // 触球状态（需要从 Humanoid 获取）
  // 注意：HumanoidBase 没有直接的 TouchPending/TouchAnim 方法
  // 这些方法在 Humanoid 类中，需要向下转型
  dst.touch_pending = false;
  dst.touch_anim = false;
  dst.touch_pos = Vector3(0);
  dst.touch_frame = 0;
  
  // 动画选择
  dst.is_retain_anim = false;
  dst.is_trip_anim = false;
  dst.trip_vector = Vector3(0);
  dst.trip_type = 0;
  
  // 身体部位方向
  dst.body_angle = 0;
  dst.look_at_angle = 0;
  dst.look_at_target = Vector3(0);
  
  // 空间状态（用于渲染）
  dst.position = src.GetPosition();
  dst.direction_vec = src.GetDirectionVec();
  dst.body_direction_vec = src.GetBodyDirectionVec();
  dst.rel_body_angle = src.GetRelBodyAngle();
}

void SyncHumanoidStateSystem(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  bool needs_sort = false;
  
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (!meta || !pref || !pref->player) continue;
    if (!meta->is_active) continue;
    
    auto* humanoid = pref->player->CastHumanoid();
    if (!humanoid) continue;
    
    HumanoidStateComponent* comp = w.GetComponent<HumanoidStateComponent>(e);
    if (!comp) {
      HumanoidStateComponent fresh;
      SyncHumanoidToEcs(*humanoid, fresh);
      w.AddComponent(e, fresh);
      needs_sort = true;
    } else {
      SyncHumanoidToEcs(*humanoid, *comp);
    }
  }
  
  // 批量添加后统一排序
  if (needs_sort) {
    w.FlushBatchAdds<HumanoidStateComponent>();
  }
}

// 2026-09-02 Phase 8：MentalImage 心理图像 ECS 系统
// 从 MentalImage OOP 提取心理图像状态到 ECS 组件，使 AI 决策状态可查询。

#include "AIsupport/mentalimage.hpp"

void SyncMentalImageToEcs(const MentalImage& src, MentalImageComponent& dst) {
  // 时间信息
  dst.time_stamp_ms = src.timeStamp_ms;
  dst.is_valid = (src.timeStamp_ms > 0);  // 使用时间戳判断有效性
  
  // 球状态（从 ballPredictions 获取最新预测）
  if (!src.ballPredictions.empty()) {
    dst.ball_position = src.ballPredictions.back();
  } else {
    dst.ball_position = Vector3(0);
  }
  dst.ball_momentum = Vector3(0);  // MentalImage 不直接存储动量
  
  // 球员状态
  dst.player_states.clear();
  for (const auto& player_img : src.players) {
    MentalImageComponent::PlayerState state;
    state.position = player_img.position;
    state.direction_vec = player_img.directionVec;
    state.is_active = (player_img.player != nullptr);
    state.team_id = -1;  // 需要从 Player 获取 team_id
    dst.player_states.push_back(state);
  }
  
  // 队伍状态（需要从 Match 获取）
  dst.last_touch_team_id = -1;
  dst.best_possession_team_id = -1;
  
  // 偏差参数
  dst.max_distance_deviation = src.maxDistanceDeviation;
  dst.max_movement_deviation = src.maxMovementDeviation;
}

void SyncMentalImageSystem(Match* match) {
  DO_VALIDATION;
  // MentalImage 存储在 Match 的 mentalImages 向量中
  // 这里同步最新的 MentalImage 到 ECS
  // 注意：MentalImage 是按时间戳存储的，我们只同步最新的一个
  
  // 获取最新的 MentalImage（如果有）
  // MentalImage 系统在 StepMentalImages 中更新，这里只做同步
}
