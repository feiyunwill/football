# TCP 与大厅容量：实施进度

归属：ms-21.1 性能与容量 → plan-21.1.2 容量与预算 → task-21.1.2.1 网络与回滚内存预算。

本报告接续[快照、回放和 UDP 进度](optimization-task-21.1.2.1-progress-2026-09-09.md)。本轮完成共用 TCP 发送组件、大厅服务端/客户端，以及独立 TCP 权威服务器的局部实施和验证。GameEnv 集成 TCP、其他 TCP 客户端、日志和渲染队列仍未全部处理，`memory_budget.ready` 保持 `false`，任务、里程碑和整体目标均未标记完成。

## 实际改动

| 模块 | 默认容量与期限 | 满载、异常与恢复 |
|---|---|---|
| BoundedTCPWriter | 256 条、2 MiB 待发送数据，计入正在写入的消息；5 秒单次写期限；至多一个读操作 | 入队前保留数量和实际 vector capacity；拒绝超限，消费后可以重试。关闭时丢弃等待项，在途缓冲保留至完成回调；慢读端超时关闭套接字 |
| LobbyServer | 总连接 128，含仍持有读写缓冲的关闭中连接；每连接发送 256 条/128 KiB、接收 16 KiB；未设置身份期限 30 秒 | 超过连接上限在创建会话前拒绝；超限发送断开该连接；完整清理后重新接入。名字 32、聊天 4096、开赛地址 96 字节，读取长度头即可拒绝超大声明 |
| LobbyClient | 同样有界发送；房间最多 256；接收容量 `3 + 256×ROOM_METADATA_SIZE + 4096`；聊天最多 1024 条、字符串 capacity 合计 1 MiB | 发送方法返回成功/失败，过载断开并暴露原因；聊天淘汰最旧项，清空后可恢复；非法消息不更新已有房间列表。每次 poll 至多执行 64 个完成事件，并在事件之间检查 2 ms 时间配额 |
| 独立 FrameSyncServer | 每队至多 11、总受控槽位 1–22；一个会话占一个槽位；接收 8192 字节；发送沿用 TCP 默认预算；未就绪期限 30 秒 | 开赛前释放已断开会话后可重新接入；开赛后的槽位保留，拒绝尚无状态引导的新连接。非法数量/槽位/输入立即关闭；慢读端不会持锁阻塞其他客户端 |

预算分别限制有效载荷容量和对象数量，并不等于整个进程的精确堆/RSS、所有纹理资源或操作系统套接字内存上限。客户端另保留有界聊天对象数组、房间数组和每次最多一个回调消息副本。聊天淘汰会处理短字符串赋值保留旧大容量的问题，测试逐次核对实际字符串 capacity。

大厅和独立 TCP 服务端的外部对象使用共享实现管理异步生命周期。stop 在提交异步清理前先同步关闭发送组件，防止 io_context 已停止时，在它销毁期间重新提交清理任务。取消写不会提前释放正在被 Asio 引用的消息。连接注册表在读操作、在途写实际结束后才释放对应容量。

大厅客户端使用私有 IO 上下文，只有 poll 推进收发和回调；外部 IO 线程不会并发修改 UI 状态。回调先获得独立消息副本，再消费解析缓存，允许回调断开连接或替换自身。API 仍要求单线程调用，连接建立/域名解析仍是同步操作；实时收发期限需要持续 poll 才能处理，这不代表连接建立期限已验收。

独立 TCP 服务器抽出实际生产实现到 `engine/src/frame_sync/tcp_frame_server.hpp`，原 `asio_server.cpp` 使用该实现，旧实现按仓库规则保留在注释中。它原先发送客户端未协商支持的增量权威帧，现发送完整帧；冻结输入、编码和发送队列入队受同一个互斥锁保护，网络写入由独立异步执行器推进。命令行在缩窄整数前验证范围，SIGINT/SIGTERM 执行正常关闭。

大厅协议另增加固定字符串终止符、枚举范围和人数验证。RoomConfig 的原始布尔字节在载入 bool 对象前检查，避免不合法网络字节触发未定义行为。解码失败保留调用者原数据。

## 可复现证据

