# 永久状态与控制门禁验证

归属 ms-23.1 → plan-23.1.1 → task-23.1.1.2。候选未采纳到正式源码，产品验收未通过。

2026-09-25 永久验证进展：native-state-permanent-validation-20260925-b 的 Release 与完整 Debug 状态门禁已全部通过，共 24 项结果、81100 项断言；双向各 1500 份跨配置快照恢复通过。当前进入控制门禁，尚未完成实际窗口与独立回放验收。正式源码未采纳候选，产品级验收仍未通过。

阶段 native-state-permanent-validation-20260925-b 使用 46 份冻结候选文件和 1164 份状态源文件，先串行执行 Release 与完整 Debug 状态门禁，再执行控制门禁。正式源码 1138 份固定输入保持不变。

每种配置的 10 项组件/恢复结果各通过 37551 项断言：writer 8406、节点/网缓存 13+9、mirror 19、bulk writer 24832、animation 16、capture 306、hash 2054、seed 42/43 恢复 946/950。双向跨配置各生产 1500 份快照，各消费者核验 2999 次哈希和 1499 次连续恢复。报告合计 81100 项断言、3000 份快照、2998 次后续运行。原始报告：native-state-permanent-validation-20260925-b/workspace/.project/optimization/benchmarks/state-evidence/report.json。

完整 Debug 编译保留 -g、ASan/UBSan、禁止 sanitizer 恢复及 frame pointer，已检查 182 条编译记录，不使用 O1/O2/O3/Ofast 或 DNDEBUG。Release 早期检查点的 12 份命令日志 SHA-256 已核验，记录在 native-state-permanent-progress-20260925-a/release-state-checkpoint.json。

当前控制门禁仍在运行，预期 38 项结果；状态组件通过不代表实际窗口、恢复矩阵、退出时间或独立回放通过。原整机仅 65 次呈现、缺失 23 份 /tmp 产物、基准源码仅恢复 844/881，以及原始 RSS/输入窗口问题仍是未完成项。
