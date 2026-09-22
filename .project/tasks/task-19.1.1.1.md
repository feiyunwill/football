# task-19.1.1.1 — 验收证据与依赖状态机

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 拒绝空测试、跳过、非零退出、超时、失效证据；任务/计划/里程碑依赖闭环

依赖：无

执行顺序：无

验收检查：quality_selftest

执行：`python3 .project/quality.py run task-19.1.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-10: 正式框架/架构依赖链与 d 包证据已刷新，保留上一轮记录。
2026-09-10 当前正式验收：在实际 Linux 执行质量状态机 42 项自测，零跳过、零失败；[归档证据](../optimization/benchmarks/native-gymnasium-quality-20260910-a/quality_selftest.json)。本任务及 task-19.1.1.2 的证据已刷新；整体里程碑仍取决于后续任务。
-->

2026-09-10 当前正式验收：质量状态机 42 项通过；当前七门禁及源/日志/二进制归档见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。ms-19.1 与 ms-20.1 已按正式依赖链刷新为 verified，下一项为 task-21.1.1.1。
