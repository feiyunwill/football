# 原生输入发布校准与 AI 接管恢复（2026-09-13）

当前结论：输入发布校准和 AI 死球恢复已接入 11 个正式文件；32 项组件/采样检查共 2,080,418 条断言通过。完整固定输入门禁仍因 UDP 第 200、201 帧持续输入缺口失败，不能宣布产品通过。里程碑 19–26 的状态仍由质量程序计算为 stale。

## 实现与原因

- 输入发布器在收到推进后的权威帧、且已经存在提前发布的不可变输入时，重置下一次推测发布时限，让服务器先消费已有输入。保留既有输入历史、服务端缺失输入规则、50Hz 节拍、16 帧接纳窗口和时钟溢出检查。
- BotGameSnapshot 显式记录暂时不可用的控制槽。真实 GameEnv 在死球转换期间可将 controlled_player 设为 -1；观察器保留这个合法状态，AI 对该槽生成中性输入，球员重新选中后恢复决策。损坏的索引、缺少的控制器和超出槽范围的掩码仍被拒绝。
- 新固定测试嵌入真实失败现场的 512 帧回放及 57 帧后续输入，校验原始逐帧哈希和球员轨迹，并要求完整经历无选中球员与恢复阶段。它与慢权威发布校准检查均接入固定输入验收。

正式实现：[发布时钟](../../engine/src/frame_sync/native_publication_clock.hpp)、[AI 状态与输入](../../engine/src/frame_sync/bot_takeover.hpp)、[真实观察器](../../engine/src/frame_sync/engine_tcp_bridge.hpp)、[TCP 权威](../../engine/src/frame_sync/engine_tcp_server.hpp)。新回归：[真实 AI 转换](../../engine/tests/engine_native_bot_selection_contract.cpp)、[发布校准](../../engine/tests/engine_native_publication_clock_contract.cpp)、[固定检查入口](../checks/input_contract.py)。

## 可复现证据

1. [原始链路观测](../optimization/benchmarks/native-input-latency-review-20260913-a/analysis.json)：UDP 再次按键在 1.834ms 被 SDL 采样、16.902ms 发布，约 0.13ms 后完成服务器收包，却到 191.885ms 才完成对应权威帧；发布提前量 p95/max 为 8 帧。原始固定验收的 342.668ms 失败仍保留，不用后续成功覆盖。
2. [持续输入缺口](../optimization/benchmarks/native-input-latency-review-20260913-a/udp-held-gap.json)：原始观察轮第 203 帧没有发布或发送，202→204 间隔约 40.96ms。该轮明确失败。
3. 相同 12 秒、服务器每帧 21ms 的确定性输入中，[旧代码](../optimization/benchmarks/native-input-latency-review-20260913-a/drift-execution/current-run.log)达到提前 15 帧并失败；[候选代码](../optimization/benchmarks/native-input-latency-review-20260913-a/drift-execution/candidate-run.log)保持最多 2 帧，发布 572 帧。原型 Release、ASan/UBSan、TSan 各 31,148 条断言通过。
4. [原型实际三窗口](../optimization/benchmarks/native-publication-resync-prototype-20260913-a/x11/windows/report.json)全部通过；[独立分析](../optimization/benchmarks/native-publication-resync-review-20260913-a/analysis.json)显示 TCP/UDP 提前量最大 2 帧，UDP 再次按键权威响应 59.123ms。这是单次软件 X11 观察，不是 50ms 延迟分位数或硬件呈现验收。
5. [100ms 暂缓观测](../optimization/benchmarks/native-publication-resync-review-20260913-a/batch-observation.json)：TCP/UDP 期间分别继续发送 4/5 帧，持续输入 69/70 个权威帧均无中性缺口。但 TCP 玩家退出后触发 AI 观察器异常，因此该整轮仍失败。
6. [AI 真实现场对照](../optimization/benchmarks/native-bot-selection-prototype-20260913-c/report.json)：旧观察器重放到同一转换后稳定报错；修复后 Release/ASan 各 1,230 条断言通过，完整记录 30 帧不可用状态及后续恢复。
7. [组合实际窗口](../optimization/benchmarks/native-publication-bot-combined-20260913-a/x11/windows/report.json)：发布校准客户端与 AI 修复服务器共同运行，TCP/UDP 100ms 暂缓均通过；TCP 玩家退出后继续推进 250 个权威帧并正常停止。

