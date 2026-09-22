# plan-21.1.2 — 容量与预算

2026-09-13 正式 C 已结束，原生驱动退出 0，正常质量入口的 11 项检查全部通过，耗时 3823.132 秒。当前源码计算得到 task-21.1.2.2、plan-21.1.2 以及 ms-21.1 均为 verified；未手动提升状态。整个产品优化阶段尚未完成，后续继续输入、网络、渲染和产品验收。

正式性能和容量终态见[长局性能报告](../reports/optimization-long-match-acceptance-2026-09-13.md)。以下保留任务定义与实施过程；先前“未通过／运行中”描述属于对应历史阶段，不替代当前质量入口的计算结果。

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-21.1.2.1、task-21.1.2.2

验收检查：memory_budget、performance_regression

执行：`python3 .project/quality.py run plan-21.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-13：保留前一阶段记录，容量入口已接通。
2026-09-13 实施进度：原生流式原子保存、最大回放与采样缓冲对照已有证据；完整容量和性能门禁仍待接通，本计划未完成，见[原生性能与回放报告](../reports/optimization-native-performance-replay-progress-2026-09-10.md)。
-->

<!-- 2026-09-13：保留正式 a 之前的进度描述。
2026-09-13 当前进度：原生目录配额和恢复已实现，综合容量检查正在执行正式依赖链，详见[目录与容量进度](../reports/optimization-native-directory-capacity-progress-2026-09-13.md)。性能验收入口与长期稳定采样仍待完成，本计划未通过。
-->

<!-- 2026-09-13 正式 c 已终止；历史进度。
2026-09-13 当前进度：目录容量与恢复已实现，回放专项 224 次执行通过；正式 a 的终止边界测试失败已保留并修正，完整容量正式 b 正在运行。性能验收入口与长期稳定采样仍待完成，本计划未通过，详见[目录与容量进度](../reports/optimization-native-directory-capacity-progress-2026-09-13.md)。
-->

<!-- 2026-09-13 正式 c 已终止；历史进度。
2026-09-13 最新：正式 b 已因前置 CPU 收益证据不足终止，容量 c 正在独立执行；计划尚未通过，详见[当前性能证据](../reports/optimization-performance-evidence-review-2026-09-13.md)。
-->

<!-- 2026-09-13 正式 c 已终止；历史进度。
2026-09-13 最新终态：容量 c 独立检查通过 1390 项执行、零跳过，原始结果与指纹核验已归档；正式 b 的 CPU 收益条件仍失败，不提升任务状态。见[当前性能与容量证据](../reports/optimization-performance-evidence-review-2026-09-13.md)。
-->

2026-09-13 正式终态：容量任务 task-21.1.2.1 已通过正式 c；长期稳定性任务 task-21.1.2.2 尚待独立长局入口与实际验收，本计划仍未完成。见[完整当前证据](../reports/optimization-native-directory-capacity-progress-2026-09-13.md)和[性能结果](../reports/optimization-performance-evidence-review-2026-09-13.md)。