- [TCP 组件和大厅原始结果](../optimization/benchmarks/tcp-lobby-preflight-20260909/report.json)：64 项 C++ 测试通过，无禁用项。包括共用 writer 10、大厅服务端容量 10、大厅客户端容量 10、实际大厅流程 3、协议 13、RoomManager 18。使用 ASan/UBSan，开启泄漏检测。报告 SHA256：`5cc41b96a73b7f40cc20151a1f42bfc9a40eb534be7c6e3f5d55c1a359a3a865`。
- [实际独立 TCP 服务器测试](../optimization/benchmarks/tcp-frame-server-preflight-20260909/report.json)：另 8 项 ASan/UBSan 测试通过。慢读端与正常端共享同一个服务器，22 槽位完整帧；慢端恰好发生一次写超时，正常端仍收到至少 200 个连续编号的完整权威帧，无队列溢出/非法消息。压力配置为 1 ms 收集等待、1 ms 帧间隔、100 ms 写期限，并请求较小的套接字缓冲；这是加速的协议压力测试，不是 GameEnv 帧性能或真实远程网络测量。报告 SHA256：`c4aea1e244808db2409148e344de0dfc32b6297fba2dbeb1d033d185634c63f1`。
- 共用 writer 单独覆盖 4 MiB 在途消息取消时的保留/释放、100 轮填满排空、对端 RST、慢读端与正常连接并行、并发生产者和销毁后的回调。大厅客户端覆盖 600 条长短混合聊天、1100 条短聊天、完整 256 房间列表分片、回调内断开/重连/替换回调与旧缓存隔离。
- [Release 可执行程序探测](../optimization/benchmarks/tcp-native-capacity-release-20260909-final/report.json)和[检测构建探测](../optimization/benchmarks/tcp-native-capacity-sanitized-20260909-final/report.json)：各 7 个场景通过。覆盖空槽位、整数缩窄绕过、尾随字符、种子溢出、非法端口、非法长度头，以及实际连续帧 0/1/2 原样广播不同输入后带连接 SIGTERM 退出。检测构建正常退出码 0 且无 ASan/UBSan/LSan 报告。
- 上述执行程序不链接 GameEnv；不能把原样输入广播当成真实引擎确定性测试。真实引擎已有的 128 帧确认/回滚证据见上份报告，集成 TCP 的对应验证仍待完成。
- 探测入口：`.project/checks/tcp_capacity_probe.py --server <frame_sync_server> --output <新证据目录>`。C++ 构建目录 `/tmp/football-optimization-memory-tests`，独立程序检测构建 `/tmp/football-optimization-memory-asio`、Release `/tmp/football-optimization-memory-asio-release`。所有编译为 `-j 1`。
- `quality.py validate` 通过：56 个节点、31 项检查。源码差异检查通过。尚未运行完整容量门禁或重验全部前置门禁；原始性能基线及归档未变。

## 保留的失败与边界

首次可执行程序探测错误地把打包的十字节 SlotInput 编码成十二字节，同时按错误长度读取权威帧，造成输入比较失败。改为遵循 protocol.hpp 的十字节静态断言后，两类构建通过；[首次失败记录](../optimization/benchmarks/tcp-native-capacity-sanitized-20260909/report.json)保留，未修改产品断言、关闭检测器或覆盖失败目录。

共用 writer 最初两个测试过早假设 FIN/RST 已经到达；修正为等待真实 EOF、发送足够大的在途消息后再检测 RST。TCP 服务端测试初次编译误用了两个编码函数签名，按生产接口更正。以上均为测试实现错误，不算产品缺陷或通过证据。

## 下一步仍需实现

1. `integrated_server.cpp` 仍有持锁同步发送、未注册握手会话无限增长、接收缓冲无界，以及托管/归还通知重复获取同一互斥锁的问题。需要接入现有 writer、连接/接收限制、生命周期管理，并用真实 GameEnv 场景验收。
2. `integrated_client.cpp`、`asio_client.cpp` 与 `reconnecting_client.hpp` 仍需逐一处理同步发送、接收边界、权威帧超限或哈希不匹配后的明确停止行为。当前集成服务端重连 token 被忽略、状态帧边界和晚加入同步也未完成网络验收，不能宣称已修复。
3. 运行时队列已追到真实路径：GraphicsOverlay2D_Image2DInterpreter::OnPoke 产生带纹理 intrusive_ptr 的 Overlay2DQueueEntry；GraphicsTask::Render 在同一次渲染流程中消费到临时 vector，再提交 RenderOverlay2D。`MessageQueue` 为头文件实现，没有 messagequeue.cpp。需定义容量与异常渲染后的清理策略，不能静默丢弃带资源所有权的命令。
4. base/log.cpp 的同步输出仍使用共享 ctime 缓冲，FatalError 故意解引用坏指针；全仓库还存在 Python observation_processor 的视频/回放 dump，需要继续分清诊断历史、日志和用户产物。现有审查不足以宣称所有运行时输出均已受控，项目质量证据不得当作游戏日志清理。
5. 全部边界与故障恢复接入正式 memory_budget 检查后，再基于最新源码重验前置任务。容量任务通过后，进入 task-21.1.2.2 的长时间增长和稳态性能验收。
