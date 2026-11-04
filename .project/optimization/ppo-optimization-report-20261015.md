# PPO CPU 性能优化：2026-10-15 续轮

已保留两项生产代码优化：策略网络前向计算按四个独立神经元分块；PPO 更新在样本、minibatch 之间复用梯度和导数缓冲区。每个神经元的输入求和顺序、每个参数的样本累加顺序、除法、有限值检查、梯度裁剪与 Adam 事务提交保持原计算方式。没有启用 fast-math，也没有新增运行依赖或改变检查点格式。

## 性能结果与适用范围

隔离编译优化前/后生产 C++，同一进程、同一逻辑 CPU，预热后交替测量 24 对，每次执行 8 个 PPO 更新。每个更新 128 个样本、4 epochs、minibatch 64。只计 UpdatePpo 的进程 CPU 时间，状态输出和诊断不计入。各组要求中位 CPU 成本下降至少 10%，且配对 bootstrap 95% speedup 下界大于 1；四组全部通过。

| 控制人数 | 隐藏单元 | 更新 CPU 成本下降中位数 | speedup 95% 区间 |
|---|---|---|---|
| 1 | 16 | 16.31% | 1.151–1.316 |
| 1 | 64 | 13.30% | 1.129–1.182 |
| 11 | 16 | 15.25% | 1.155–1.228 |
| 11 | 64 | 16.89% | 1.173–1.246 |

[原始配对数据、源码与工具快照](../native-training/evidence/ppo-combined-20261015-a/report.json)。这是特定 Linux/WSL 主机上的 PPO 更新收益，不代表仿真、整条训练流水线、渲染或 GPU 获得相同比例提升。不同生产编译参数和硬件仍需复测。

## 正确性与集成

- 基线/候选的模型参数、Adam 一二阶矩、步数、shuffle RNG、更新指标和抽样公开梯度逐字节一致。
- 额外覆盖 1/6/65/256 个样本、1/3/7/64 隐藏单元，验证单样本、末尾 minibatch 与隐藏层尾部，结果一致：[边界证据](../native-training/evidence/ppo-combined-edges-20261015-a/report.json)。
- 新增标量 oracle，对 1/11 人、115/460 特征、1/3/4/7/16/64 隐藏单元、两种动作布局共 48 种组合逐位比较前向结果；验证分块溢出失败保留动作 RNG。
- 当前版本重建后，72 项 Python 集成测试和 8 项 C++ 契约全部通过：[当前完整质量收据](../native-training/evidence/ppo-combined-quality-20261015-a/report.json)。
- 真实 on-policy PPO 重跑 1/2/4 workers × 1/11 人 × cadence 2/10，三次轮换重复。36 次轨迹及更新指标与优化前一致；本轮不同 worker 数检查点一致，新进程从 1 worker 前缀切换到 4 workers 续训，与完整运行逐字节一致：[worker 证据](../native-training/evidence/ppo-combined-workers-20261015-a/report.json)。
- 优化前后的已保存学习器 payload 完全一致。检查点外层 source/core 身份随构建变化，完整 envelope SHA 理应不同，恢复时仍严格校验身份。首版审计误比较跨构建 envelope，失败记录保留；修正后的审计验证 payload 和各构建身份：[当前审计](../native-training/evidence/ppo-combined-audit-20261015-b/report.json)。

本轮短 episode 流水线四 worker/单 worker 倍率依次为 2.946、2.940、1.231、3.106（1人/c2、1人/c10、11人/c2、11人/c10）。全配置 2 倍目标仍未通过；该数据不能与不同时段的旧短跑直接解释成整体提升或退化。需要独立的长时、交错基线/候选流水线实验。

## 未保留的实验

直接累加梯度、单独复用缓冲区、仅隐藏层分块均未通过各自性能门槛；保留诊断证据，不作为独立收益声明。首轮计时还包含状态输出，末尾与质量检查重叠，仅作诊断；后续计时已排除输出并串行运行。

- [直接累加](../native-training/evidence/ppo-fusion-20261015-a/report.json)
- [单独缓冲区复用](../native-training/evidence/ppo-reuse-20261015-a/report.json)
- [仅隐藏层分块](../native-training/evidence/policy-blocking-20261015-a/report.json)

## 复现与下一步

在 Linux 仓库根目录，创建新的外部 work-root，把组合证据目录中的 baseline-policy.cpp、baseline-math.cpp 分别复制为 work-root/baseline-policy.cpp、work-root/baseline.cpp；指定新的空输出目录运行：

```bash
python .project/native-training/benchmark_ppo_paired.py --work-root /tmp/NEW_WORK --output /tmp/NEW_EVIDENCE
python .project/native-training/quality.py run --build-root /tmp/NEW_BUILD --output /tmp/NEW_QUALITY
python .project/native-training/benchmark_ppo_workers.py --build-root /tmp/NEW_BUILD --work-root /tmp/NEW_WORKERS --output /tmp/NEW_WORKER_EVIDENCE
```

微基准的完整源码指纹早于新增标量测试；审计已核对候选生产文件和头文件 hash 未变化，完整质量与 worker 证据绑定最终源码。旧学习和安装收据继续作为历史证据；本轮未重新执行学习研究或构建 wheel，不将旧 wheel 标为当前优化版本。后续重点是稳定环境下的长时流水线对照及当前版本交付验证。远端 CI 与暂停中的 GPU 验收仍开放，产品里程碑不因此自动升级。

## ??????

???????????? 2026-10-15 ???2026-10-17 ??? [worker ??????](selected-digests-report-20261017.md)??????????????????????????????
