# plan-25.1.2 — 评估与训练可靠性

2026-09-24：检查点文件 I/O 候选的 Release/Debug 回归通过，完整训练序列化与生命周期仍待验证，训练验收状态不提升。见[实现与边界](../reports/optimization-training-checkpoint-io-2026-09-24.md)。

以下保留此前阶段记录：

2026-09-24：训练观测 128 列声明/147 值写入已修复，新增共享布局、编译期维度检查和永久运行合约。Linux Release 与完整 Debug ASan/UBSan 各通过 4 场景、1850 条断言；8 项验收器测试通过。当前源码 1117 项，正式原生/完整框架验收已启动，完整训练与产品级状态仍未通过。详见[实现、证据与边界](../reports/optimization-rl-observation-layout-2026-09-24.md)。

以下保留此前阶段记录：

2026-09-15 实现复核：发现观测声明 128 维但写入 147 值、检查点覆盖写入且未检查写入结果、恢复失败退回随机初始化、保存周期零值和生命周期边界问题。实际 RLtools 依赖目录为空，训练入口尚未构建运行；源码复核不作为训练验收通过。修复顺序及限定证据见[训练可靠性复核](../optimization/benchmarks/training-reliability-review-20260915-a/review.md)。

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-25.1.2.1、task-25.1.2.2

验收检查：training_reliability、ai_regression

执行：`python3 .project/quality.py run plan-25.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
