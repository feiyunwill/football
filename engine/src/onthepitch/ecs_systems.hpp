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
/// 2026-08-28 P2-Phase2：从 ECS BallComponent 恢复 Ball 状态（ECS → OOP 方向）
void SyncBallEcsToOop(Match* match);

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

// 2026-08-28 P2-Phase1：PlayerPhysicsComponent 双向同步
struct SpatialState;
struct PlayerPhysicsComponent;
/// 从 HumanoidBase::spatialState → PlayerPhysicsComponent（OOP → ECS）
void SyncSpatialStateToPhysics(const SpatialState& src, PlayerPhysicsComponent& dst);
/// 从 PlayerPhysicsComponent → SpatialState（ECS → OOP）
void SyncPhysicsToSpatialState(const PlayerPhysicsComponent& src, SpatialState& dst);
/// 遍历所有活跃球员实体，将 SpatialState 同步到 PlayerPhysicsComponent（OOP → ECS）
void SyncPlayerPhysicsSystem(Match* match);
/// 遍历所有活跃球员实体，将 PlayerPhysicsComponent 同步回 SpatialState（ECS → OOP）
void SyncPhysicsToSpatialSystem(Match* match);

// 2026-08-28 P2-Phase3+：球物理状态数据化
/// 将球物理状态（位置/动量/高度/速度/碰网）同步到 BallPhysicsComponent
void SyncBallPhysicsSystem(Match* match);

// 2026-08-28 P2-Phase3+：碰撞结果数据化
/// 碰撞 System 执行后，将碰撞结果从 OOP 写入 ECS CollisionResultComponent
void PopulateCollisionResults(Match* match);

// 2026-08-28 ECS Phase 4：Team 战术系统 wrapper
/// 包装 Team::Process()，执行队伍 AI 战术决策
void TeamTacticsSystemProcess(Match* match, int team_id);
/// 包装 Team::UpdateSwitch()，执行球员切换逻辑
void TeamSwitchSystemProcess(Match* match, int team_id);
/// 包装 Team::UpdatePossessionStats()，更新控球统计
void TeamPossessionStatsSystemProcess(Match* match, int team_id);

// 2026-08-29 P2-Phase4：PossessionComponent 双向同步
struct PossessionComponent;
class Player;
/// 从 Player 成员变量 → PossessionComponent（OOP → ECS）
void SyncPossessionToEcs(const Player& src, PossessionComponent& dst);
/// 遍历所有活跃球员实体，将控球状态同步到 ECS
void SyncPlayerPossessionSystem(Match* match);

// 2026-09-02 Phase 8：Officials ECS 系统
struct OfficialsComponent;
class Officials;
/// 从 Officials OOP → OfficialsComponent（OOP → ECS）
void SyncOfficialsToEcs(const Officials& src, OfficialsComponent& dst);
/// 包装 Officials::Process()，执行裁判组逻辑
void OfficialsSystemProcess(Match* match);
/// 包装 Officials::FetchPutBuffers()，获取渲染缓冲区
void OfficialsSystemFetchPutBuffers(Match* match);
/// 包装 Officials::Put()，执行渲染
void OfficialsSystemPut(Match* match, bool mirror);

// 2026-09-02 Phase 8：Player 核心状态 ECS 系统
struct PlayerStateComponent;
/// 从 Player OOP → PlayerStateComponent（OOP → ECS）
void SyncPlayerToEcs(Player& src, PlayerStateComponent& dst);
/// 遍历所有活跃球员实体，将核心状态同步到 ECS
void SyncPlayerStateSystem(Match* match);

// 2026-09-02 Phase 8：Humanoid 动画状态 ECS 系统
struct HumanoidStateComponent;
class HumanoidBase;
/// 从 HumanoidBase OOP → HumanoidStateComponent（OOP → ECS）
void SyncHumanoidToEcs(HumanoidBase& src, HumanoidStateComponent& dst);
/// 遍历所有活跃球员实体，将 Humanoid 动画状态同步到 ECS
void SyncHumanoidStateSystem(Match* match);

// 2026-09-02 Phase 8：MentalImage 心理图像 ECS 系统
struct MentalImageComponent;
class MentalImage;
/// 从 MentalImage OOP → MentalImageComponent（OOP → ECS）
void SyncMentalImageToEcs(const MentalImage& src, MentalImageComponent& dst);
/// 同步所有 MentalImage 到 ECS
void SyncMentalImageSystem(Match* match);

#endif
