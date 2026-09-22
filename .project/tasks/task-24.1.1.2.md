# task-24.1.1.2 — HDR 与后处理

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 曝光、Bloom、抗锯齿等启用效果有真实纹理输入、正确顺序与可关闭对照

依赖：task-24.1.1.1

执行顺序：无

验收检查：postprocessing

执行：`python3 .project/quality.py run task-24.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
