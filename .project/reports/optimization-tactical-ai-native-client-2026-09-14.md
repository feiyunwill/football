# 真实战术 AI 与原生 UDP 接管 — 2026-09-14

本轮推进 ms-25.1 → plan-25.1.1 → task-25.1.1.1/2，并关联 ms-23.1 的权威输入、断线处理任务。战术实现和 UDP 客户端缺陷已正式修复；AI、完整输入、完整架构和四批历史回放全部通过，本轮运行已结束。当前没有提升产品、网络延迟或硬件验收状态。

<!-- 2026-09-14：输入门禁终态已确认，保留前次状态。
本轮推进 ms-25.1 → plan-25.1.1 → task-25.1.1.1/2，并关联 ms-23.1 的权威输入、断线处理任务。战术实现和 UDP 客户端缺陷已正式修复；最终完整门禁仍在执行，本文会随终态结果补齐。当前没有提升产品、网络延迟或硬件验收状态。
-->

| 原问题及触发条件 | 正式实现 | 验证依据 |
| --- | --- | --- |
| 固定场地、体力、错误剩余时间和不一致的受控球员 | 从真实 GameEnv 读取逻辑坐标、队伍朝向、控球身份、体力、比分、剩余模拟时间和实际控制器对应球员 | 每构建 960 个真实逻辑帧，覆盖种子 42/43、物理步数 2/10，3513 次非零球员索引、331 个定位球帧 |
| 前次权重与按钮残留，可能传给自己 | 每次重建决策；排除自己、失活球员、被阻挡和越位的传球候选；按钮逐帧释放 | 每构建 7288 条策略断言，600 组持球方向对称用例 |
| 无球支援方向不对称，守门员远离球门 | 支援横向偏移跟随进攻方向；守门员守住球门，远球不占用外场追球职责 | 旧候选在 3601 条角色断言中失败 1198 次；修复后 1800 组角色镜像用例通过 |
| 实际 UDP 服务器未接管掉线槽位 | 仿真线程在帧边界接管已分配且断线的槽位；同一份冻结输入用于引擎推进和广播 | 每构建 TCP/UDP × 左/右掉线四场，均至少 151 个接管后帧；未分配的第三槽位保持中性 |
| 客户端把 Takeover 负载字节当成消息类型 | 完整消费 Takeover/Handback，等待完整分片，验证槽位和权威帧边界 | 旧实际客户端在第 59 帧停住并失败退出；修复版本在两侧掉线场景均至少完成 260 帧 |

[真实状态适配](../../engine/src/ai/ai_tactics.cpp)、[有界战术决策](../../engine/src/ai/ai_tactics.hpp)、[共享接管观察](../../engine/src/frame_sync/engine_bot_observer.hpp)、[接管管理](../../engine/src/frame_sync/bot_takeover.hpp)、[UDP 权威入口](../../engine/src/frame_sync/asio_server_engine.cpp)、[实际客户端解析](../../engine/src/frame_sync/integrated_client_udp.cpp)。

战术帧最多容纳两队各 11 名球员、22 个控制槽位，决策本身不使用动态容器。传球考虑前进距离、接球空间和对手对线路的阻挡；射门取实际球门方向；体力限制冲刺，最后 10% 比赛时间依据比分调整选择。定位球仅由裁判指定、已经允许开球的球员执行。踢球冷却按模拟时间计算为 500ms，种子变化或时间回退会重置。TCP、UDP 共用观察和决策，IO 线程只标记连接状态，仿真线程负责 AI 状态。这里描述已验证的确定性启发式行为，不等同于训练 AI、战术强度或完整比赛体验验收。

真实状态测试还验证观察不会改变引擎摘要、完整快照恢复、HID 绑定实际球员及释放全部按钮。原有 512 帧前缀、57 帧死球过渡、30 帧无选中球员后的恢复检查保持原断言，recovered_frames=1 没有修改。旧最小 BotGameSnapshot 接口继续通过 600 个引擎帧和 10000 个发布时钟事件的合同。

[最终私有战术候选](../optimization/benchmarks/native-tactics-contract-20260914-d/report.json)、[首次正式 17 文件变更](../optimization/benchmarks/native-tactics-adoption-20260914-a/canonical-changes.json)、[客户端修复的正式变更](../optimization/benchmarks/native-tactics-adoption-20260914-b/canonical-changes.json)。

真实服务器和真实客户端分别验收。早期正式 integration 检查仅通过独立协议 Peer 驱动服务器，101436 条断言通过，并不能证明原生客户端处理新增通知。随后加入实际 UDP 客户端、真实掉线接管、独立保存回放及分片/非法控制通知。客户端保存的每一帧输入和状态哈希都需要与线上的权威输入、独立 GameEnv 重放结果一致，并在 Release 与 ASan/UBSan 两种构建中交叉重放。

