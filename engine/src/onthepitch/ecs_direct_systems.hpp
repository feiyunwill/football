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

#ifndef _HPP_ECS_DIRECT_SYSTEMS
#define _HPP_ECS_DIRECT_SYSTEMS

#include "../ecs/world.hpp"
#include "../ecs/entity.hpp"
#include "ecs_components.hpp"

class Match;
class Team;

/// 2026-09-02 Phase 9: 球员状态系统
/// 直接从 ECS 查询球员状态，不调用 OOP 方法
void PlayerStateSystemDirect(Match* match);

/// 2026-09-02 Phase 9: Humanoid 状态系统
/// 直接从 ECS 查询 Humanoid 状态，不调用 OOP 方法
void HumanoidStateSystemDirect(Match* match);

/// 2026-09-02 Phase 9: 球物理系统
/// 直接从 ECS 查询球物理状态，不调用 OOP 方法
void BallPhysicsSystemDirect(Match* match);

/// 2026-09-02 Phase 9: 裁判组系统
/// 直接从 ECS 查询裁判组状态，不调用 OOP 方法
void OfficialsSystemDirect(Match* match);

/// 2026-09-02 Phase 9: 队伍战术系统
/// 直接从 ECS 查询队伍战术状态，不调用 OOP 方法
void TeamTacticsSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 9: 队伍切换系统
/// 直接从 ECS 查询队伍切换状态，不调用 OOP 方法
void TeamSwitchSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 9: 控球统计系统
/// 直接从 ECS 查询控球统计状态，不调用 OOP 方法
void PossessionStatsSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 10: Team 主处理系统
/// 直接从 ECS 查询 Team 状态，不调用 OOP 方法
void TeamProcessSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 10: Team 控球决策系统
/// 直接从 ECS 查询 Team 控球决策状态，不调用 OOP 方法
void TeamPossessionDecisionSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 10: Team 状态填充系统
/// 直接从 ECS 查询 Team 状态并填充组件
void TeamStateFillSystemDirect(Match* match, int team_id);

/// 2026-09-02 Phase 10: Referee 主处理系统
/// 直接从 ECS 查询 Referee 状态，不调用 OOP 方法
void RefereeProcessSystemDirect(Match* match);

/// 2026-09-02 Phase 10: Referee 状态填充系统
/// 直接从 ECS 查询 Referee 状态并填充组件
void RefereeStateFillSystemDirect(Match* match);

/// 2026-09-02 Phase 10: MentalImage 同步系统
/// 直接从 ECS 查询 MentalImage 状态，不调用 OOP 方法
void MentalImageSyncSystemDirect(Match* match);

#endif
