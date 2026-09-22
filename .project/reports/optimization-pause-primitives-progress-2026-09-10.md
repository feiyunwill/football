# 优化进展：权威暂停的客户端执行与输入清理

2026-09-10。对应 ms22 → plan22.1.2 → task22.1.2.1，并继续维护 task21.1.2.1 的预算约束。已实现并验证控制格式、客户端边界回退、输入冻结和恢复提交顺序；当前对外比赛仍协商 v5，联机暂停尚未接通，任务与整体目标继续未完成。

## 审查与实现

暂停不能只让画面停止，也不能在恢复时继续使用暂停前排队的射门。客户端可能已经预测到权威暂停边界之后，因此需要撤销越界预测，并明确哪些输入已在新的会话代次中作废。

[match_control.py](../../gfootball/frame_sync/match_control.py) 定义不可变控制状态、严格的小端控制/确认格式和带代次的输入格式。状态依次为 RUNNING、下一代次 PAUSED、下一代次 RESUMING、同代次 RUNNING 提交；范围、重复、冲突、越代、长度和非法类型均检查。保留编号 19/20/21 尚未加入运行中的 v5 传输解析器。

[ClientLogicLoop](../../gfootball/frame_sync/client_logic.py) 新增显式控制初始化接口，在会话原点验证帧号和规范摘要。控制由逻辑所有者处理，收到暂停后停止采样、重试和新预测，按已有预算消费边界之前的权威帧，通过已有快照撤销越界预测。核对 hash、清空作废输入与重试记录后才 ACK；延迟确认 hash 的有界历史继续保留。失败时关闭客户端并释放缓存。

恢复准备阶段仍冻结。RUNNING 提交必须被逻辑层实际消费，之后才能采样；同批到达的提交与权威帧按此顺序处理。若提交后紧接再次暂停，传输必须依次提供两条控制，不能覆盖为一个最新值。新增 `commit_control()` 本地消费契约；后续实际传输将实现至多两条控制记录的收件存储，目前还未启用。

[InputBuffer](../../gfootball/frame_sync/graphical_input.py) 新增线程安全的 `set_suspended(bool)`，清空方向和待消费动作边沿。恢复后必须先观察一次有焦点的中立游戏输入，持续按住的方向/动作、相反方向组合和手柄摇杆不会自动重启。保存和退出继续按原命令边沿工作。暂停发布一次权威回退及展示历史中断，空闲 tick 不重复序列化同一快照。

接口、输入细则见[使用说明](../../gfootball/doc/match_control.md)，服务端和传输的剩余工作见[实施约束](../optimization/pause-protocol-design.md)。没有改写原生物理暂停状态或存档物理格式。

## 自动检查

新增 [test_match_control.py](../../gfootball/frame_sync/test_match_control.py) 共 35 项：格式 9 项、逻辑 19 项、输入 7 项。它调用实际 ClientLogicLoop、LogicStateHolder、InputBuffer 和 FrameInputWindow，使用明确的独立状态机引擎及可控消息投递夹具，不伪装为 GameEnv 或真实暂停网络。

检查覆盖：独立十六进制格式预期、代次与容量边界、受预算限制的追帧、预测回退与摘要后确认、迟到 hash、输入所有者失败、确认拒绝、采样/发送期间收到暂停、重复控制、恢复提交与再次暂停顺序、暂停中的终局清理、持续按住和短按、焦点/手柄断开及保存退出。模拟 1000 次暂停 tick 验证无额外步进/重试，另有 100 次 tick 验证不重复快照；这不是实际长时间运行或设备性能证据。

首次完整 332 项运行有 1 项新测试预期错误：第四次无权威消息的 tick 会触发现有保护，仅前三次进行了预测，展示帧应为 2。修正测试前置预期后，保留“超过暂停边界、回退并停止重复快照”的全部检查；[首次失败归档](../optimization/benchmarks/python-pause-primitives-match-windows-20260910-a/report.json)保留，最终 b 目录完整重跑通过。

| 检查 | 本轮结果 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、文件/存档/回放与新控制原语 | 332 项通过，122 个来源文件 | [报告](../optimization/benchmarks/python-pause-primitives-match-windows-20260910-b/report.json) |
| 共享 TCP/UDP、恢复、预测和展示 | 219 项通过，45 个来源文件 | [报告](../optimization/benchmarks/python-pause-primitives-network-windows-20260910-a/report.json) |
| 所有权、资源池、录制和回放组件 | 146 项通过，36 个来源文件 | [报告](../optimization/benchmarks/python-pause-primitives-recording-windows-20260910-a/report.json) |
| 实际资源与 Python 策略读取 | 复用此前 21 个来源文件均匹配的证据，本轮未重测 | [报告](../optimization/benchmarks/python-match-cadence-identity-files-windows-20260910-a/report.json) |

三份最终回归无失败、错误、跳过或各自受检工作线程/进程/锁遗留。比赛和共享网络报告无已检测异步警告。四份报告、224 个来源条目及三个测试日志均重新核对 SHA256，见[证据清单](../optimization/benchmarks/python-pause-primitives-evidence-20260910.json)。前次比赛和共享网络报告相关源码指纹已过期，保留为历史。

实际执行为 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0；完整比赛探针解析 41 个 Python 3.9 语法文件，没有运行 Python 3.9。当前 v5 的最大原点 UDP 故障回归仍验证 1 MiB、5 帧和 1200 字节数据报上限；这些测量不构成暂停网络、WAN 或性能提升证明。

## 下一任务

按现有里程碑继续接入 v6 原点与 MatchReady、受限控制收件队列、服务端帧边界和恢复 ACK 屏障、旧输入代次拒绝、超时与断线恢复，然后接通 Local/Host/Join 和图形反馈，补齐真实 TCP/UDP 暂停矩阵。

原生持牌契约、11 项比赛/图形原生检查及另 28 项环境/原生/渲染检查仍未执行；真实设备、输入延迟、图像连续性、GPU/RSS、长期 p99、后续 AI 与发布验收仍待完成。本轮未执行 C++ 构建、WSL 重试、安装或 Git 操作。四个相关 ready 标志继续为 false，不将局部通过计为产品级验收。
