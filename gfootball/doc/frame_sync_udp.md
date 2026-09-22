# Python UDP 传输与客户端

2026-09-10。适用于 `gfootball.frame_sync.client_udp` 导出的 `ReliableUDPClient`、`FrameSyncUDPClient` 和 `UDPLimits`。

## 已实现的行为

可靠层使用现有 C++ 格式：DATA 为 `<BIH` 加载荷，ACK 为 `<BI`；最大 UDP 数据报 1200 字节，应用载荷 1–1193 字节。头、声明长度与数据报实际长度必须完全一致。Python 接收端先按 uint32 序号排序，再向应用层投递一次；重复包重新 ACK，最近重复包内容冲突则关闭连接。序号跨 `0xffffffff → 0` 使用有限窗口比较。

接收窗口之外的未来序号、接收预算超限、序号缺口超时、重传耗尽或硬 I/O 错误都会终止流并释放队列。不会跳过丢失的数据继续解析。发送窗口满时，`ReliableUDPClient.send()` 返回 `False`，不消耗序号；ACK 释放容量后可重试。`failure_reason` 区分容量背压与终止故障。

默认可靠层限额：

| 项目 | 默认值 |
| --- | --- |
| 未确认发送 | 256 包 / 256 KiB |
| 乱序及正在投递的载荷 | 256 包 / 256 KiB |
| 已投递摘要历史 | 256 条，每条 16 字节摘要 |
| RTT 样本 | 32 条 |
| RTO | 初始 140 ms；平均 RTT + 4 倍平均绝对偏差，限制为 50–1000 ms |
| 最大重传 | 5 次，初次发送另计 |
| 缺口期限 / 交付期限 | 2 秒 / 6 秒 |
| 接收速率 | 2000 包/秒，突发 512 包，超出时丢弃当前数据报 |

重传过的包不用于 RTT 估计。时间均为单调时钟；重复数据、ACK 和部分业务字节不能延长业务存活期限。未发送成功的数据也受初次入队的交付期限约束。

字节预算统计所持有的不可变 `bytes` 对象及其 Python 对象头；字典和队列元数据另受条数限制。已投递摘要的对象开销也可由 `stats()` 观察。活动回调持有的载荷在回调返回前仍计入接收预算，即使 `stop()` 已调用。预算不等同于进程 RSS、操作系统套接字缓存或调用方保留对象的总量。

## 客户端生命周期

`FrameSyncUDPClient` 使用一个非 daemon I/O 线程，统一处理收发、重传、心跳和期限。可靠层不另开线程。连接的 IPv4 UDP socket 由内核过滤其他源端点；这项过滤不构成加密身份认证。

`connect()` 发出版本握手，等待 SessionStart 和 SlotAssignment，返回 `(session, slots)`。调用方完成引擎初始化后显式调用 `send_ready()`。反复 Ready 不会重复发送。主线程可用 `send_frame_entries()` 传入已采样的输入，或者用 `send_frame_input()` 调用配置的输入回调；槽位必须与实际分配严格一致。回调在传输锁之外执行，最多消费 23 项，旧连接的采样结果无法进入后续连接。

应用层复用 `ClientBuffers`：严格校验连续权威帧、槽位、方向、按钮和哈希；默认权威队列 1024 帧 / 512 KiB，哈希和时间戳各 1024 条，应用发送队列 256 条 / 2 MiB。可靠层和应用发送队列分别计费。可靠层背压时保留原应用入队时间，超过写期限就终止。消费者不读取权威帧导致积压超限也会终止，不能静默丢帧。

`close()` 和 `reset_for_reconnect()` 清理队列并等待 I/O 线程退出，由线程在 I/O 结束后关闭 socket。握手超时会执行相同清理。客户端可作为上下文管理器使用。OS 主机名解析仍是同步调用，不能以客户端握手期限强制中断；客户端也不能强制终止调用方自己的输入回调。

单独使用 `ReliableUDPClient` 时，传入借用的非阻塞 IPv4 UDP socket、数字端点和回调。默认 `start()` 拥有一个重传线程；`start(background=False)` 要求现有 I/O 所有者周期调用 `poll()`。接收所有者调用 `handle_received(packet, remote_addr)`。`stop()` 等待自有重传线程，借用 socket 由其所有者在接收工作结束后关闭。停止后的通道不能重新 start。

## 验证与未完成项

本轮 Windows Python 3.14.6 的 86 项检查包含实际双向 loopback 丢包/重复/乱序、完整 ACK 退款、22 槽位、积压、错误包、心跳、握手取消、30 次退出，以及 UDP 接入既有回滚逻辑后的 3 帧确认哈希。逻辑测试使用明确的整数状态机，不是 GameEnv。

```text
python .project/checks/python_udp_probe.py --output .project/optimization/benchmarks/python-udp-local-run
```

输出目录必须不存在，脚本保存日志、平台和实际导入源码哈希。源码兼容 Python 3.9 的语法检查已执行；3.9 运行时未执行。

原生服务可用时，单个新比赛/新服务上运行以下检查；一次连接内必须实际收到至少 10 帧、状态哈希和心跳才能成功：

```text
python -m gfootball.frame_sync.test_e2e_udp
```

历史 UDP 服务会保留断连槽位直到比赛结束，因此不能把三个独立检查依次指向同一场已结束的客户端会话。脚本中的单项函数各需要新服务；CLI 统一使用一场会话。

<!-- 2026-09-10: 自动恢复已有独立实现，保留旧状态记录。
当前 C++ `ReliableUDPChannel` 已有容量限制，但接收端仍缺少排序/去重。本轮未执行 C++ UDP 服务或 GameEnv，也没有 WAN、拥塞控制、跨机器时钟或目标平台网络性能验收。Python 自动重连包装器仍是旧实现，尚未实现可靠的 token/snapshot/Ready 恢复链；本客户端支持初始会话，不能将新建会话称为恢复原比赛。原生 UDP 目前也没有快照分片恢复协议。以上事项保留在网络里程碑，不能据本轮局部通过将整个网络环节标为完成。
-->

当前 C++ `ReliableUDPChannel` 仍缺少接收排序/去重，原生服务和 WAN 验收未完成。Python 自动恢复现已实现显式 cookie/epoch 协议及配套服务端，详见 [UDP 会话恢复](frame_sync_udp_resume.md)。它不能与现有 C++ UDP 服务直接互通；普通 `FrameSyncUDPClient` 保留旧协议初始会话行为。
