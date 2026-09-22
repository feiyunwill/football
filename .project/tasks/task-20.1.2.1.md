# task-20.1.2.1 — 逻辑与表现边界

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 渲染不推进逻辑；快照恢复是事务；逻辑结果不依赖是否渲染

依赖：task-20.1.1.2

执行顺序：无

验收检查：simulation_contract

执行：`python3 .project/quality.py run task-20.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-10 当前正式验收：正常/反向/实际渲染的六组仿真与快照检查共 3,568 条通过；无效 reset 保留物理状态和展示姿态，详见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。
