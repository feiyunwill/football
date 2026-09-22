# task-19.1.1.2 — 命令行与计划文档

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 自动生成层级文档；CLI 完成操作只能验证现有证据；下一任务可恢复

依赖：task-19.1.1.1

执行顺序：无

验收检查：quality_selftest

执行：`python3 .project/quality.py run task-19.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-10: 正式框架/架构依赖链与 d 包证据已刷新，保留上一轮记录。
2026-09-10 当前正式验收：经依赖链执行 quality_selftest，42 项通过；[归档证据](../optimization/benchmarks/native-gymnasium-quality-20260910-a/quality_selftest.json)。当前下一任务为 task-19.1.2.1，未用局部安装报告代替后续门禁。
-->

2026-09-10 当前正式验收：质量状态机 42 项及后续框架/架构门禁全部通过，当前下一任务为 task-21.1.1.1；详见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。
