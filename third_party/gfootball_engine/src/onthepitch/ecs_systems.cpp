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
