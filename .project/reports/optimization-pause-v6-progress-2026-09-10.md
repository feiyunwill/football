# 优化进展：TCP/UDP 权威暂停与恢复接入

2026-09-10。对应 ms22 → plan22.1.2 → task22.1.2.1，并维护 task21.1.2.1 的网络与历史预算。Python 比赛已升级到 v6，接通真实 TCP/UDP 暂停屏障、恢复提交、输入代次及原会话恢复。当前检查使用独立测试引擎和真实 socket/文件；Local 暂停、界面入口、真实原生及产品整体验收仍待完成。

## 审查与实现

此前客户端已有暂停原语，但运行中的 v5 协议没有控制原点、确认屏障或输入代次。仅停止采样无法停止权威物理推进，暂停前排队输入也可能在恢复后生效。本轮把控制约束接入实际比赛，而不改变存档中的物理暂停状态。

[原点与收件缓冲](../../gfootball/frame_sync/match_bootstrap.py) 使用 `FMATCH6`、六字段元数据和包含 epoch 的 17 字节 MatchReady。客户端在恢复引擎与核对摘要后绑定控制契约，随后才能 Ready/采样。缓冲保留首条尚未应用的控制，至多两条，支持同批到达的 RUNNING 提交和下一次暂停；重复提交不会覆盖屏障或重新执行输入。

[比赛服务端](../../gfootball/frame_sync/multiplayer_transport.py) 在权威所有者上处理最新暂停意图。收集中的帧先完成，随后建立包含下一帧号和规范校验值的 PAUSED 屏障，清空未来输入窗口。PAUSED → RESUMING 增加代次；在线参与者确认恢复准备后才广播同代次 RUNNING。每个 Peer 只保留一个待确认状态，期限为 `min(3 秒, ready_timeout)`，心跳不能延长；超时断开后沿用现有 AI 接管政策。

[协议解析与输入窗口](../../gfootball/frame_sync/server_state.py) 接受带 epoch 的输入格式。旧 epoch 输入在结构、槽位所有权与数值校验后丢弃；未来 epoch、暂停期间当前代次输入和旧格式输入被拒绝。恢复后相同帧号可在新代次重新采样，同代次的输入不可变规则仍有效。当前可接受输入只执行一次窗口验证，避免为代次校验重复完整准入工作。

[客户端逻辑](../../gfootball/frame_sync/client_logic.py) 与 [恢复工厂](../../gfootball/frame_sync/client_reconnect.py) 在原点绑定控制状态，并在原预算内追帧、回退预测、核对边界、清理输入，再发送确认。恢复时重新验证原点控制；Ready 的 epoch 过期会拒绝并重试原会话。控制读取或 ACK 排队过程中发生的真实断线按网络恢复处理；非法控制、摘要不一致和引擎失败仍明确终止。

[Host/Join 所有者](../../gfootball/frame_sync/multiplayer_runtime.py) 共用逻辑循环处理大厅和比赛，移除独立的首帧输入缓存。大厅不预测，但能处理暂停与恢复。Host 增加 `set_paused/pause/resume`，暂停中的 `advance()` 返回 false；公开服务端 `run_loop()` 同样停止物理推进，继续处理控制和传输。图形 Host/Join 已把控制回调绑定到输入冻结与展示等待状态；Local 和界面暂停请求尚未接通。

结束优先于尚未完成的暂停确认期限，保留 UDP 结束排空窗口，避免已结束比赛被暂停 ACK 超时提前拆掉。暂停保存只记录物理权威状态，恢复运行后的录制与独立回放保持一致。接口及完整字段见[使用说明](../../gfootball/doc/match_control.md)、[节拍协议](../../gfootball/doc/match_cadence.md)和[实施约束](../optimization/pause-protocol-design.md)。

## 自动检查

