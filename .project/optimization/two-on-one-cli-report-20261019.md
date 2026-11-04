# O21：正式 CLI 的 balanced 推理与恢复验收

本阶段目标已完成：[最终收据](../native-training/evidence/o21-cli-20261019-a/report.json)。长期训练目标仍未完成。

`native_ppo_train` 现已提供正式的 `--inference-mode balanced|argmax|sample|uniform_random|builtin_ai` 入口，支持有界 2v1 场景文件、决策预算和跨进程会话恢复。默认训练、原始 argmax 和采样行为保持原定义。推理模式拒绝训练参数，固定 simple115、19 动作、cadence10、每回合最多256次决策及固定 AI 队友。

```sh
./native_ppo_train --inference-mode balanced --policy inference/42.fpol --inference-cases inference/cases.txt
./native_ppo_train --inference-mode balanced --policy inference/42.fpol --inference-cases inference/cases.txt \
  --inference-decisions 8 --inference-state-out session.fifs
./native_ppo_train --inference-mode balanced --policy inference/42.fpol --inference-cases inference/cases.txt \
  --inference-state-in session.fifs
```

生产源码 SHA256：`c1d57094a4eb3976a35ba3061d93bbea984d134a9f191af7a28bef9e4adf5ae8`。本轮重新执行当前源码的完整质量门槛，并从当前工作树独立构建 wheel、在新虚拟环境安装和执行79项测试；没有将旧源码的质量或安装收据冒充当前验收。

## 快照与模型边界

FPPO 的源码、构建、ABI、资源和配置校验保持严格；实际测试确认新构建拒绝旧 FPPO，报错为 `Incompatible training build or runtime dimensions`。

五个 O20 模型先在原兼容引擎中载入并核对完整快照字节，再显式导出仅策略的 FPOL1 文件。该格式记录任务视图版本、策略/RNG版本、网络权重和原 FPPO SHA256；不导入优化器或训练环境，不能用于训练续跑。新 CLI 的 `--export-policy FILE` 可以在兼容构建中导出当前2v1策略，禁止改写旧快照身份来迁移训练状态。

FIFS1 会话保存引擎快照、DIC1 控制器状态、动作 RNG、配合历史及累计回报，绑定完整策略文件、场景文件和推理模式。恢复继续执行原生快照的构建、资源和场景校验。错误版本、校验和、模式和输入匹配检查通过实际测试。

## 验证结果

- 工作树构建的79项集成测试和完整原生契约检查通过。
- 独立 wheel 安装后的79项集成测试通过，训练完整运行与恢复运行保持一致。
- 正式 CLI 的1000个 balanced 回合及2000个 argmax/采样对照回合，与 O20 对应回合 JSONL **逐字节一致**。这些是旧数据一致性回归，不是新的学习确认。
- 五个模型在五种场景类型各取一个固定回合，均通过真实新进程恢复；另对全部五种推理模式及恰好停在回合边界的状态恢复进行核对，完成回合行均与完整运行一致。
- 生产控制器与 O20 适配器在10,000次不同概率输入下，动作及序列化字节完全一致。非法状态和概率输入不改变原状态。
- 迁移后的当前原生包复现1000个主要回合；实际归档解压到另一目录后，包内脚本再次复现1000回合并通过五个SHA256。安装包自身核心库的推理暂停、跨进程恢复也通过。

回合行保持确定性。末行 summary 包含本次调用的时间与计数，分段续跑及复现哈希忽略各段 summary。

## 接入成本

hidden64、合成单人观测，按固定交错顺序执行五次、每次20,000次决策，测量 `forward + distribution + 动作选择` 的中位数：

| 模式 | 每次决策 |
|---|---:|
| balanced | 2.90 μs |
| argmax | 2.81 μs |
| sample | 2.84 μs |

balanced 相对 argmax 的中位差异约3.0%，仅限该短测。控制器对象为176 B，样本序列化状态为410 B，不包含引擎快照。原始测量保留首次运行及其余四次，不剔除较慢样本；主机频率和固定执行顺序会影响结果，没有建立长期延迟或显著性结论。

五个模型各运行200个匹配场景，使用单个子进程 `wait4` 资源统计：

| 模式 | 进程墙钟中位数 | CPU中位数 | 决策吞吐中位数 | 最大RSS |
|---|---:|---:|---:|---:|
| balanced | 9.42 s | 9.35 s | 1019/s | 79.8 MiB |
| argmax | 10.02 s | 9.98 s | 1037/s | 79.9 MiB |
| sample | 9.82 s | 9.73 s | 1014/s | 79.9 MiB |

模式间动作和回合长度不同，这些是当前机器的端到端观察值，不能据此宣称引擎加速。没有重新训练模型或新增30分钟持续运行结论。

## 交付

持久目录：`/root/work_space/football-artifacts/o21-cli-20261019-a`，包含当前 wheel、原生归档、acceptance.json 和 SHA256SUMS。原生包仍依赖兼容 Linux 系统动态库。

```sh
tar -xzf football-o21-native-inference.tar.gz
./football-o21/reproduce-inference.sh NEW_OUTPUT_DIRECTORY
```

执行脚本会使用包内正式 CLI、核心库、资源和五个策略文件，自动核对所有主要回合。协议见[执行计划](two-on-one-cli-plan-20261019.md)，使用说明见[原生训练文档](../../gfootball/doc/native_training.md)。

保留一次工具启动失败：parity-a 缺少系统 `/usr/bin/time`，尚未执行任何回合；parity-b 改用 Python 的 monotonic/wait4 计时，生产源码及验收门槛未变。
