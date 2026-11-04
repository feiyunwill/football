# 2026-10-18 学习泛化与交付验收

约定的本阶段目标已完成：[最终审计](../native-training/evidence/learning-delivery-audit-20261018-a/report.json)。
源码 SHA256：`9443b0308bd536d70df6cd567177fa17d3db071269b6f3becd84d9a404334029`。

## 学习结果

主策略为 categorical sampling。两个任务分别训练五个独立种子，每个模型确认评估 200 回合；确认起点与训练、验证和旧测试集合互不重叠。两个任务均通过预注册的均值、逐种子及配对置信区间门槛。

| 任务 | 平均成功率 | 相对未训练采样策略提升（95% CI） | 相对随机策略提升（95% CI） |
|---|---:|---:|---:|
| 变起点空门射门 | 89.3% | 78.5 个百分点 [69.9, 86.7] | 77.3 个百分点 [71.2, 83.0] |
| 变起点有门将射门 | 92.2% | 79.6 个百分点 [72.7975, 86.1] | 81.7 个百分点 [76.3, 86.8] |

[学习审计](../native-training/evidence/sampled-confirmation-audit-20261018-c/report.json)复核了 98 条原始命令。先前任务原型的修正和失败的 argmax 试验完整保留，未替换失败种子或放宽门槛。采样策略的新确认试验使用新分区、新评估种子和重新训练的模型；不宣称贪心策略通过。

## 当前源码运行与交付

- [完整质量](../native-training/evidence/generalization-quality-20261018-c/report.json)：76 项 Python 集成测试、9 项 C++ 合约，无跳过。
- [30 分钟运行](../native-training/evidence/quiet-final-20261018-a/report.json)：1800.060 秒、8442 次更新、2,161,152 个联合转移，1200.60 转移/秒。外部 CPU 均值 0.0412 核、P95 0.0599 核，未观测到外部编译器。四个 worker 正常退出并回收，父进程 FD 运行前后均为 5。该结果是观测到低外部负载的 WSL 基线，不能推断物理主机完全隔离或新的加速比。
- [实际交付](../native-training/evidence/current-delivery-20261018-a/report.json)：精确导出当前工作树（含未提交修改），新构建 CPython 3.14/Linux x86_64 wheel，独立环境安装，仓库外加载及 76 项测试通过；原生目录包迁移、链接检查、完整/续训检查点一致性通过。
- [模型重放](../native-training/evidence/learned-delivery-20261018-a/report.json)：交付程序逐批重现全部 10 个模型的 2000 个确认回合，完整评估 JSON 一致；10 个模型各续训一次更新，交付程序与原构建产生的检查点逐字节一致。

保留的本机交付产物位于 `/root/work_space/football-artifacts/native-training-20261018-a/`，包括带 10 个模型的原生目录压缩包、wheel、精确源码快照、验收记录及 `SHA256SUMS`。解压原生包后运行 `./reproduce-generalization.sh` 可重放确认评估；模型、协议、结果和哈希清单位于 `study-models/`。未发布到远端。

归档证据的逐文件哈希见 [交付归档清单](../native-training/evidence/delivery-archive-20261018-a.json)；较早的学习及运行归档见 [学习归档清单](../native-training/evidence/learning-archive-20261018-a/manifest.json)。原始证据路径保留供审计。

本次验收范围为两个有界的单人变起点射门任务、当前 Linux/WSL 与 CPython 3.14 交付、当前源码持续运行。完整足球/11v11 能力、GPU、其他平台、远程 CI 及完整产品里程碑仍开放；未推送或发布。
