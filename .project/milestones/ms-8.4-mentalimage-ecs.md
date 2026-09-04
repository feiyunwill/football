# ms-8.4: MentalImage ECS化

## 基本信息

- **ID**: ms-8.4
- **标题**: MentalImage ECS化
- **阶段**: Phase 8
- **优先级**: 中
- **状态**: COMPLETED

## 目标

将 MentalImage（心理图像）迁移到 ECS 架构，实现 MentalImageComponent 组件，使 AI 心理图像状态可查询、可序列化。

## 成功条件

- [x] MentalImageComponent 组件定义完成
- [x] 双向同步函数（OOP ↔ ECS）正常工作
- [x] SyncMentalImageSystem 同步心理图像状态
- [x] Match 集成 MentalImageSystem
- [x] 语法检查通过

## 实现细节

### 核心组件

```cpp
/// MentalImage心理图像组件
struct MentalImageComponent {
  // 时间信息
  unsigned int time_stamp_ms = 0;
  bool is_valid = false;
  
  // 球状态
  Vector3 ball_position;
  Vector3 ball_momentum;
  
  // 球员状态（简化版，只存储关键信息）
  struct PlayerState {
    Vector3 position;
    Vector3 direction_vec;
    bool is_active = false;
    int team_id = -1;
  };
  std::vector<PlayerState> player_states;
  
  // 队伍状态
  int last_touch_team_id = -1;
  int best_possession_team_id = -1;
  
  // 偏差参数
  float max_distance_deviation = 2.5f;
  float max_movement_deviation = 1.0f;
};
```

### 双向同步函数

1. `SyncMentalImageToEcs()` - OOP → ECS
2. `SyncMentalImageFromEcs()` - ECS → OOP
3. `SyncMentalImageSystem()` - 同步 MentalImage 到 ECS

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/onthepitch/ecs_components.hpp` | 新增 MentalImageComponent |
| `engine/src/onthepitch/ecs_systems.hpp` | 新增 MentalImageSystem 函数声明 |
| `engine/src/onthepitch/ecs_systems.cpp` | 实现 MentalImageSystem |
| `engine/src/onthepitch/match.cpp` | 在 StepMentalImages 中集成 SyncMentalImageSystem |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
