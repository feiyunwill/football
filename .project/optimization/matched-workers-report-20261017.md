# 固定工作量 worker 对照与 CPU 定位：2026-10-17

已补齐单 worker 长跑，并完成独立 worker CPU 剖析。生产源码保持原版本；本轮增加诊断与审计工具，没有保留新的生产性能改动。

## 同等工作量结果

两次运行均为 11 人、cadence 2、hidden 16、4 epochs、minibatch 64，每次更新四个最多 64 步的完整 episode；相同初始模型、episode-keyed RNG 和排序更新规则。四 worker 对照来自上一轮 30 分钟运行；单 worker 固定执行相同的 **4,475 次更新、1,145,600 个联合转换**。

| 配置 | 测量时长 | 联合转换/秒 |
|---|---:|---:|
| 单 worker | 3,494.95 秒（58.25 分钟） | 327.79 |
| 四 workers，历史对照 | 1,800.17 秒（30.00 分钟） | 636.39 |

本次观察到四 worker/单 worker 吞吐比 **1.9415**，未达到 2 倍。它是一对历史/后续运行的观察值，不是多次交错实验的中位数或置信区间，不能将全配置扩展目标标为通过。源码、构建产物和记录的环境身份相同，并不证明频率、主机负载或调度条件相同。

测量均排除启动、预热和最终保存/收尾，包含正常更新迭代、流式日志及周期资源/检查点开销。退出条件分别为原时长目标和新的固定更新数；已核对两者实际处理完全相同的更新集合。

## 等价性与资源

- **4,475 次更新逐条比较通过**：版本、转换数、loss、entropy、梯度范数、参数变化、KL、value loss 等指标一致。
- 完整 episode/更新回放 SHA 一致；最终模型参数、Adam 一二阶矩/步数、shuffle RNG 和版本的 canonical payload 完全一致。
- 检查点外层绑定运行器身份，新旧运行器 hash 不同；比较 payload 不等于绕过恢复身份校验。
- 单 worker 最终检查点在新进程冻结加载后 payload 一致，动作探测未改变文件、模型、优化器或 RNG。这不是完整续训或足球能力评估。
- 单 worker 正常退出并被回收，父进程 FD 恢复为起始的 6；worker RSS 从约 131.965 MiB 到 131.969 MiB。父进程 RSS 从初始约 48.65 MiB 到约 61.94 MiB，含模型/检查点和采样元数据分配，不据此声明不存在泄漏。

[固定工作量对照与逐更新审计](../native-training/evidence/matched-worker-comparison-20261017-a/report.json)、[单 worker 原始运行](../native-training/evidence/matched-w1-20261017-a/report.json)、[冻结加载](../native-training/evidence/matched-w1-checkpoint-load-20261017-a/report.json)。

## 阶段观察

相同工作量的累计阶段墙钟如下，数值仅描述这一对运行，不构成各阶段的独立因果比较：

| 阶段 | 单 worker / 秒 | 四 workers / 秒 |
|---|---:|---:|
| step RPC | 2,362.62 | 1,035.37 |
| reset | 568.30 | 192.27 |
| 原生 PPO 更新 | 302.04 | 340.32 |
| 推理 + 采样回调 | 140.63 | 103.48 |
| 摘要 | 16.62 | 7.39 |

step RPC 仍混合仿真、传输、Python 封装和调度；不能把它全部标为 IPC。PPO 更新在四 worker 运行中累计时间反而略高，说明不能忽略主机条件和并发竞争，也不能据此单次结果推断算法回退。

## 独立 CPU 剖析

未剖析长跑结束后，另以四 workers 执行 128 次真实 PPO 更新、32,768 个转换。使用 `cProfile` 的进程 CPU 计时，并在子进程的 Gym 与 `OwnedEngine._invoke` 边界记录累计 CPU/墙钟；所有原所有权和生命周期检查仍通过原方法执行。剖析开销不用于吞吐或扩展倍率结论。

首轮 A 显示 CPU 主要落在 `_invoke`，该 Python 帧也包含被转发的 C++ 时间，不能解释为 Python 所有权检查成本。B 轮进一步按 native 操作分组。四个实际 worker 的累计调用数据：

| native 调用边界 | 次数 | 进程 CPU / 秒 | 累计调用墙钟 / 秒 |
|---|---:|---:|---:|
| step | 32,848 | 51.51 | 54.32 |
| reset | 520 | 16.33 | 16.97 |
| get_state_digest | 516 | 0.29 | 0.30 |

次数包含实际 worker 的预热（额外 80 次 step）和环境构造的额外 reset；另一个专门 warmup worker 已排除。调用边界包含轻量 Python 适配/校验和绑定开销，并非已细分到 C++ 内部函数。

本轮 `cProfile` 记录 CPU 合计约 89.92 秒。以上 native step、reset 分别约为其 57%、18%，仅为相同 CPU 基数的近似参照，不是可与外层 Gym 计时相加的严格分区。四个线程的 `/proc/self/schedstat` runqueue wait 增量合计约 7.45 秒，范围还包含构造、预热、消息处理与收尾；不能加到父进程 RPC 墙钟，或称为其中调度等待的确定比例。

**128 次剖析更新的数值指标与未剖析对照同一前缀一致。** 原始 pstats、每 worker 调用/调度快照及源码快照见 [B 轮 CPU 分析](../native-training/evidence/worker-cpu-20261017-b/cpu-analysis.json)。原生 step/reset 是下一步值得深入采样的入口；纯 IPC 与调度等待仍未被完整独立分离。

## 审计与下一步

[综合审计](../native-training/evidence/matched-worker-audit-20261017-a/report.json)通过，核对回放、payload、原始日志与 pstats/timing 文件 hash、实际产物、冻结加载、worker 回收及当前有效的 74 项 Python / 8 项 C++ 质量收据。未改生产源码，因此没有重复整套质量构建。

下一项应对子进程的 **native step/reset 内部做采样**，定位具体 C++ 热点，再选择保序、可回滚的优化候选并做交错对照。保留至少 10% 主成本改善、正向配对区间和其他配置回退不超过 3% 的既有性能门槛；独立重复及其他配置扩展测试继续开放。

本轮不证明完整比赛学习能力、全配置 2 倍扩展、当前 wheel 交付或远端 CI；GPU 验收继续暂停。

复现固定更新运行，使用新目录：

```bash
python .project/native-training/profile_matched_ppo.py \
  --build-root /tmp/football-native-assessment-20261015 \
  --work-root /tmp/NEW_MATCHED_WORK --output /tmp/NEW_MATCHED_EVIDENCE \
  --workers 1 --updates 4475 --seconds 7200
```

`--seconds` 是上限，不是运行目标。独立剖析使用 `diagnose_worker_cpu.py`，不可与正式性能测量并行运行，也不可将其吞吐用于验收。
