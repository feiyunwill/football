# ms-8.3: Humanoid动画状态组件

## 基本信息

- **ID**: ms-8.3
- **标题**: Humanoid动画状态组件
- **阶段**: Phase 8
- **优先级**: 中
- **状态**: COMPLETED

## 目标

将 Humanoid 动画状态迁移到 ECS 架构，实现 HumanoidStateComponent 组件，使动画状态可查询、可序列化。

## 成功条件

- [x] HumanoidStateComponent 组件定义完成
- [x] 双向同步函数（OOP ↔ ECS）正常工作
- [x] SyncHumanoidStateSystem 同步动画状态
- [x] Match 集成 HumanoidStateSystem
- [x] 语法检查通过

## 实现细节

### 核心组件

```cpp
/// Humanoid动画状态组件
struct HumanoidStateComponent {
  // 动画信息
  int current_frame = 0;
  int frame_count = 0;
  int current_anim_id = -1;
  e_FunctionType current_function_type = e_FunctionType_None;
  e_FunctionType previous_function_type = e_FunctionType_None;
  
  // 触球状态
  bool touch_pending = false;
  bool touch_anim = false;
  Vector3 touch_pos;
  int touch_frame = 0;
  
  // 动画选择
  bool is_retain_anim = false;
  bool is_trip_anim = false;
  Vector3 trip_vector;
  int trip_type = 0;
  
  // 身体部位方向
  radian body_angle = 0;
  radian look_at_angle = 0;
  Vector3 look_at_target;
  
  // 空间状态（用于渲染）
  Vector3 position;
  Vector3 direction_vec;
  Vector3 body_direction_vec;
  radian rel_body_angle = 0;
};
```

### 双向同步函数

1. `SyncHumanoidToEcs()` - OOP → ECS
2. `SyncHumanoidFromEcs()` - ECS → OOP
3. `SyncHumanoidStateSystem()` - 遍历所有 Humanoid 同步状态

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/onthepitch/ecs_components.hpp` | 新增 HumanoidStateComponent |
| `engine/src/onthepitch/ecs_systems.hpp` | 新增 HumanoidStateSystem 函数声明 |
| `engine/src/onthepitch/ecs_systems.cpp` | 实现 HumanoidStateSystem |
| `engine/src/onthepitch/match.cpp` | 在 StepPlayersProcess 中集成 SyncHumanoidStateSystem |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
