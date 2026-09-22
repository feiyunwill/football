# task-26.1.1.2 — 长时与资源检测

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 多种子至少 100000 逻辑帧；已覆盖路径无 ASan/UBSan 问题，资源增长有界

依赖：task-26.1.1.1

执行顺序：无

验收检查：product_soak

执行：`python3 .project/quality.py run task-26.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