新增 [test_match_pause_network.py](../../gfootball/frame_sync/test_match_pause_network.py) 共 22 项：6 项缓冲/报文检查和 16 项实际比赛集成检查；多数集成路径分别执行 TCP 与 UDP。沿用明确的 MatchOracle，不把它作为 GameEnv。既有 35 项控制原语也纳入完整回归。

检查包括分片、独立 Ready 字节预期、边界与 hash 拒绝、控制顺序、控制/确认丢失与重复、UDP 交付确认丢失、旧输入代次、确认超时仍有心跳、收集中请求、暂停原点重连、过期 Ready 重试、恢复准备中再次暂停、控制处理期间断线、暂停保存/回放、终局与公开服务端循环。连续再暂停检查验证控制队列、输入和历史回收，不用放宽生产容量通过测试。

接入过程中旧 v5 固定预期需要更新，另有新测试误用连接数查询接口导致错误；已修正为独立 v6 字节预期和实际公开方法。下面的最终完整运行在全部源码修改结束后执行，没有忽略失败或跳过测试。

| 检查 | 本轮结果 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、文件/存档/回放与 v6 控制 | 354 项通过，123 个来源文件 | [报告](../optimization/benchmarks/python-pause-v6-match-windows-20260910-a/report.json) |
| 共享 TCP/UDP、恢复、预测与展示 | 219 项通过，45 个来源文件 | [报告](../optimization/benchmarks/python-pause-v6-network-windows-20260910-a/report.json) |
| 所有权、资源池、录制与回放组件 | 146 项通过，36 个来源文件 | [报告](../optimization/benchmarks/python-pause-v6-recording-windows-20260910-a/report.json) |
| 实际资源及 Python 策略文件读取 | 本轮重新测量通过，21 个来源文件 | [报告](../optimization/benchmarks/python-pause-v6-identity-files-windows-20260910-a/report.json) |

三套回归均无失败、错误、跳过或各自受检资源遗留。比赛与共享网络未检测到异步警告；录制引擎池的 live/leased/idle 最终均为零。四份报告、225 个来源条目和三个测试日志的 SHA256 均重新核对，见[证据清单](../optimization/benchmarks/python-pause-v6-evidence-20260910.json)。前轮比赛、共享网络和文件身份报告中的相关源码指纹已过期，保留为历史。

执行环境为 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0；比赛探针解析 42 个 Python 3.9 语法文件，没有运行 Python 3.9。实际最大原点 UDP 回归为 1 MiB、5 帧，丢弃 55、重复 44、乱序 37 个数据报，观察耗时 4.3195 秒，最大数据报 1200 字节。共享恢复探针的 1 MiB 传输为 0.7274 秒、丢弃 53、重复 43、乱序 37，仍为 1200 字节。两者在本机并发回归环境中测量，不作为性能提升、WAN 或设备延迟结论。

实际资源读取 90,974,146 字节，Python 分配峰值 1,155,745 字节、单次请求最多 65,536 字节；策略读取 383,500 字节，Python 分配峰值 157,515 字节。它们是文件读取与 Python 分配观察，不是整个进程、原生内存或 GPU 预算。

## 下一任务与验收边界

继续实现 LocalPlayer 的权威暂停，以及界面请求和可理解的状态反馈；保持保存/退出、持键释放、所有者线程和有界命令契约，并检查首帧前暂停与大厅期限的交界。然后补齐 GameEnv、SDL 键盘/手柄、真实暂停图像、长暂停、输入到画面延迟及长期 p99。

原生持牌契约、11 项比赛/图形原生检查及另 28 项环境/原生/渲染检查仍未执行；C++ 通用协议仍为 v2，本轮未实现或验证 C++ 比赛 v6 互通。原生字节/GPU/RSS、POSIX、WAN、后续 AI 与发布验收继续待完成。本轮未构建 C++、重试 WSL、安装依赖或执行 Git 操作。`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 的 ready 均保持 false，任务与整体目标继续自动推进。
