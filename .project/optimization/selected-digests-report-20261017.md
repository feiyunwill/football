# Worker 摘要选择优化：2026-10-17

已保留生产优化：`NativeWorkerPool.digests(workers=None)` 支持只请求指定的、已经 reset 的 worker；采样器在 episode 结束时传入刚结束的 worker 列表。无参数调用继续返回所有已 reset worker 的摘要。选择范围、类型、重复和未 reset 状态均在 IPC 前校验；请求期限和失败时关闭整池的规则保持原行为。

## 问题与结果

旧采样器每次收尾都请求所有曾 reset 的 worker。4 workers 采集 5 个等长 episode 时，第一批四个结束后请求四次；最后一个结束时仍请求四次。新版本分别请求四次和一次，摘要 worker 请求合计从 **8 降至 5（减少 37.5%）**，所有 episode 结果、轨迹和最终内核摘要一致。

隔离摘要阶段的配对实验使用真实 11 人环境、4 个 persistent spawn workers、cadence 2。对照请求全部四个 worker，候选只请求所需的一个；8 对轮换顺序，每段 512 次请求。预设门槛为父子进程合计 CPU 成本中位数下降至少 50%，且配对 bootstrap 95% speedup 下界大于 1。

最终 B 轮结果：

- 所需摘要完全一致，worker 请求减少 **75%**。
- 摘要阶段父子进程合计 CPU 成本中位数下降 **72.01%**。
- 配对 speedup 95% 区间 **3.286–3.826**，通过预设门槛。
- 另执行 8 对真实 `5 episodes × 8 steps × 11 players` 采样，episode 结果、奖励、轨迹及最终内核摘要完全一致。

CPU 成本包含父进程 `process_time` 与各 worker `/proc/PID/stat` 的 user/system CPU ticks；后者存在时钟 tick 量化。原始配对数据保留在[最终实验收据](../native-training/evidence/selected-digests-20261017-b/report.json)，同目录保存实验脚本快照。A 轮为早期诊断，B 轮在改善脚本可读性及增加快照保存后重跑，未修改生产候选或放宽门槛。

**72.01% 仅属于“只需一个摘要”的摘要 IPC 阶段，不代表完整采样或训练提升。** 全批次同时结束时仍需全部摘要；本轮没有重跑长时 PPO 扩展矩阵，不将之前未通过的全配置 2 倍目标标为通过。

## 验证

- 新增真实进程测试，检查选择错误不发出 IPC、不改变状态；选择单个 worker 的请求和返回键准确；无参数调用兼容。
- 新增真实采样测试，直接检查不满批次的摘要请求为 `(0,1,2,3)`、`(0,)`，并与旧的全 worker 行为比较完整 episode 结果。
- **74 项 Python 集成测试、8 项 C++ 契约全部通过**，无跳过：[当前完整质量收据](../native-training/evidence/selected-digests-quality-20261017-a/report.json)。
- 当前源码、环境、原始质量日志、实际加载引擎二进制、实验脚本 hash、配对统计与退出状态均已核对：[本轮审计](../native-training/evidence/selected-digests-audit-20261017-a/report.json)。

本轮没有改动之前保留的 C++ PPO 优化。旧 PPO 性能、学习、安装及 worker 扩展收据保留为各自源码版本的历史证据；当前源码的完整质量入口以上述新收据为准。当前优化版 wheel、远端 CI、长时流水线对照仍待后续验证；GPU 验收继续暂停。

## 复现

在 Linux 仓库根目录，使用已安装训练依赖的 Python，先准备 staged 原生模块，再运行：

```bash
PYTHONPATH=/tmp/football-native-assessment-20261015/validation-stage:. \
GFOOTBALL_DATA_DIR="$PWD/engine/data" \
GFOOTBALL_FONT="$PWD/engine/fonts/AlegreyaSansSC-ExtraBold.ttf" \
python .project/native-training/benchmark_selected_digests.py --output /tmp/NEW_DIGEST_EVIDENCE

python .project/native-training/quality.py run \
  --build-root /tmp/NEW_BUILD --output /tmp/NEW_QUALITY
```

输出目录需使用新路径。基线行为通过同一 pool 的无参数 `digests()` 重现；采样对照将收尾请求转换为该全 worker 调用，保持相同种子、动作、环境步数和 reset 次数。
