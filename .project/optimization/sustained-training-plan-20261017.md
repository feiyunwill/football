# 原生足球 AI 训练交付目标：2026-10-17

目标周期为接下来的 6–8 周：交付可重复训练、在变化场景中取得可验证进步、可独立安装运行的原生足球 AI 训练版本。周期用于工作排序，不将未完成验收视为按日期自动完成。GPU 验收继续暂停。

## 阶段与退出条件

1. **持续训练基线（第 1–2 周）**：真实 on-policy PPO 持续至少 30 分钟，绑定当前源码、二进制、工具和环境。记录阶段成本、分钟吞吐、RSS/FD、检查点与 worker 回收。第一条配置为 11 人/cadence 2/四 worker；单条配置不证明 worker 扩展倍率。后续补单 worker、重复及交错顺序，控制启动/预热、样本数、策略版本和 episode 随机种子。
2. **整体训练效率（第 3–4 周）**：依据持续运行证据选择瓶颈。四 worker/单 worker 的主要配置吞吐中位数目标为 2 倍，报告有效置信区间；完整目标覆盖 1/11 人、cadence 2/10。其他配置成本回退不得超过 3%。所有性能判定需事先规定协议，保留未通过结果；不以邻近时间窗口冒充独立重复。
3. **变化场景学习（第 5–6 周）**：从变化开局位置到加入门将，先冻结任务和评估规则，再训练至少 5 个独立种子，使用独立评估场景。成功率需显著超过未训练及随机策略。既有固定空门 97.6% 结果仅为历史起点，不代表对抗或 11v11 能力。
4. **可复现交付（第 7–8 周）**：重建当前源码的安装包，独立环境验证安装、训练、完整续训和冻结评估，交付复现命令、模型、原始指标与说明。远端写入、push 或发布另按明确授权执行。

## 当前执行：首条 30 分钟基线

运行器：`../native-training/profile_sustained_ppo.py`。

- 场景 `11_vs_11_easy_stochastic`，11 人、cadence 2、四个 persistent spawn workers。
- hidden 16、4 epochs、minibatch 64；每次收集四个完整 episode，每个最多 64 步，最多 256 个真实转换后更新。
- 采用已有生产 C++ PPO 数学；诊断桥接独立编译到仓库外。每次采样期间策略保持冻结，episode-keyed RNG 与排序更新规则沿用现有诊断协议。
- reset、step RPC、策略推理、回调、状态摘要、原生 PPO 更新、附加诊断分别计时。step RPC 包含引擎、IPC、调度，不能归为纯 IPC；回调包含旧/后继状态估值等真实采样工作。
- 每约 10 秒记录资源，每约 60 秒保存并在第二实例中恢复完整学习器状态。JSON 仅适用于完整 episode/update 边界，属于诊断格式，不替代 FPPO。
- 输出持续流式落盘；运行完成后校验源码/工具/环境/二进制未变、模型指标有限、FD 收尾和 worker 回收。RSS 为观测数据，不能替代既有产品内存门槛。

原始证据位置：`../native-training/evidence/sustained-ppo-20261017-a/`。运行中 `progress.json` 仅为进度；只有最终 `report.json` 的 `passed: true` 与独立分析通过后，才能将持续基线标记完成。

本次持续时间不等同于长 episode：episode 仍受 64 步 rollout 预算约束。该配置用于成本基线，不评判足球学习能力、跨 worker 扩展或整体训练性能收益。

## ??????

[?? 30 ???????](sustained-training-report-20261017.md)?1,145,600 ??????4,475 ????????????????????????????????? worker ???????????????????????

## ????????

[? worker ????? CPU ???????](matched-workers-report-20261017.md)?4,475 ???????????????????? 1.9415??????????? 2 ??????????????? native step/reset ?????

2026-10-17 measured progress: [PPO pipeline acceptance](ppo-pipeline-report-20261017.md) verifies the primary fixed-workload four/one-worker median target (2.2102x,95% CI2.1633-2.2586), positive primary pipeline gain (1.0902x,lower CI1.00045), and the four-configuration median cost gates. The current 1800-second run passed resource/checkpoint/cleanup checks but overlapped another project compilation, so isolated sustained throughput remains open. The five-seed held-out learning objective and refreshed install/relocation/train/resume/eval delivery are not complete; this does not close the long-term plan.
