# 原生重连：实际断线基线与构建覆盖修正（2026-09-14）

归属：ms-23.1 → [plan-23.1.1 传输与恢复](../plans/plan-23.1.1.md) → [task-23.1.1.2 断线与重连](../tasks/task-23.1.1.2.md)。

当前源码的实际 TCP/UDP 客户端在自身连接中断后退出并保存确认前缀，没有自动恢复。此结论已在 Release 和 ASan/UBSan 中复现；服务器由 AI 接管原槽位，另一玩家继续比赛。这里通过的是缺陷复现与回放检查，原生重连验收仍未通过。

| 实际客户端 | 保存确认帧 | 客户端校验哈希数 | 服务器总帧 | AI 接管起始帧 | 恢复尝试 |
|---|---:|---:|---:|---:|---:|
| Release TCP | 100 | 10 | 253 | 102 | 0 |
| Release UDP | 101 | 10 | 270 | 119 | 0 |
| 当前源码 ASan TCP | 82 | 8 | 253 | 102 | 0 |
| ASan UDP | 101 | 10 | 269 | 118 | 0 |

每例在权威第 100 帧后切断实际客户端自己的连接，3 秒后网络路径重新可用；客户端均以失败码 1 退出。每例均观察到 151 帧非零 AI 输入和另一玩家的 151 帧非零输入，未分配的第三槽位保持中立。服务器正常终止，退出码均为 0。

4 份完整权威记录合计 1,045 帧，4 份客户端保存前缀合计 384 帧，均分别在 Release 和 ASan 中逐帧重放。完整记录核对真实 GameEnv 决策、输入和广播哈希；保存前缀逐帧核对实际客户端记录的输入与状态哈希，并核对最终文件元数据。汇总 47,662 条断言，零跳过。见[完整结果](../optimization/benchmarks/native-reconnect-baseline-20260914-b/report.json)。

本测试使用每例一个实际无窗口产品客户端和一个独立协议玩家；独立玩家每 20 帧改变方向。它没有覆盖两个实际键盘玩家同时重连、双向复杂弱网、渲染卡顿或输入延迟指标。

ASan TCP 首次失败发生在断网注入之前。代理记录显示，旧客户端接通 TCP 后等待约 5 秒，没有发出当前 FNAT1 Hello，随后退出。8 个原生产物的依赖时间审计中，只有 ASan TCP 客户端对象文件落后于当前依赖：有 11 条过期依赖记录，其中 main.hpp 重复一次。旧对象和二进制时间为 1789275127，当前 integrated_client.cpp 源码时间为 1789308248。见[依赖审计](../optimization/benchmarks/native-reconnect-build-audit-20260914-a/audit.json)和[旧握手记录](../optimization/benchmarks/native-reconnect-baseline-diagnosis-20260914-a/sanitized/tcp/bootstrap-trace.json)。

从当前 integrated_client.cpp 按现有 ASan 编译和链接参数隔离构建后，客户端发送完整的 18 字节 Hello，收到 37 字节描述符及槽位分配，正常进入比赛后才触发断线基线。见[当前源码握手记录](../optimization/benchmarks/native-reconnect-baseline-20260914-b/sanitized/actual/tcp/bootstrap-trace.json)。主构建目录中的旧 ASan TCP 客户端保留原样，尚未刷新；此次成功使用的是有源码、命令和哈希记录的隔离产物。

此前战术阶段的 64 个产物哈希是文件身份记录，不能单独证明每个目标都由最新源码重建。该阶段的实际 UDP 客户端、Release 窗口与 ASan 引擎回放结果不变；ASan TCP 产品入口的构建与实际运行覆盖缺口由本次单独发现和验证。下一次正式接入必须补齐四个原生客户端/服务器目标的构建覆盖，避免继续复用过期对象。

保留所有失败：baseline-a 中的 ASan 握手失败、diagnosis-a 的同一失败及原始日志均未覆盖。baseline-a 的失败汇总中 baseline_defect_reproduced 字段原先无条件为 true，不能采信，必须以 passed=false 为准；baseline-b 修正了该汇总字段。原先拟复用的双槽位窗口时钟测试要求中途保存文件，不适用于本次三槽位断线前缀；已新增独立前缀回放检查，没有修改或放宽旧检查。

下一项实现为[恢复凭证和所有权组件](optimization-native-recovery-credentials-2026-09-14.md)，之后接入明确版本的恢复协议、分片快照、追帧和客户端恢复循环。旧 UDP 第 200、201 帧缺口、50ms p95、硬件渲染及整个产品质量目标仍未达标；不手动提升里程碑或任务状态。
