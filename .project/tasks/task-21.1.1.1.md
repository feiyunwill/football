# task-21.1.1.1 — 真实比赛基准

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 11v11 固定输入及种子，记录硬件、编译参数、p50/p95/p99、RSS；启动与稳态分开

依赖：ms-20.1

执行顺序：无

验收检查：match_benchmark

执行：`python3 .project/quality.py run task-21.1.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-13：保留先前基准待办。
2026-09-10 当前交接：ms-19.1/ms-20.1 的正式证据已刷新，本任务是质量程序返回的下一项 stale 任务，见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。应使用当前原生源码和 d 安装包对应实现刷新基准，记录实测硬件、配置及统计分布；本轮未把功能测试耗时或 ASan RSS 当成性能提升。
-->

2026-09-13 当前验收：两种子各 5 个独立进程的真实 11v11 基准通过，合并 p99 为 4.69／5.12 ms，本任务 verified，见[原生性能与回放报告](../reports/optimization-native-performance-replay-progress-2026-09-10.md)。
