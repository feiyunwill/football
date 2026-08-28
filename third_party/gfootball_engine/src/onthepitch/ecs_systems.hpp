// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

#ifndef _HPP_ONTHEPITCH_ECS_SYSTEMS
#define _HPP_ONTHEPITCH_ECS_SYSTEMS

// 2025-03-17 ECS 迁移：比赛层 System 入口，委托现有 OOP 并同步 ECS

class Match;

/// 执行球逻辑（当前委托 Ball::Process）并同步状态到 ECS BallComponent/Transform
void BallSystemProcess(Match* match);

/// 执行裁判逻辑（委托 Referee::Process）
void RefereeSystemProcess(Match* match);

/// 对全部球员实体执行 Controller::Process 与 Humanoid::Process（替代 Team 内循环）
void RunPlayerSystems(Match* match);

/// 2026-08-25 ECS Phase 2：Put 阶段把 Transform 幂等写回 SceneNodeRef 指向的
/// Spatial（值等价于 legacy Put，由 Match::Put 末尾统一做脏传播）
void PutEcsSync(Match* match);

// 2026-08-28 ECS Phase 3：碰撞系统 wrapper
/// 包装 Match::CheckHumanoidCollisions()，委托已有球员碰撞逻辑
void HumanoidCollisionSystemProcess(Match* match);
/// 包装 Match::CheckBallCollisions()，委托已有球碰撞逻辑
void BallCollisionSystemProcess(Match* match);

#endif