[旧客户端失败与修复对照](../optimization/benchmarks/native-tactical-client-controls-20260914-b/report.json)、[原始六个控制边界用例](../optimization/benchmarks/native-tactical-client-control-boundaries-20260914-a/report.json)、[实际客户端回放检查](../../engine/tests/engine_native_tactics_replay_contract.cpp)、[正式集成检查器](../checks/ai_tactics_contract.py)。

保留的试验失败包括：头文件遗漏直接依赖、单球员夹具保留非法控制索引、探针在首个权威帧之前把 -1 打包成无符号心跳，以及私有诊断副本未调整导入根路径。旧 UDP 无接管、旧守门员/镜像决策、旧原生客户端通知解析问题均保留失败结果与修复后的对照。

正式集成第二轮还出现测试计时问题：ASan 客户端的模型加载超过 15 秒，测试在 Ready 之前报“解析停滞”。独立诊断记录了会话描述和槽位消息均被 ACK，ready=false、控制分片尚未发送；GDB 停在 tree_readblock → ASELoader → Match::Match → GameEnv::start_game → connect。这次失败不能归因于通知解析器。校正测试后单列 40 秒启动预算，保留 Ready 后 15 秒响应预算；三个用例的外层进程预算从 90 秒改为 180 秒，以容纳各自有界的启动和响应阶段。这里明确改变了测试准备计时方式，没有据此提高产品延迟或启动性能评分。

私有修正测试六个用例全部通过，共 318 条断言。ASan 三次启动为 10.921、18.599、11.662 秒，Ready 后处理和退出为 0.924、0.706、0.559 秒；Release 对应阶段约为 0.2 秒与 0.2 秒。这些单次、带测试分片等待和进程清理的耗时仅用于区分失败阶段，不能充当 p95 延迟或启动性能验收。

[原始正式计时失败](../optimization/benchmarks/native-tactics-adoption-20260914-b/ai-integration/sanitized-control-boundaries/report.json)、[诊断抓包与阶段状态](../optimization/benchmarks/native-tactical-control-diagnosis-20260914-b/sanitized-invalid_slot/timeout.json)、[实际调试栈](../optimization/benchmarks/native-tactical-control-diagnosis-20260914-b/sanitized-invalid_slot/gdb.log)、[分阶段计时对照](../optimization/benchmarks/native-tactical-control-phases-20260914-a/report.json)。

为使完整门禁对应最终检查器，已在当前原生合同执行完成后设置受控检查点，保留主动中止记录。首次正式接入的主动停止发生在服务器集成检查完成之后；第二次发生在发现准备阶段计时问题之后。主动检查点、夹具失败和产品缺陷分别记录，不互相替代。

后续仍需：最终完整输入与架构回归、当前源码和产物证据复核、UDP 旧第 200/201 帧缺口的根因、完整弱网及重连、50ms p95 手感、硬件渲染与 Sanitizer、训练栈和对局质量。UDP 接管已接入；UDP 同局重连/全量快照恢复尚未实现，Handback 解析用例不证明重连流程完成。软件或私有 GPU 功能通过也不代表产品打包与硬件验收完成。状态继续由完整里程碑依赖链和当前证据计算。

2026-09-14 最终检查器的 AI 集成已通过：32 项检查、160465 条断言、零跳过。Release 实际服务器四场共 802 帧，ASan 四场共 803 帧；合计 1605 个服务器帧分别在两种构建中重放，逐帧 AI 输入与广播哈希一致。四份实际 UDP 客户端回放共 1042 帧，也分别在两种构建中核对全部输入和状态哈希。实际客户端分别完成 260、260、262、260 帧，全部正常退出；六个分片/非法通知用例通过。ASan 非法槽位用例此次启动耗时 17.499 秒，Ready 后 0.451 秒结束，再次验证准备阶段计时与解析结果应分别记录。

[最终 AI 集成结果](../optimization/benchmarks/native-tactics-adoption-20260914-c/ai-integration/report.json)、[结果摘要](../optimization/benchmarks/native-tactics-current-review-20260914-a/ai-integration-summary.json)、[20 文件完整变更](../optimization/benchmarks/native-tactics-current-review-20260914-a/canonical.diff)、[历史版本与命令复核](../optimization/benchmarks/native-tactics-current-review-20260914-a/historical-review.json)。完整输入、架构和历史比赛回放仍待终态，以上通过不替代这些验收。


