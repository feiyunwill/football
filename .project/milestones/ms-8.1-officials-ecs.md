# ms-8.1: Officials ECS 迁移

## 基本信息

- **ID**: ms-8.1
- **标题**: Officials ECS 迁移
- **阶段**: Phase 8
- **优先级**: 高
- **状态**: COMPLETED

## 目标

将 Officials（裁判组）迁移到 ECS 架构，实现 OfficialsComponent 组件，使裁判组状态可查询、可序列化。

## 成功条件

- [x] OfficialsComponent 组件定义完成
- [x] 双向同步函数（OOP ↔ ECS）正常工作
- [x] OfficialsSystem 包装现有 Process/FetchPutBuffers/Put 逻辑
- [x] Match 集成 OfficialsSystem
- [x] 语法检查通过

## 实现细节

### 核心组件

```cpp
/// 裁判组状态组件
struct OfficialsComponent {
  // 裁判实体ID
  int referee_entity_id = -1;
  int linesmen_entity_ids[2] = {-1, -1};
  
  // 裁判类型标记
  bool is_referee_active = false;
  bool are_linesmen_active = false;
  
  // 卡牌状态
  bool has_yellow_card = false;
  bool has_red_card = false;
  Vector3 yellow_card_position;
  Vector3 red_card_position;
  
  // 处理状态
  bool is_processing = false;
};
```

### 双向同步函数

1. `SyncOfficialsToEcs()` - OOP → ECS
2. `SyncOfficialsFromEcs()` - ECS → OOP
3. `OfficialsSystemProcess()` - 包装 Process 逻辑
4. `OfficialsSystemFetchPutBuffers()` - 包装 FetchPutBuffers 逻辑
5. `OfficialsSystemPut()` - 包装 Put 逻辑

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/onthepitch/ecs_components.hpp` | 新增 OfficialsComponent |
| `engine/src/onthepitch/ecs_systems.hpp` | 新增 OfficialsSystem 函数声明 |
| `engine/src/onthepitch/ecs_systems.cpp` | 实现 OfficialsSystem |
| `engine/src/onthepitch/match.hpp` | 添加 GetEcsOfficialsEntity 方法 |
| `engine/src/onthepitch/match.cpp` | 集成 OfficialsSystem，注册 Officials 实体 |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
