2026-09-25 最新终态：永久验证 B 已退出 1，状态门禁 24 项/81100 断言通过，控制门禁保留 35 项通过结果（Release 19、完整 Debug 16）；Debug TCP 在暂停边界发生重连，未满足原暂停安装观察条件。2564 份控制输入和 68 份日志核验通过。失败窗口的恢复回放已另行在完整 Debug 验证：219 帧、1 个检查点、最终边界 241、439 项断言通过，不能据此将窗口门禁改为通过。

2026-09-25 管线与图形观测：native-pipeline-profile-validation-20260925-a 和 native-graphics-profile-validation-20260925-a 均已终态退出 1，Release 窗口/独立回放通过，Debug 分别出现输入保留窗口耗尽和暂停安装观察失败。两阶段分别核验 3059 输入/15 日志、3060 输入/16 日志。18 个管线钩子及 8 个预期图形钩子均取得数据；PBR 路径未观察到。本轮为强制软件 OpenGL 场景，全屏阶段 Release 每帧约 64ms，是后续优化重点。已准备仅改变 modifier 缓冲通道数的 RG16F 候选及真实画面差分工具，尚未编译、执行或采纳。

2026-09-25 控制门禁增量：永久验证 B 的 Release 共 19 项结果通过，涵盖 6 个普通客户端、3 个恢复客户端及 11 次独立回放。TCP/UDP 窗口分别确认 4732/4839 帧、完成 1002/1003 次呈现，退出 61.464/86.720ms；两个窗口独立回放合计 9571 帧通过。当前完整 Debug 控制验证仍在运行。检查点核验 2545 份控制输入与 44 份完成命令日志，无差异。旧日志只读统计显示呈现间隔中位约 97ms，窗口门槛通过不能代表产品流畅度达标。

2026-09-25 证据保留修正：状态门禁的 33 份固定输入中，31 份仍匹配；控制门禁重新配置共享构建目录，导致两份 compile_commands.json 被追加私有 X11 include 路径。已在独立证据目录恢复两份原始编译记录，SHA-256 与原状态门禁固定值完全一致；未覆盖执行目录。28 份状态命令日志全部匹配。后续驱动已准备 state-build/control-build 隔离及跨门禁累计输入核验，尚未执行，不能将当前阶段宣称为固定输入全程不变。详见 optimization-native-validation-isolation-2026-09-25.md。

# 永久状态与控制门禁验证

归属 ms-23.1 → plan-23.1.1 → task-23.1.1.2。候选未采纳到正式源码，产品验收未通过。

2026-09-25 永久验证进展：native-state-permanent-validation-20260925-b 的 Release 与完整 Debug 状态门禁已全部通过，共 24 项结果、81100 项断言；双向各 1500 份跨配置快照恢复通过。当前进入控制门禁，尚未完成实际窗口与独立回放验收。正式源码未采纳候选，产品级验收仍未通过。

阶段 native-state-permanent-validation-20260925-b 使用 46 份冻结候选文件和 1164 份状态源文件，先串行执行 Release 与完整 Debug 状态门禁，再执行控制门禁。正式源码 1138 份固定输入保持不变。

每种配置的 10 项组件/恢复结果各通过 37551 项断言：writer 8406、节点/网缓存 13+9、mirror 19、bulk writer 24832、animation 16、capture 306、hash 2054、seed 42/43 恢复 946/950。双向跨配置各生产 1500 份快照，各消费者核验 2999 次哈希和 1499 次连续恢复。报告合计 81100 项断言、3000 份快照、2998 次后续运行。原始报告：native-state-permanent-validation-20260925-b/workspace/.project/optimization/benchmarks/state-evidence/report.json。

完整 Debug 编译保留 -g、ASan/UBSan、禁止 sanitizer 恢复及 frame pointer，已检查 182 条编译记录，不使用 O1/O2/O3/Ofast 或 DNDEBUG。Release 早期检查点的 12 份命令日志 SHA-256 已核验，记录在 native-state-permanent-progress-20260925-a/release-state-checkpoint.json。

当前控制门禁仍在运行，预期 38 项结果；状态组件通过不代表实际窗口、恢复矩阵、退出时间或独立回放通过。原整机仅 65 次呈现、缺失 23 份 /tmp 产物、基准源码仅恢复 844/881，以及原始 RSS/输入窗口问题仍是未完成项。
