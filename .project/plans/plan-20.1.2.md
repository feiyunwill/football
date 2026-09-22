# plan-20.1.2 — 模块契约

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-20.1.2.1、task-20.1.2.2

验收检查：simulation_contract、architecture_regression

执行：`python3 .project/quality.py run plan-20.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
