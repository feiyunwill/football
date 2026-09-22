# plan-26.1.1 — 整局与长时运行

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-26.1.1.1、task-26.1.1.2

验收检查：product_journey、product_soak

执行：`python3 .project/quality.py run plan-26.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
