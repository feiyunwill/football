# 帧同步联机端到端集成 — 实施计划

**Milestone**: ms-1290ef3a  
**创建时间**: 2026-08-29  
**优先级**: high  
**标签**: networking, framesync, cpp, python

---

## 目标

实现完整的帧同步联机系统，支持多人（11v11）足球对战，具备断线重连、确定性验证等鲁棒性特性。

## 当前状态

| 组件 | 状态 | 备注 |
|------|------|------|
| 协议定义 | ✅ 完成 | PROTOCOL.md, protocol.py, protocol.hpp |
| Python 服务器 | ✅ 完成 | server.py, server_async.py |
| Python 客户端 | ✅ 完成 | client.py, client_async.py |
| C++ 独立服务器 | ✅ 完成 | asio_server.cpp (纯网络，无引擎) |
| C++ 独立客户端 | ✅ 完成 | asio_client.cpp |
| C++ 引擎服务器 | ⚠️ 部分完成 | asio_server_engine.cpp (535行，基本框架) |
| 多客户端支持 | ❌ 未开始 | 当前仅支持 1v1 |
| 断线重连 | ❌ 未开始 | 协议已定义心跳机制 |
| 端到端测试 | ❌ 未开始 | 需要自动化验证 |

---

## 实施阶段

### Phase 1: C++ 引擎服务器完善 (高优先级)

**目标**: 确保 C++ 服务器能正确集成真实 GameEnv 引擎，处理多客户端连接。

**任务**:
1. **验证 asio_server_engine.cpp 的 SessionStart 流程**
   - 检查 seed/left_agents/right_agents 是否正确传递给 GameEnv
   - 验证 SetControllerSetup 调用是否正确
   - 测试 headless 模式下的引擎初始化

2. **完善多客户端连接管理**
   - 实现客户端槽位分配（SlotAssignment）
   - 验证 left_agents + right_agents 的总槽位数
   - 处理客户端连接/断开事件

3. **帧循环稳定性测试**
   - 连续运行 1000+ 帧无崩溃
   - 验证 StateHash 每 K 帧发送
   - 处理客户端超时（默认输入填充）

### Phase 2: Python 客户端对接 C++ 服务器 (高优先级)

**目标**: 验证 Python 客户端能连接 C++ 服务器并完成完整游戏流程。

**任务**:
4. **协议兼容性验证**
   - 测试 Python client → C++ server 的消息格式
   - 验证字节序（little-endian）一致性
   - 处理消息类型枚举值对齐

5. **端到端流程测试**
   - Connect → SessionStart → Ready → FrameInput → AuthoritativeFrame
   - 验证 StateHash 校验
   - 测试心跳包交互

6. **Python 环境封装**
   - 实现 FrameSyncClient 类，封装底层协议
   - 提供 step()/reset() 接口给 RL 训练
   - 处理异步网络与同步游戏循环的协调

### Phase 3: 11v11 多人支持 (中优先级)

**目标**: 支持 11v11 完整足球比赛，每队多个客户端。

**任务**:
7. **多槽位管理**
   - 服务器支持 22 个槽位（11+11）
   - 客户端可控制多个槽位（如一个客户端控制全队）
   - 槽位分配策略（固定/动态）

8. **输入聚合与广播**
   - 服务器收集所有客户端的 FrameInput
   - 超时处理：缺失输入用默认值填充
   - 广播 AuthoritativeFrame 给所有客户端

9. **状态同步优化**
   - 增量状态同步（仅发送变化部分）
   - 带宽优化（压缩 SlotInput）
   - 延迟统计与监控

### Phase 4: 断线重连与鲁棒性 (中优先级)

**目标**: 实现可靠的断线重连机制，保证游戏连续性。

**任务**:
10. **断线检测**
    - 基于心跳超时的断线检测（HEARTBEAT_MISS_LIMIT=5）
    - 客户端检测服务器无响应
    - 服务器检测客户端超时

11. **自动重连**
    - 客户端断线后自动尝试重连
    - 重连时状态恢复（从最近的 StateHash）
    - 重连超时处理

12. **状态恢复**
    - 服务器保存最近 N 帧的完整状态
    - 重连客户端从检查点恢复
    - 处理重连期间的帧丢失

### Phase 5: 端到端确定性验证 (低优先级)

**目标**: 建立自动化测试体系，验证多客户端的确定性一致性。

**任务**:
13. **多客户端 StateHash 比较**
    - 3 个客户端同时运行同一场景
    - 每 10 帧比较 StateHash
    - 验证 1000 帧内 100% 一致

14. **自动化测试脚本**
    - 实现 run_e2e_test.py 的多客户端版本
    - 支持参数化测试（不同 seed/场景）
    - 测试结果持久化

15. **性能基准测试**
    - 测量帧处理延迟（目标 < 16ms @ 60fps）
    - 测量带宽消耗
    - 压力测试（22 客户端同时连接）

---

## 依赖关系

```
Phase 1 (C++ 服务器) → Phase 2 (Python 客户端) → Phase 3 (11v11)
                                          ↓
                                   Phase 4 (断线重连)
                                          ↓
                                   Phase 5 (确定性验证)
```

## 验收标准

1. **Phase 1**: C++ 服务器能处理 2 个客户端连接，运行 1000 帧无崩溃
2. **Phase 2**: Python 客户端能连接 C++ 服务器，完成完整游戏流程
3. **Phase 3**: 支持 4 个客户端（2v2）同时游戏，StateHash 一致
4. **Phase 4**: 模拟断线后自动重连，游戏状态恢复
5. **Phase 5**: 3 客户端 1000 帧 StateHash 100% 一致

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 引擎 headless 模式不稳定 | 高 | 使用 MockRenderer3D，增加错误处理 |
| 字节序/对齐问题 | 中 | 严格测试协议兼容性，使用 packed 结构 |
| 带宽瓶颈（11v11） | 中 | 实现增量同步，压缩 SlotInput |
| 断线重连状态不一致 | 高 | 服务器保存完整状态快照，重连时全量同步 |

---

## 相关文件

- `third_party/gfootball_engine/src/frame_sync/asio_server_engine.cpp` — C++ 引擎服务器
- `third_party/gfootball_engine/src/frame_sync/asio_client.cpp` — C++ 客户端
- `gfootball/frame_sync/server.py` — Python 服务器
- `gfootball/frame_sync/client.py` — Python 客户端
- `gfootball/frame_sync/protocol.py` — 协议定义
- `third_party/gfootball_engine/src/frame_sync/protocol.hpp` — C++ 协议定义
