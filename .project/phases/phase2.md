# Phase 2: ECS 架构重构完成

## 目标

将所有游戏对象迁移到 ECS 架构，使 ECS 成为唯一的权威数据源，OOP 层退化为薄代理。

## 成功条件

- 所有游戏状态可通过 ECS 查询
- OOP 层（Player/Team/Match/Referee）仅保留 Process 逻辑
- 序列化/反序列化 100% 通过 ECS
- 性能不低于纯 OOP（内存局部性提升）

## 当前状态

### 已完成的 ECS 组件

| 组件 | 来源 | 状态 |
|------|------|------|
| BallComponent | Ball | ✅ 双向同步 |
| PlayerPhysicsComponent | SpatialState | ✅ 双向同步 |
| TacticsComponent | Team | ✅ 只读查询 |
| BallPhysicsComponent | Ball | ✅ 查询快照 |
| CollisionResultComponent | Collision | ✅ 写入结果 |
| PossessionComponent | Player | ✅ 双向同步 |

### 待迁移的游戏对象

| 对象 | 复杂度 | 优先级 | 说明 |
|------|--------|--------|------|
| **Team** | 中 | 高 | 战术状态、控球、阵型 |
| **Referee** | 低 | 中 | 裁判状态、犯规判定 |
| **Match** | 高 | 低 | 中央协调器，依赖所有子系统 |
| **Player AI** | 高 | 低 | 控制器策略，与 OOP 耦合深 |

## 里程碑

| 里程碑 | 目标 | 成功条件 | 依赖 | 状态 |
|--------|------|----------|------|------|
| ms-2.1 | Team ECS 迁移 | Team 状态 100% 可查询 | - | 待开始 |
| ms-2.2 | Referee ECS 迁移 | 裁判状态可序列化 | - | 待开始 |
| ms-2.3 | Match ECS 协调 | Match::Step 通过 ECS 驱动 | ms-2.1, ms-2.2 | 待开始 |
| ms-2.4 | 序列化完整性 | 所有组件可序列化/反序列化 | ms-2.3 | 待开始 |
| ms-2.5 | 性能验证 | ECS 查询性能 ≥ OOP | ms-2.4 | 待开始 |

## 实现策略

### 渐进迁移

1. **Phase A: 数据提取** — 从 OOP 类中提取状态到 ECS 组件
2. **Phase B: 双向同步** — 实现 Sync*ToEcs / Sync*FromEcs 函数
3. **Phase C: 逻辑迁移** — 将 Process 逻辑从 OOP 移到 System
4. **Phase D: 清理** — 删除冗余 OOP 状态，保留 Process 壳

### 关键约束

- **确定性不变**：ECS 遍历顺序必须与 OOP 一致（按 Entity id 排序）
- **向后兼容**：Python 接口不变，C++ 内部重构
- **性能不退化**：内存局部性提升应抵消间接寻址开销

## 文件变更

| 文件 | 变更 |
|------|------|
| `src/onthepitch/ecs_components.hpp` | 新增组件定义 |
| `src/onthepitch/ecs_systems.cpp` | 新增 System 实现 |
| `src/ecs/world.hpp` | 可能扩展 World API |
| `src/onthepitch/team.hpp/cpp` | 状态提取到 ECS |
| `src/onthepitch/referee.hpp/cpp` | 状态提取到 ECS |
| `tests/ecs_test.cpp` | 新增组件测试 |
