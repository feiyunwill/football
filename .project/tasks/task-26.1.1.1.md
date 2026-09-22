# task-26.1.1.1 — 全流程自动场景

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 新启动到大厅、比赛、结束、退出完整脚本；恢复故障后可继续使用

依赖：ms-25.1

执行顺序：无

验收检查：product_journey

执行：`python3 .project/quality.py run task-26.1.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
