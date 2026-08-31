# ms-1.6: 逻辑渲染分离

## 基本信息

- **ID**: ms-1.6
- **标题**: 逻辑渲染分离
- **阶段**: Phase 1
- **优先级**: 高
- **状态**: COMPLETED

## 目标

实现逻辑帧率固定，渲染可插值。

## 成功条件

- [x] 逻辑帧率固定
- [x] 渲染可插值
- [x] 逻辑与渲染解耦

## 实现细节

### 核心组件

1. **Interpolator 类** (`engine/src/frame_sync/interpolator.hpp`)
   - 提供 Vec3 和 Quat 的插值运算
   - 支持线性插值（位置）和球面线性插值（旋转）
   - 管理前一帧和当前帧的状态

2. **Ball 类修改** (`engine/src/onthepitch/ball.hpp/cpp`)
   - 新增 `previousPositionBuffer` 和 `previousOrientationBuffer`
   - 新增 `SaveInterpolationState()` 方法
   - 新增 `PutInterpolated(float t)` 方法

3. **Match 类修改** (`engine/src/onthepitch/match.hpp/cpp`)
   - 新增 `SaveInterpolationState()` 方法
   - 新增 `PutInterpolated(float t)` 方法

### 插值算法

```
位置插值: result = previous * (1 - t) + current * t
旋转插值: result = slerp(previous, current, t)
```

### 文件变更

| 文件 | 变更 |
|------|------|
| `engine/src/frame_sync/interpolator.hpp` | 新增：插值器类 |
| `engine/src/onthepitch/ball.hpp` | 新增：插值缓冲区和方法 |
| `engine/src/onthepitch/ball.cpp` | 新增：插值方法实现 |
| `engine/src/onthepitch/match.hpp` | 新增：插值渲染方法 |
| `engine/src/onthepitch/match.cpp` | 新增：插值渲染实现 |

## 进度

- **开始时间**: 2026-08-31
- **实际完成**: 2026-08-31
- **完成百分比**: 100%
