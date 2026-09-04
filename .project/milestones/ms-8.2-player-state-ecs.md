# ms-8.2: Player核心状态组件

## 基本信息

- **ID**: ms-8.2
- **标题**: Player核心状态组件
- **阶段**: Phase 8
- **优先级**: 高
- **状态**: COMPLETED

## 目标

将 Player 核心状态迁移到 ECS 架构，实现 PlayerStateComponent 组件，使球员状态可查询、可序列化。

## 成功条件

- [x] PlayerStateComponent 组件定义完成
- [x] 双向同步函数（OOP ↔ ECS）正常工作
- [x] SyncPlayerStateSystem 同步球员状态
- [x] Match 集成 PlayerStateSystem
- [x] 语法检查通过

## 实现细节

### 核心组件

```cpp
/// 球员核心状态组件
struct PlayerStateComponent {
  // 基本信息
  int stable_id = -1;
  int team_id = -1;
  bool is_active = false;
  
  // 物理状态
  Vector3 position;
  Vector3 geom_position;
  Vector3 direction_vec;
  Vector3 body_direction_vec;
  radian rel_body_angle = 0;
  
  // 动作状态
  e_Velocity enum_velocity = e_Velocity_Idle;
  float float_velocity = 0.0f;
  Vector3 movement;
  e_Foot foot = e_Foot_Right;
  
  // 控球状态
  bool has_possession = false;
  bool has_best_possession = false;
  bool has_unique_possession = false;
  int possession_duration_ms = 0;
  
  // 时间戳
  unsigned long last_touch_time_ms = 0;
  int last_touch_type = 0;
  
  // 疲劳与状态
  float fatigue_factor_inv = 0.0f;
  int cards = 0;
};
```

### 双向同步函数

1. `SyncPlayerToEcs()` - OOP → ECS
2. `SyncPlayerFromEcs()` - ECS → OOP
3. `SyncPlayerStateSystem()` - 遍历所有球员同步状态

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/onthepitch/ecs_components.hpp` | 新增 PlayerStateComponent |
| `engine/src/onthepitch/ecs_systems.hpp` | 新增 PlayerStateSystem 函数声明 |
| `engine/src/onthepitch/ecs_systems.cpp` | 实现 PlayerStateSystem |
| `engine/src/onthepitch/match.cpp` | 在 StepPlayersProcess 中集成 SyncPlayerStateSystem |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
