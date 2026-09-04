# ms-9.2: 优化ECS查询接口

## 基本信息

- **ID**: ms-9.2
- **标题**: 优化ECS查询接口
- **阶段**: Phase 9
- **优先级**: 高
- **状态**: COMPLETED

## 目标

优化 ECS 查询接口，提供更高效、更易用的查询机制。

## 成功条件

- [x] 分析当前 ECS 查询模式
- [x] 设计优化查询接口
- [x] 实现查询优化
- [x] 保持功能完整性
- [x] 语法检查通过

## 实现细节

### 新增查询接口

1. **QueryResult<Components...>** - 查询结果缓存
   - 支持任意数量的组件类型
   - 提供迭代器支持
   - 支持 Contains 查询

2. **QueryBuilder<Components...>** - 查询构建器
   - 支持链式调用
   - 提供 Execute() 方法执行查询
   - 提供 ForEach() 方法遍历结果

3. **全局查询函数**
   - `Query<Components...>(world)` - 创建查询构建器
   - `GetEntities<Components...>(world)` - 获取实体列表
   - `HasAllComponents<Components...>(world, entity)` - 检查实体组件

### 优化点

1. **使用较小的池作为主遍历池** - 减少遍历次数
2. **编译时组件类型检查** - 使用 fold expression 确保类型安全
3. **支持链式调用** - 提供更流畅的 API

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/ecs/query.hpp` | 新增：查询接口定义 |
| `engine/src/ecs/world.hpp` | 更新：添加 GetPool 方法 |
| `engine/src/onthepitch/ecs_direct_systems.cpp` | 更新：使用新查询接口 |
| `engine/sources.cmake` | 更新：添加新文件 |

## 进度

- **开始时间**: 2026-09-02
- **预计完成**: 2026-09-02
- **实际完成**: 2026-09-02
- **完成百分比**: 100%
