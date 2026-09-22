# 原生重连的生产调用链复核 — 2026-09-14

本次复核对应 ms-23.1 → plan-23.1.1 → task-23.1.1.2。战术 AI 的本轮完整回归现已通过。下面是独立的源码与调用链审查，没有改变正式重连实现，也没有将重连任务标为通过。

1. **TCP 产品入口尚未接入完整自动重连。** CMake 将 football_client_tcp 指向 integrated_client.cpp。入口只调用一次 connect，再进入 RunNativeClient；网络失败后退出循环、保存已有回放并返回失败。解析器明确按首次连接处理，不接受未请求的快照。现有 TCPFrameClient::Resume 与 ReconnectingClient::ResetForReconnect 的限定调用图只找到测试调用；直接检查协议代码也确认它们走旧 SessionStart/Connect/ReconnectRequest 握手。不能把这些组件的通过结果移用于当前原生 50Hz 产品客户端。

2. **原生 TCP 服务器也没有走通恢复握手。** EngineTCPServer::ProcessLocked 在 native_product 的 Identify 阶段只接受 NativeMatchContract::kHello，随后发送描述并分配槽位。旧 ReconnectRequest 分支在这条提前返回路径之后。已有快照生成、恢复等待和 Handback 可作为实现依据，但需要明确接入原生协议。UDP 仍保留断线槽位，缺少同局重新认证、快照分发和恢复流程。

3. **旧令牌不能直接用作新增产品恢复凭据。** MakeSessionToken 把 slot、seed 和 session_id 组合后进行固定 FNV 运算，没有加入服务器秘密或新随机量。seed 左移 16 位与 session_id 左移 32 位的区间还会重叠并按位或：同一槽位下，seed=65536、session_id=2/3 得到相同的哈希前值；seed=20260914、session_id=2/3 也相同。这是对当前整数表达式的精确碰撞证明，并非已执行的网络攻击。原生恢复应使用与比赛实例绑定、可过期和轮换的不可预测凭据，并显式区分协议能力。

4. **UDP 全量快照需要有界分片。** ReliableUDPChannel 当前最大完整包为 1200 字节，超过负载上限会拒绝。不能直接把 TCP 的整块快照发送方式复制到 UDP。恢复消息还须包含明确的快照起始帧、长度和完整性信息，限制接收内存及等待时间，并在该快照之后保持权威帧连续。

[实际 TCP 入口](../../engine/src/frame_sync/integrated_client.cpp)、[共用产品主循环](../../engine/src/frame_sync/native_client_loop.hpp)、[TCP 权威及快照流程](../../engine/src/frame_sync/engine_tcp_server.hpp)、[已有恢复组件](../../engine/src/frame_sync/tcp_frame_client.hpp)、[UDP 权威入口](../../engine/src/frame_sync/asio_server_engine.cpp)、[旧令牌实现](../../engine/src/frame_sync/protocol.hpp)、[UDP 包上限](../../engine/src/frame_sync/reliable_udp.hpp)。

下一阶段仍按 task-23.1.1.2 推进，实施顺序如下：

| 顺序 | 实现任务 | 通过所需的实际证据 |
| --- | --- | --- |
| 1 | 保留当前真实客户端断线退出的对照，明确原生恢复协议和凭据生命周期 | TCP/UDP 实际进程、断线位置、原始输出、旧版本拒绝/兼容规则 |
| 2 | 接入服务器原槽位恢复、等待期间 AI 继续接管、帧边界交还 | 有效凭据恢复原槽位；错误、过期及跨比赛凭据拒绝；未分配槽位不被占用 |
| 3 | 实现有界快照传输、主线程/仿真线程恢复职责和连续追帧 | 快照状态与起始帧对应；分片丢失、重复、乱序、截断受控；其他客户端继续比赛 |
| 4 | 接入实际产品客户端的重试状态、发布时钟与输入历史重置、回放连续性 | 无旧输入回填；真实客户端从恢复帧继续；回放与权威全部哈希一致 |
| 5 | 加入故障矩阵并注册正式检查器 | 两客户端持续变化输入，断线两侧、反复恢复、超时和终止均自动验证，Release/ASan 覆盖 |

既有 FNAT1 节拍、历史回放、固定 oracle 和输入窗口不能被静默重解释。实现新恢复能力时必须明确版本边界及回放缺口/快照段的表达，再执行新旧双方的拒绝与恢复用例。以上仍是待实现的产品合同，不是本次已完成的功能。

[限定源码、哈希与审查结论](../optimization/benchmarks/native-reconnect-review-20260914-a/findings.json)、[调用图及索引覆盖](../optimization/benchmarks/native-reconnect-review-20260914-a/graph.json)、[令牌字段碰撞证明](../optimization/benchmarks/native-reconnect-review-20260914-a/token-collision.json)。图索引为尽力覆盖；TCP 产品客户端第 636 行、服务器第 501 行有部分索引标记，已经结合直接源码读取，结论限定在列出的生产入口及协议路径。
