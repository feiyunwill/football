# 框架生命周期修复与验收记录（2026-09-21）

2026-09-22 最新终态：当前完整框架门禁因 Python 最大快照 UDP 恢复失败而结束，后续集成/恢复未启动。文件读取原生回归仍通过，整体验收未通过；网络调度候选尚未采用。见[失败与复现](optimization-python-udp-snapshot-2026-09-22.md)。

以下保留此前阶段记录。

2026-09-22 最新：文件读取优化已接入正式源码（1090 项），完整框架复验正在执行；本报告先前核心与结果保留为历史，当前启动及恢复验收仍待复验。见[最新记录](optimization-native-file-read-2026-09-22.md)。

以下保留此前阶段记录。

2026-09-22 正式接入：ASE 修复及 10 项永久原生回归已采用，Release/完整 ASan+UBSan 各通过 554 条断言；完整框架门禁通过 560 项 C++、781 项 Python、305 个子测试及两种子的独立 1000 帧/快照回放。当前正式源码为 1089 项。性能统计与整个产品验收仍未完成，见[接入及完整证据](../reports/optimization-native-ase-adoption-2026-09-22.md)。

以下为此前阶段的实现与历史记录。

里程碑 ms-19.1 → 计划 plan-19.1.2 → 任务 task-19.1.2.2。三项实现已采用，完整框架门禁 D 已通过；整个优化阶段及产品网络/性能验收尚未完成。

| 问题 | 实现与验证 | 状态 |
|---|---|---|
| 首次输入前关闭窗口误判为启动失败 | UI 已收到退出而 ready 尚未发布时，正常进入比赛线程收尾；展示失败与回放取消语义保留。旧实现确定性失败，新实现及原用例共 15 项通过，验证零帧回放与所有者回收。 | 已采用 |
| 公共 TCP/UDP 结束请求与收集输入竞争 | 共享一个有界 Future，当前帧提交后发布最终帧号和哈希；调用方取消不取消共享请求，关闭及引擎/摘要失败结束等待。旧实现两种传输均复现 frame_in_progress，新实现 81 项通过。 | 已采用 |
| 首个权威帧在队列检查后到达，已确认却仍被归为大厅 | 在逻辑处理后根据已确认帧更新开局标志。真实 TCP/UDP 在检查空队列后、逻辑读取前发送第 0 帧，旧实现两项均失败；候选与原多人/暂停套件共 53 项通过。 | 已采用 |
| 真实 UDP 自然结束超过 15 秒 | 未改变原测试或期限。独立 TCP/UDP、UDP 计时诊断及完整 C 都通过；原 B 超时根因未确认。 | 保留历史失败 |
| 最大快照弱网握手 udp_gap_timeout | 完整 C 失败，四次独立重跑及完整 D 均通过；独立观测记录 11847、11649、10972 个事件，无截断。 | 历史失败根因未确定 |

[采用 A](../optimization/benchmarks/framework-lifecycle-adoption-20260921-a/report.json) 包含两个实现文件、两个永久回归文件；[采用 B](../optimization/benchmarks/framework-lifecycle-adoption-20260921-b/report.json) 增加首帧交接实现及两项永久用例。均逐字节采用已验证候选，旧源码保存在 before。当前清单为 1088 个文件，永久新增 13 项回归。

对应私有旧/新对照：[启动退出](../optimization/benchmarks/graphical-startup-quit-20260921-a/report.json)、[结束帧边界](../optimization/benchmarks/match-finish-boundary-20260921-b/report.json)、[首个权威帧](../optimization/benchmarks/match-first-authority-20260921-a/report.json)。结束边界 A 的测试驱动输入路径拼写错误发生在测试启动前，B 只修正该路径，失败 A 保留。

[完整门禁 C](../optimization/benchmarks/framework-display-20260921-c/report.json) 为失败终态：560 项 C++ 通过，Python 778 项及 304 个子测试通过；一个 UDP 暂停子测试和最大快照弱网测试失败。启动退出、公共 UDP 结束和真实 GameEnv UDP 自然结束均通过。后续两个种子的独立 1000 帧回放步骤未执行。完整日志 SHA 为 27e37a484a08853f533128bdec3aaf75754a776924957bf0477a01d2fa7a4dd0；XML/JSON 已复制入本轮证据目录，未依赖会被后续门禁覆盖的固定文件。

[完整门禁 D](../optimization/benchmarks/framework-display-20260921-d/report.json) 已通过：560 项 C++、781 项 Python、305 个子测试，零失败和跳过；167 个 Debug 编译单元，两个种子各两个独立进程的 1000 帧运行与快照回放全部通过，结构化验收计数 1344。原套件、阈值和断言均保留。额外收集目录只有 conftest；最大快照原 UDP fail 路径观察器没有捕获失败事件。正式日志 SHA 为 072c4ac6768c21bf1ef8ddf35d7607d13d06f962cdf14552ed0c36fde0baee57。[D 的固定 XML/JSON 与验证摘要](../optimization/benchmarks/framework-lifecycle-evidence-20260921-c/validated-summary.json) 已单独归档，历史 C 失败也保留；本次通过不等于历史缺口超时根因已修复。

[真实 GameEnv 计时诊断](../optimization/benchmarks/native-completion-timing-20260921-a/report.json)：UDP 第 116 帧终局，首轮 advance 至终局约 3.83 秒；119 次 advance 累计 2.652 秒、p95 50.41 ms，116 次 authority.run_frame 累计 0.967 秒。该单次诊断不构成产品性能通过。[弱网诊断](../optimization/benchmarks/python-udp-gap-diagnostic-20260921-a/report.json) 三轮最大观测收包至交付等待约 0.413、0.210、0.471 秒，均未触发 2 秒缺口期限；完整 C 的失败仍有效。

[原生 TCP ASan 对照](../optimization/benchmarks/native-transport-policy-diagnostic-20260921-a/report.json) 使用原头文件与共用传输候选、同一契约及当前原生核心，保持 Debug -g、ASan/UBSan、泄漏检查和全部期限。原实现手动恢复在确认 32 帧时因服务端 idle_timeout 断开；原实现自动模式和候选手动模式均有 ready_timeout；候选自动模式通过，确认到 47 帧、恢复一次、两次恢复后哈希验证、2280 条断言。没有观察到 sanitizer 故障，但这些结果不足以验收传输重构，更不能代表实际原生集成客户端已验证。

[本轮证据](../optimization/benchmarks/framework-lifecycle-evidence-20260921-b/proof-files.json) 保存全部终态、采用差异与原文档归档。五项原生 UDP 组件、产品网络接入、启动/退出性能、完整弱网、目标硬件渲染、训练、打包和长稳仍按原里程碑继续。

本次完整框架通过的[终态与证据](../optimization/benchmarks/framework-lifecycle-evidence-20260921-c/proof-files.json)已确认对应 PID/start-tick 不再存活，当前无待观察运行任务。后续继续原生启动/退出性能、共用 TCP/UDP 产品接入和完整弱网验证。
