# 使用、迁移和回滚

## 一条命令复现原生训练

先按 DELIVERY.md 生成 Linux native 目录包；以下脚本完成完整训练、分段训练、
新进程续训和冻结评估，并比较更新/trajectory、完整 checkpoint 字节和评估：

```sh
python .project/native-training/reproduce_training.py \
  --program /tmp/football-native-package/native_ppo_train \
  --output /tmp/football-native-reproduction
```

默认 seed42、2 次更新、每次8样本、hidden8、epochs2、minibatch4；评估每种
策略一个 episode、horizon16。output 必须是新目录，保存四个 JSON、stderr、
三个 FPPO 文件及报告。可调整 --seed、--updates、--split、--rollout 和
--timeout；split 是中断位置，必须小于总 updates。这是短功能复现，不是训练
预算或已学会足球的证明。更长/多 seed 研究应参考 TRAINING_EXPERIMENTS.md。

单独训练、冻结评估和续训的 CLI 用法：

```sh
PROGRAM=/tmp/football-native-package/native_ppo_train
"$PROGRAM" --seed 42 --updates 4 --save /tmp/football-policy.fppo
"$PROGRAM" --seed 42 --updates 0 --load /tmp/football-policy.fppo
"$PROGRAM" --seed 42 --updates 4 --load /tmp/football-policy.fppo --save /tmp/football-policy-next.fppo
```

updates 总是额外更新数。load 时 scenario、seed、players/features/actions/hidden、
cadence、episode limit、reward 和 optimizer 配置必须匹配原文件。
默认是 empty_goal 原生模板，并非解释 Python academy 文件；11v11 是另一明确
模板。sample/argmax/random/builtin AI 基线使用匹配 engine seeds，报告是 goal
difference，不是 win rate。训练目标为单侧联合离散策略、团队平均 reward/value；
算法与 GAE/terminal/truncated/PPO 约定见 PPO_DECISION.md、PPO_CHECKPOINT.md。

## 现有 Python 用户

现有 FootballEnv 默认 backend='python'，原有场景编排和训练生态仍可使用。
需要数值原生内核时显式选择 backend='native'，例如：

```python
from gfootball.gymnasium import FootballEnv
from gfootball import training_snapshot

env = FootballEnv(backend='native', env_name='11_vs_11_easy_stochastic',
                  representation='simple115v2', stacked=True,
                  rewards='scoring,checkpoints')
try:
    observation, info = env.reset(seed=42)
    state = training_snapshot.get_state(env)
    observation, reward, terminated, truncated, info = env.step(0)
    training_snapshot.set_state(env, state)
finally:
    env.close()
```

支持范围以 COMPATIBILITY.md 为准；native 不支持的像素/SMM/raw、render、
extra_players 和录制配置明确拒绝，不静默切换实现。step_many 是预设动作批量，
raw env 内遇 terminal 返回前缀，不自动 reset；外层 wrapper hooks 不在 batch
中执行。依赖当前观测的策略用闭环采样或原生 PPO，而不是预先填满动作序列。

## 回滚与格式边界

回到旧 Python 路径时，新建 FootballEnv(backend='python', ...)，从新 episode
开始；已有 Python 算法入口与模型格式保留。不要将 native 训练 checkpoint 当成
Python 后端的实时状态载入。需要撤回部署时保留旧安装环境/原生目录包和原文件，
切回原入口；本路线没有替用户卸载旧环境或覆盖旧模型。

FTRN 是环境快照；Python helper 外层还含 Gym RNG、episode 和标准 wrapper
状态；FPPO 则是新 learner 的环境、参数、Adam、RNG 和计数完整状态。旧 RLtools
Gaussian checkpoint 是另一路径。三者不能互换，不提供静默转换或 pickle 迁移。
恢复必须同源/构建/资源/ABI及配置；升级前保留旧 binary/venv 和 checkpoint，
升级失败应使用原构建恢复。文件原子保存保护旧文件；仍建议新版本写新文件名。

原生运行不需要 Python；Gym/scenario 编排、wheel 安装和验证脚本仍使用 Python。
平台实际证据与未验证版本见 PLATFORMS.md；质量入口见 QUALITY.md。
