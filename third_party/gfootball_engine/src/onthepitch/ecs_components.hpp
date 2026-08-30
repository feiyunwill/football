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

/// 2026-08-28 P2-Phase3+：球物理状态组件（查询友好）
/// 存储球的实时物理状态快照，供下游系统直接从 ECS 查询。
struct BallPhysicsComponent {
  Vector3 position;
  Vector3 momentum;
  float height = 0.0f;
  float speed = 0.0f;
  bool touches_net = false;
};

/// 2026-08-28 P2-Phase3+：碰撞结果组件
/// 碰撞 System 执行后将结果写入此组件，下游系统可从 ECS 查询而非调用 OOP。
struct CollisionResultComponent {
  bool collided_with_ball = false;
  bool collided_with_player = false;
  int collided_player_id = -1;
  Vector3 collision_normal;
};

/// 2026-08-30 P2-Phase2: 队伍身份与状态组件
/// 从 Team 类提取核心状态，使 ECS 成为可查询的队伍数据源。
/// 双向同步函数 SyncTeamToEcs / SyncTeamFromEcs
/// 负责 OOP ↔ ECS 一致性。
struct TeamStateComponent {
  int team_id = 0;                    // 队伍 ID (0 或 1)
  int side = -1;                      // 动态边 (-1=左, 1=右)
  int static_side = -1;               // 静态边 (由 team_id 决定)
  bool mirrored = false;              // 是否镜像
  float ai_difficulty = 0.0f;         // AI 难度
  int player_count = 0;               // 球员数量
  int human_gamer_count = 0;          // 人类玩家数量
  int active_player_count = 0;        // 活跃球员数量
  int last_touch_player_id = -1;      // 最后触球球员 stable_id
  int designated_possession_player_id = -1;  // 指定控球球员
};

/// 裁判实体标记（状态仍在 Referee 类中，System 调用 Referee::Process）
struct RefereeTag {};

/// 2026-08-29 P2-Phase4：球员控球状态组件
/// 从 Player 成员变量提取控球相关属性，使 ECS 成为可查询的控球数据源。
/// 双向同步函数 SyncPossessionToEcs / SyncPossessionFromEcs
/// 负责 OOP ↔ ECS 一致性。
struct PossessionComponent {
  bool hasPossession = false;
  bool hasBestPossession = false;
  bool hasUniquePossession = false;
  int possessionDuration_ms = 0;
  unsigned int timeNeededToGetToBall_ms = 1000;
  unsigned int timeNeededToGetToBall_optimistic_ms = 1000;
  unsigned int timeNeededToGetToBall_previous_ms = 1000;
  int desiredTimeToBall_ms = 0;
};

#endif
