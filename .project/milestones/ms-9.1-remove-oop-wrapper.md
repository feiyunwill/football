# ms-9.1: 移除OOP包装层

## 基本信息

- **ID**: ms-9.1
- **标题**: 移除OOP包装层
- **阶段**: Phase 9
- **优先级**: 高
- **状态**: COMPLETED

## 目标

移除 OOP 包装层，使 ECS 直接驱动游戏逻辑，减少间接调用开销。

## 成功条件

- [x] 分析当前 OOP 包装层的使用情况
- [x] 设计 ECS 直接驱动方案
- [x] 实现 ECS 直接驱动
- [x] 保持功能完整性
- [x] 语法检查通过

## 实现细节

### 新增 ECS 直接驱动系统

1. **PlayerStateSystemDirect** - 直接从 ECS 查询球员状态
2. **HumanoidStateSystemDirect** - 直接从 ECS 查询 Humanoid 状态
3. **BallPhysicsSystemDirect** - 直接从 ECS 查询球物理状态
4. **OfficialsSystemDirect** - 直接从 ECS 查询裁判组状态
5. **TeamTacticsSystemDirect** - 直接从 ECS 查询队伍战术状态
6. **TeamSwitchSystemDirect** - 直接从 ECS 查询队伍切换状态
7. **PossessionStatsSystemDirect** - 直接从 ECS 查询控球统计状态

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/onthepitch/ecs_direct_systems.hpp` | 新增：ECS 直接驱动系统声明 |
| `engine/src/onthepitch/ecs_direct_systems.cpp` | 新增：ECS 直接驱动系统实现 |
| `engine/src/onthepitch/match.cpp` | 更新：使用 ECS 直接驱动系统 |
| `engine/sources.cmake` | 更新：添加新文件 |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