2026-09-14 完整输入门禁已通过：42 项检查、3071529 条断言、零跳过。真实独立游戏、TCP、UDP 窗口均完成操作脚本。TCP 的严格持续按键区间为 70/70 个非零权威帧，UDP 为 68/68；当前保存的 511+509=1020 个确认帧在 Release 和 ASan 中分别重放一致。窗口采集子报告中的 full_engine_replay_verified=false 表示该采集阶段本身没有执行引擎回放；后续父检查器已独立运行两份 clock-replay 合同并验证全部确认帧。

| 本轮实际窗口 | 单次本地响应完成 | 软件渲染 p95 |
| --- | ---: | ---: |
| 独立游戏 | 33.703 ms | 201.195 ms |
| TCP | 156.532 ms | 135.924 ms |
| UDP | 85.562 ms | 165.366 ms |

单次独立游戏响应低于 50ms，不能替代 50ms p95 的产品验收。TCP/UDP 响应和渲染仍有明显耗时；原先第 200/201 帧缺口的根因也没有因此得到证明。完整架构与四批历史比赛回放尚待终态。

[当前完整输入报告](../optimization/benchmarks/native-tactics-adoption-20260914-c/input-gate/report.json)、[采集与独立回放结果摘要](../optimization/benchmarks/native-tactics-current-review-20260914-a/input-summary.json)。

下一项网络任务已完成生产调用链复核：当前 TCP 和 UDP 产品入口都尚未接入完整同局重连，已有 TCP 恢复组件走旧协议测试路径。旧会话令牌还存在精确字段碰撞，UDP 快照需要有界分片，见[原生恢复实施依据](optimization-native-reconnect-review-2026-09-14.md)。这些待实现项不会因本轮 AI/输入检查通过而被标为完成。


2026-09-14 完整架构门禁已通过：22 项检查、1629909 条断言、零跳过；158 个编译单元带 ASan/UBSan，泄漏检测开启，无抑制项。两个种子的普通、反序和渲染快照恢复均通过。重复/并发实例的预热 RSS 为 343834624 字节，结束时为 343805952 字节；双 EGL 上下文用例报告的渲染器为 llvmpipe (LLVM 22.1.8, 256 bits)，因此不能计作硬件渲染验收。SDL 事件、上下文失败和损坏/缺失字体的清理用例均通过。最终正式接入驱动以退出码 0 完成，耗时 2523.26 秒，四个阶段全部通过。

[完整架构原始记录](../optimization/benchmarks/native-tactics-adoption-20260914-c/execution/full-architecture.log)、[架构结果摘要](../optimization/benchmarks/native-tactics-current-review-20260914-a/architecture-summary.json)、[正式门禁终态](../optimization/benchmarks/native-tactics-adoption-20260914-c/exit.json)。历史四批比赛回放仍在完成 ASan 的剩余用例。


2026-09-14 本轮运行终态：四批历史比赛共 4124 个权威帧，已在当前 Release 与 ASan 中分别重放一致；八个回放合同合计 3620434 条断言、零跳过。它们包含原严格窗口失败的输入序列；可重放不等于原 UDP 第 200/201 帧缺口已经修复。加上本轮完整输入保存的 1020 帧，共 5144 个新旧窗口确认帧分别通过两种构建的引擎回放；AI 集成的 1605 个服务器帧与 1042 个实际客户端帧另行验证，避免混淆不同场景的统计范围。

| 最终门禁 | 检查/用例 | 断言 | 结论 |
| --- | ---: | ---: | --- |
| AI 集成 | 32 | 160465 | 通过，含实际服务器/客户端与交叉回放 |
| AI 决策 | 6 | 22950 | 通过 |
| 完整输入 | 42 | 3071529 | 通过，含真实窗口及 1020 帧双构建回放 |
| 完整架构 | 22 | 1629909 | 通过，完整 ASan/UBSan 与泄漏检查 |
| 历史回放 | 8 | 3620434 | 通过，每构建 4124 帧 |

[历史回放终态](../optimization/benchmarks/native-tactics-historical-replay-20260914-a/report.json)、[历史回放摘要](../optimization/benchmarks/native-tactics-current-review-20260914-a/historical-replay-summary.json)。

本轮所有测试驱动已退出。最终源码与产物仍需以证据清单的独立哈希校验为准；本报告不会把准备阶段预算修正、主动检查点或旧版本失败隐藏成产品通过。后续继续 task-23.1.1.2 的实际原生重连实现，保留 50ms p95 手感、硬件渲染与运行时打包、训练栈和完整对局质量的待验收状态。
