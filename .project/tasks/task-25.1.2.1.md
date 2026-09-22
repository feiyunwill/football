# task-25.1.2.1 — 训练与检查点

2026-09-15 实现复核：发现观测声明 128 维但写入 147 值、检查点覆盖写入且未检查写入结果、恢复失败退回随机初始化、保存周期零值和生命周期边界问题。实际 RLtools 依赖目录为空，训练入口尚未构建运行；源码复核不作为训练验收通过。修复顺序及限定证据见[训练可靠性复核](../optimization/benchmarks/training-reliability-review-20260915-a/review.md)。

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 检查点写入原子化、损坏/维度不匹配可诊断；环境实例限制明确并受测试约束

依赖：task-25.1.1.2

执行顺序：无

验收检查：training_reliability

执行：`python3 .project/quality.py run task-25.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
