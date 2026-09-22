# task-20.1.2.2 — 架构集成回归

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 覆盖启动、踢球、暂停、恢复、结束、销毁与多实例边界

依赖：task-20.1.2.1

执行顺序：无

验收检查：architecture_regression

执行：`python3 .project/quality.py run task-20.1.2.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-10 当前正式验收：134 个实际编译单元带 ASan/UBSan，34,562 条断言通过，涵盖多实例、暂停/恢复/结束、快照、双 EGL、真实 SDL 和失败资源路径，无 sanitizer 错误或抑制规则。ms-20.1=verified；验收范围及尚未覆盖的 HUD 分配异常见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。
