# task-23.1.2.1 — 大厅到比赛生命周期

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 协议显式字节序；建房/准备/开局/比赛地址/结束回收与重进闭环

依赖：task-23.1.1.2

执行顺序：无

验收检查：lobby_lifecycle

执行：`python3 .project/quality.py run task-23.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
