# task-26.1.2.2 — 最终质量审查

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 七个领域当前源码验收全部有效；已知严重缺陷为零；产物与运行证据可复现

依赖：task-26.1.2.1

执行顺序：无

验收检查：product_release

执行：`python3 .project/quality.py run task-26.1.2.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
