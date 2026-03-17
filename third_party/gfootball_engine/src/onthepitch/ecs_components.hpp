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
#include "../base/math/vector3.hpp"
#include "../base/math/quaternion.hpp"
#include "../gamedefines.hpp"
#include "../defines.hpp"
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

  void ProcessState(EnvState* state);
};

/// 球员元数据（stable_id, team_id, is_active；PlayerData* 用于兼容 getter）
struct PlayerMeta {
  int stable_id = 0;
  int team_id = 0;
  bool is_active = false;
  PlayerData* player_data = nullptr;

  void ProcessState(EnvState* state);
};

/// 对现有 IController 的引用，便于渐进迁移仍调 Controller::Process
struct ControllerRef {
  IController* controller = nullptr;
};

/// 对 Player 的引用，供 HumanoidSystem 调用 CastHumanoid()->Process()
struct PlayerRef {
  Player* player = nullptr;
};

/// 对场景 Node 的引用，Put 阶段将 Transform 写回 Node
struct SceneNodeRef {
  boost::intrusive_ptr<Node> node;
};

/// 裁判实体标记（状态仍在 Referee 类中，System 调用 Referee::Process）
struct RefereeTag {};

/// 边裁实体标记
struct LinesmanTag {};

#endif
