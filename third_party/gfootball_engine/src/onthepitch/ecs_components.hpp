// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

#ifndef _HPP_ONTHEPITCH_ECS_COMPONENTS
#define _HPP_ONTHEPITCH_ECS_COMPONENTS

// 2025-03-17 ECS 迁移：比赛层组件定义，供 Match/System 使用

#include "../ecs/entity.hpp"
#include "../ecs/transform.hpp"
#include "../types/spatial.hpp"
#include "../base/math/vector3.hpp"
#include "../base/math/quaternion.hpp"
#include "../gamedefines.hpp"
#include "../defines.hpp"
#include "../utils/animation.hpp"
#include "../scene/scene3d/node.hpp"
#include "player/controller/icontroller.hpp"
#include "../data/playerdata.hpp"

#include <list>

class Player;

using namespace blunted;

/// 球逻辑状态（从 Ball 拆出的可序列化数据）
struct BallComponent {
  Vector3 momentum;
  Quaternion rotation_ms;
  Vector3 predictions[ballPredictionSize_ms / 10 + cachedPredictions + 1];
  int valid_predictions = 0;
  Quaternion orientPrediction;
  std::list<Vector3> ballPosHistory;
  Vector3 positionBuffer;
  Quaternion orientationBuffer;
  bool ballTouchesNet = false;
};

/// 球员元数据（stable_id, team_id, is_active；PlayerData* 用于兼容 getter）
struct PlayerMeta {
  int stable_id = 0;
  int team_id = 0;
  bool is_active = false;
  PlayerData* player_data = nullptr;
};

/// 对现有 IController 的引用，便于渐进迁移仍调 Controller::Process
struct ControllerRef {
  IController* controller = nullptr;
};

/// 对 Player 的引用，供 HumanoidSystem 调用 CastHumanoid()->Process()
struct PlayerRef {
  Player* player = nullptr;
};

/// 对场景 Spatial 的引用，Put 阶段将 Transform 写回（2026-08-25 Phase 2：
/// 球的可驱动节点是内层 Geometry(Object 分支)，与 Node 同级，故用公共基类 Spatial）
struct SceneNodeRef {
  boost::intrusive_ptr<Spatial> node;
};

/// 2026-08-28 P2-Phase1：玩家物理状态组件
/// 从 SpatialState 提取核心物理字段，使 ECS 成为可查询的权威数据源。
/// 双向同步函数 SyncSpatialStateToPhysics / SyncPhysicsToSpatialState
/// 负责 OOP ↔ ECS 一致性。
struct PlayerPhysicsComponent {
  Vector3 position;
  radian angle = 0;
  Vector3 directionVec;
  e_Velocity enumVelocity = e_Velocity_Idle;
  float floatVelocity = 0.0f;
  Vector3 movement;
  Vector3 bodyDirectionVec;
  radian relBodyAngle = 0;
  e_Foot foot = e_Foot_Right;
};

/// 2026-08-28 P2-Phase3：队伍战术状态组件
/// 从 Team 成员变量提取可序列化的纯数据，使 ECS 成为可观测的战术数据源。
struct TacticsComponent {
  bool hasPossession = false;
  int timeNeededToGetToBall_ms = 0;
  float teamPossessionAmount = 0.0f;
  float fadingTeamPossessionAmount = 0.0f;
  int side = -1;
  int team_id = 0;
};

/// 裁判实体标记（状态仍在 Referee 类中，System 调用 Referee::Process）
struct RefereeTag {};

#endif
