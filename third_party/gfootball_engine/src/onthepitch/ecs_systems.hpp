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

#endif
