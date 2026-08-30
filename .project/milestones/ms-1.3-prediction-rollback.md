# ms-1.3: 客户端预测与回滚

## 基本信息

- **ID**: ms-1.3
- **标题**: 客户端预测与回滚
- **阶段**: Phase 1
- **优先级**: 高
- **状态**: COMPLETED

## 目标

实现 C++ 客户端的预测执行与权威帧回滚机制，使客户端在等待服务器确认期间能流畅运行，同时保证与服务器状态一致。

## 成功条件

- [x] StateSnapshot 接口：保存/恢复完整游戏状态（含位置、速度、比分等）
- [x] 客户端预测：在等待权威帧时本地模拟推进（最多 MAX_PREDICT_AHEAD_FRAMES 帧）
- [x] 回滚机制：收到权威帧后，回滚到该帧的快照，用权威输入重新模拟
- [x] 无包等待：连续 MAX_FRAMES_WITHOUT_PACKET 帧无包则停止预测
- [x] 状态哈希校验：每 STATE_HASH_INTERVAL_K 帧对比服务器哈希
- [x] 单元测试覆盖预测/回滚逻辑（12 + 4 = 16 tests）
- [x] 与 Python 客户端行为对齐（相同协议常量、相同回滚逻辑）

## 实现细节

### 核心算法

```
每帧循环:
  1. 发送 FrameInput(frame_id, my_input)
  2. 本地保存 StateSnapshot(frame_id)
  3. 用 my_input 本地 step → frame_id++
  4. 处理收到的 AuthoritativeFrame:
     a. 如果 frame_id == 已预测帧 → 回滚到该快照，用权威输入重新 step
     b. 如果 frame_id < 已预测帧 → 丢弃（已处理）
     c. 如果 frame_id > 已预测帧 → 跳帧处理
  5. 如果 (当前帧 - 最后确认帧) > MAX_PREDICT_AHEAD_FRAMES → 停止预测
  6. 如果连续 N 帧无包 → 停止预测，等待权威
```

### 文件变更

| 文件 | 变更 |
|------|------|
| `src/frame_sync/client_state.hpp` | 新增：StateSnapshot 结构 + 保存/恢复接口 |
| `src/frame_sync/asio_client.hpp` | 新增：预测/回滚逻辑类声明 |
| `src/frame_sync/asio_client.cpp` | 重构：集成预测/回滚 |
| `tests/frame_sync_test.cpp` | 新增：预测/回滚单元测试 |

## 提交

| 提交 | 内容 |
|------|------|
| `abd4659` | ClientState ring buffer + asio_client prediction/rollback + 16 tests |

## 进度

- **开始时间**: 2026-08-30
- **实际完成**: 2026-08-30
- **完成百分比**: 100%
