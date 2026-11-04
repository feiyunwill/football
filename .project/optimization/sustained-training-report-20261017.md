# 首条持续 PPO 训练基线：2026-10-17

已完成[长期目标](sustained-training-plan-20261017.md)第一阶段的首条 30 分钟基线：真实 on-policy PPO 持续 **1,800.17 秒**，完成 **4,475 次更新、1,145,600 个联合转换**。运行、独立日志核对、新进程冻结加载及综合审计均通过。本轮新增测量工具，没有修改生产训练代码。

## 配置与吞吐

Linux/WSL，`11_vs_11_easy_stochastic`，11 人、cadence 2、四个 persistent spawn workers，hidden 16、4 epochs、minibatch 64。每次更新四个完整 episode，每个最多 64 步，最多 256 个样本。策略与 PPO 数学使用现有生产 C++，通过仓库外编译的诊断桥接调用。

| 指标 | 结果 |
|---|---:|
| 全程平均联合转换/秒 | 636.39 |
| 完整分钟窗口吞吐中位数 | 647.90 |
| 分钟窗口 P10 / P90 | 541.88 / 714.38 |
| 分钟窗口最小 / 最大 | 432.90 / 805.55 |
| 最后五个 / 最初五个完整窗口吞吐中位数 | 1.030 |

单位没有乘以 11 个玩家。运行中累计均值曾下滑，后段恢复；完整窗口比较未显示持续退化，但波动仍较大，单次运行不能判定原因或证明稳定扩展性能。这些分位数是描述统计，不是独立重复的置信区间。

## 阶段成本

以下占比以计时迭代墙钟为分母；计时迭代占整段会话约 **97.51%**。周期检查点保存与同进程第二实例恢复校验合计 4.63 秒，约占会话 0.26%；其余还有流式记录、资源采样等开销。启动、预热和最终收尾另计。

| 阶段 | 占计时迭代 |
|---|---:|
| step RPC：引擎步进往返 | 58.98% |
| 原生 PPO 更新 | 19.39% |
| reset | 10.95% |
| 采样回调，包含旧/后继状态估值 | 4.37% |
| 其余收集工作 | 2.36% |
| 附加 KL/value 等诊断 | 1.84% |
| 策略决策 | 1.53% |
| 最终状态摘要 | 0.42% |
| 更新桥接与收尾 | 0.13% |

**step RPC 包含仿真、IPC 与调度，不能将 58.98% 归因于纯 IPC。** 第一、最后五个完整窗口相比，step RPC 单位转换成本约为 0.956 倍，PPO 更新约为 1.026 倍；未看到单个阶段的明显持续恶化，但不足以排除主机状态或工作量差异。

## 资源与正确性

- 父进程 RSS 从首个快照的 48.66 MiB 到最终 60.89 MiB，峰值 61.97 MiB；包含初期分配、诊断检查点及采样元数据，不能据此证明不存在泄漏。
- 四个 worker RSS 合计从 527.46 MiB 到 527.52 MiB，观测增量 64 KiB。RSS 相加会重复计算共享页。
- worker FD 合计始终为 32。父进程测量中有日志文件句柄，收尾 FD 恢复为起始的 6。
- 四个 worker 均以 0 退出且已回收；源码、工具、环境及实际加载二进制在运行期间未变。
- 最终学习器版本为 4,475。检查点在新进程恢复后完整 payload 相同，冻结动作探测不改变模型/优化器/RNG 或文件 SHA。该探测不等同于完整续训等价性或足球能力评估。
- 当前生产源码仍匹配已有 **74 项 Python 测试、8 项 C++ 契约**的完整质量收据，本轮核对其有效性，没有将旧源码收据重新标为新版本。

## 证据与复现

- [原始运行收据](../native-training/evidence/sustained-ppo-20261017-a/report.json)，同目录有逐更新 JSONL、资源 JSONL、最终诊断检查点及运行器/桥接源码快照。
- [独立分析](../native-training/evidence/sustained-ppo-analysis-20261017-a/report.json)及[分钟成本 CSV](../native-training/evidence/sustained-ppo-analysis-20261017-a/minute-costs.csv)。
- [新进程冻结加载](../native-training/evidence/sustained-checkpoint-load-20261017-a/report.json)。
- [综合审计](../native-training/evidence/sustained-baseline-audit-20261017-a/report.json)，同时核对原始日志 hash、当前完整质量和检查点。

在安装好训练依赖的 Linux Python 中，提供有效 staged 引擎，使用新的 work/output 路径：

```bash
python .project/native-training/profile_sustained_ppo.py \
  --build-root /tmp/football-native-assessment-20261015 \
  --work-root /tmp/NEW_SUSTAINED_WORK \
  --output /tmp/NEW_SUSTAINED_EVIDENCE --seconds 1800
python .project/native-training/analyze_sustained_ppo.py \
  --evidence /tmp/NEW_SUSTAINED_EVIDENCE --output /tmp/NEW_SUSTAINED_ANALYSIS
python .project/native-training/verify_sustained_checkpoint.py \
  --evidence /tmp/NEW_SUSTAINED_EVIDENCE --output /tmp/NEW_CHECKPOINT_LOAD
```

## 下一步决策

优先补齐同协议的**单 worker 持续基线**，然后在独立实验中拆解 worker 端仿真 CPU 与父进程等待。做扩展倍率判定时使用固定更新序列/样本预算、独立重复和交错运行顺序，而不是把相邻分钟窗口当作独立样本。先判断仿真、IPC 和调度各占多少，再决定生产优化位置。

本次只是单配置持续时间与成本基线；episode 仍最多 64 步，属于短 episode 的持续更新，不代表完整比赛或长 horizon。没有验证全配置四 worker 2 倍目标、变化开局/门将学习、当前 wheel 交付或远端 CI；GPU 验收继续暂停。

## ????

[?? 4,475 ????? worker ??? CPU ??](matched-workers-report-20261017.md)??????????? worker ???????
