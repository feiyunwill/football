# task-23.1.2.2 — 真实网络故障验收

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 两客户端非零变化输入、逐帧哈希；延迟/抖动/丢包/乱序/断线矩阵自动注入并验证

依赖：task-23.1.2.1

执行顺序：无

验收检查：network_regression

执行：`python3 .project/quality.py run task-23.1.2.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
