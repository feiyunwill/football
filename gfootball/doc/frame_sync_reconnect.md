# Python TCP 自动恢复

2026-09-10。入口为 `gfootball.frame_sync.client.ReconnectingFrameSyncClient`。现有同步/异步 Python 服务端共用此版本的恢复服务；原生 C++ 服务及 UDP 恢复还需要独立验收。

## 恢复契约

默认包装器显式协商协议 v3，服务端在 SessionStart、SlotAssignment 之后签发 `SessionToken`：消息类型 14，载荷为非零随机 uint64，共 9 字节。旧 v2 的报文和默认普通 `FrameSyncClient` 握手保持兼容。恢复令牌不会出现在 `stats()` 或测试报告里。当前链路仍是普通 TCP，TLS 和完整安全接入属于后续网络验收。

恢复使用已有 ReconnectRequest 及 StateSnapshot 格式。每次尝试必须匹配原 seed、双方槽数和分配槽，快照的下一帧编号不得落后于本地已确认帧。客户端按最多 4096 字节的 socket 读取接收大快照；声明长度在分配前验证，默认最多 1 MiB。预分配 bytearray 接收后转换成不可变 bytes，转换瞬间最多同时保留两份受限载荷。条数、对象头、普通解析缓冲和权威帧队列另受已有预算约束。

实际恢复顺序：

1. 断线后，后台线程关闭旧连接，按原令牌建立候选连接。
2. 候选连接接收原会话元数据和完整快照；服务器继续用 bot 推进。
3. 逻辑线程调用引擎 `set_state()`，创建从快照下一帧开始的新逻辑循环。
4. 引擎恢复成功才排队发送 Ready。
5. 收到所有自有槽位的 HandbackNotify 后，才触发重连成功回调并恢复输入/逻辑推进。恢复期间积累的连续权威帧和哈希按既有预算补齐。

快照过大、旧帧、会话/槽位不匹配、引擎恢复失败或非法权威数据会终止恢复。不会换成新比赛后报告“恢复成功”。普通网络丢失可以重试；逻辑错误不会通过重连反复重置并再次运行。

## 使用与所有权

首先调用 `connect()`，根据返回的会话与实际房间场景初始化本地引擎，然后 `attach_logic(env)`。此方法创建逻辑循环并发送初始 Ready。后续从同一引擎所属线程调用 `run_one_tick()`，它自动处理断线、恢复和正常帧逻辑。`logic` 属性会在恢复后指向新循环；不要继续驱动恢复前返回的旧循环。

输入通过构造函数的 `controlled_slots_callback` 提供，槽位必须匹配分配。`attach_logic` 接受 `rate_hz`、`state_holder` 和 `LogicLimits`。引擎与 state holder 属于调用方；关闭网络包装器不会关闭调用方引擎。

保留 `set_on_disconnect(callback)`、`set_on_reconnect(callback)`、`set_on_give_up(callback)`，均在逻辑线程的 `tick()` 中调用。重连成功回调参数仍为 `(session, slots)`；此时引擎已经恢复并收到交还控制权通知。回调异常会停止运行，give-up 回调异常也不会重新安排自身。重入或从其他线程执行 tick 会明确拒绝。

后台仅有一个恢复所有者线程，同一时刻最多一个连接尝试/候选连接，不会向执行器无限提交工作。候选客户端使用一个 TCP I/O 线程。`tick()` 不执行连接、退避等待或等待尝试结束；收到快照后，引擎恢复自身的耗时仍发生在逻辑线程，不能保证硬实时。

`close()` 是终止操作，取消 socket I/O 并等待自有线程退出。手动驱动的旧逻辑循环即使没有下一次 tick，也会释放预测历史、哈希和采样缓存。若关闭发生在活动回调中，其占用直到回调退出才释放。活动快照在此期间继续计入包装器的 `snapshot_bytes`。

OS 主机名解析是同步调用，无法强制中断；若它持续阻塞，`close()` 等待恢复所有者 2 秒后明确报错，仍保留该唯一在途工作的所有权，不再创建替代线程。原生引擎调用和用户回调也不能被强制终止。

## 默认期限

| 限制 | 默认值 |
| --- | --- |
| 第一次恢复尝试 | 立即进行 |
| 后续退避 | 1 秒起，每次翻倍，最多 30 秒 |
| 最大尝试 | 10 次 |
| 整次恢复期限 | 60 秒，贯穿连接、快照和 Handback |
| 快照载荷 | 1 MiB |
| 元数据/普通解析缓冲 | 既有 8 KiB |

`ReconnectLimits(max_attempts=0)` 只取消次数限制，仍受整次恢复期限约束。所有期限基于单调时钟；已过期的恢复不能建立新连接或调用引擎恢复。give-up 状态稳定，后续 tick 不会重启计数。

旧原生初始握手可设置 `handshake='native'`；其 host 在初始会话建立后取得真实令牌，再调用 `set_session_token(token)` 绑定。Python 服务端的这个旧协议路径已经用真实 socket 验证，C++ 服务尚未联调。原生协议还没有自动令牌签发，不能把默认 v3 包装器直接视为当前 C++ 服务的即插即用客户端。

## 验证边界

```text
python .project/checks/python_reconnect_probe.py --output NEW_DIRECTORY
python .project/checks/python_reconnect_probe.py --native --output ANOTHER_NEW_DIRECTORY
```

普通检查使用真实 TCP/UDP socket 和明确的独立整数/Adler32 引擎归约器，覆盖自动签发、快照、交还控制权、连续哈希、故障与受影响回归。测试归约器不是 GameEnv。`--native` 额外要求两个原有 GameEnv 服务端检查和一个新的真实 13 帧自动恢复检查，导入缺失会失败，不会跳过或改用替代引擎。本轮没有执行这三项原生检查。

UDP 包装器、原生 C++ 双向故障测试、产品房间/场景信息集成、网络认证与发布级网络性能仍待完成。本实现是优化阶段的局部进展，整体 memory_budget 和网络里程碑保持未完成。