## 固定工程验收

[正式接入记录](../optimization/benchmarks/native-publication-bot-integration-20260913-a/changes.json)保存 11 文件前后哈希及原产品二进制。首次固定构建发现新增测试 main 声明与引擎头文件声明不一致；[后续修正](../optimization/benchmarks/native-publication-bot-integration-20260913-b/predecessor.json)仅修正测试入口与历史注释。

- [TCP 会话回归](../optimization/benchmarks/native-publication-bot-integration-20260913-a/report.json)：Release 与 ASan/UBSan 的服务器、客户端合同共四项通过，各确认 40 帧服务器流程、校验 8 个哈希，并恢复 87,132 字节快照；客户端最终确认 39 帧。该报告保留其独立输入构建失败，不能把报告整体当作成功。
- [固定门禁终态](../optimization/benchmarks/native-publication-bot-integration-20260913-b/exit.json)：运行 517.587 秒后退出 1；[完成的组件检查](../optimization/benchmarks/native-publication-bot-current-review-20260913-a/completed-contracts.json)为 32 项、2,080,418 条断言、零跳过。正式 AI fixture 在 Release/ASan 各 1,262 条断言通过；发布校准在 Release/ASan/TSan 均通过，最大提前量 2、慢权威场景发布 572 帧。
- [固定 UDP 失败现场](../optimization/benchmarks/native-publication-bot-current-review-20260913-a/gate-udp-held-gap.json)：真实权威第 200、201 帧为中性输入，且已写入最终回放。缺口发生时客户端存在长时间渲染工作，但该轮缺少发送/收包记录，尚不能把渲染重叠认定为直接原因。
- [正式二进制独立场景](../optimization/benchmarks/native-publication-bot-current-windows-20260913-a/report.json)：TCP/UDP 100ms 权威收包暂缓全部功能检查通过，均继续发送 5 帧，持续输入区间分别 71/70 个权威帧没有缺口；TCP 退出后继续运行 250 帧且服务器正常结束。实际 loaded-maps 验证当前核心库路径。[网络观察](../optimization/benchmarks/native-publication-bot-current-windows-20260913-a/fault-analysis.json)记录输入收包与权威零不一致。
- 失败固定窗口批次的 [1,030 帧回放](../optimization/benchmarks/native-publication-bot-failed-replay-20260913-a/report.json)与后续独立批次的 1,031 帧回放均在 Release/ASan 完整验证。每个构建合计 **2,061 个真实确认帧、905,105 条回放断言**。回放一致性不消除持续输入缺口。
- Release 核心 SHA256 仍为 27c8c9ff779d0fad7379b9c28a9fada6c044e469e396b95882279049e676303d，ASan 核心仍为 8e0750b33752c5764741c1e41e4cd28cb750343e44dbcc022f8ab996d4834d45。本次新增行为位于发布/服务器头文件与验收，已有核心模拟实现未改变。

本轮测试工具的失败同样保留：首个观察器副本解析错数据目录；最初 AI 重放 fixture 的 std::span 实参和控制器数组长度假设分别导致编译/断言失败。最终 fixture 使用实际 MAX_PLAYERS 控制器形状，并完成旧实现失败、新实现通过的对照。没有放宽真实窗口的持续输入、恢复时间窗或服务器退出要求。

## 后续验收顺序

- 首先给发布泵、两层网络互斥量和发送/收包增加同一时钟的观测，定位正式 UDP 第 200、201 帧缺口；不得通过放宽固定持续输入检查或反复重试宣称解决。
- 持续输入在长停顿、输入方向弱网、重连和观战条件下仍需扩大验证；约 59ms 的单次权威响应尚不满足完整 50ms 产品目标。
- GPU/ASan 初始化、私有 Mesa 修复的产品化、1080p 连续呈现、渲染长帧及 AI 决策质量仍待处理。
- 实现稳定后按 ms-19.1 → ms-26.1 刷新完整依赖链；不手动提升状态。
