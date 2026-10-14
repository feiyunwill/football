# 原生 categorical PPO 实验 — NT-4.4

2026-10-15。最终证据 `evidence/nt-4.4-experiments-20261015-b/report.json`，
passed=true；source fingerprint
`77856efdadd172e065bc9289b65deaa0339eddb5aa8b22f003f7f0759bb54c6c`。
证明真实更新、跨进程恢复及冻结评估隔离，不能证明已学会足球。

## 实验配置

Deterministic native sparse empty_goal和default11v11，各用root seeds7/42/123。
单个左队controlled player、simple115v2/plain/default19动作、hidden16；
6updates×128joint transitions=768步，epochs4/minibatch32、horizon128、
cadence10、scoring（无checkpoint shaping）。每个JSON的ppo字段保存完整
hyperparameters。不是旧Gaussian模型，也不是Python stochastic场景解释器。

Eval seed12345、三engine episodes、96step horizon。四策略使用matched
engine seeds：model sample、model argmax、configured uniform random、builtin
AI19。Initial为更新前，final为更新后冻结模型；goal difference不是win rate。

## 实际结果

Mean scoring reward，sample策略的initial/final：

| native场景 | root seed | initial sample | final sample | uniform random | builtin AI |
|---|---|---|---|---|---|
| empty_goal | 7 | 0 | 0 | 2/3 | 1 |
| empty_goal | 42 | 0 | 1/3 | 2/3 | 1 |
| empty_goal | 123 | 1/3 | 0 | 2/3 | 1 |
| 11v11 | 7 | 0 | 0 | 0 | 0 |
| 11v11 | 42 | 0 | 0 | 0 | 0 |
| 11v11 | 123 | 0 | 0 | 0 | 0 |

所有update parameters delta非零；loss/entropy/clip fraction/raw gradient norm/
Adam steps和trajectory记录为原始数值。稀疏一个seed上升、另一个下降，
random/AI更好；11v11短窗口未得分。不作统一学习提升、显著性、完整比赛
胜率、收敛或泛化声明。更长训练和更多独立episodes是后续学习效果研究，
不能用768步functional验证替代。

## 恢复/隔离证据

每配置四个独立进程，共24次：full六update、prefix三update、load prefix
再三update、load final的zero-update frozen evaluation。全部比较通过：

- full前半=prefix、full后半=resumed，每项update和trajectory完全一致。
- final/resumed checkpoint bytes相同，file SHA256=JSON完整state hash。
- full/resumed/frozen-only四策略evaluation一致，evaluation前后完整learner
  bytes一致，覆盖optimizer/RNG/live engine。
- checkpoint约99,891–162,573bytes；binary位于isolated work-root，repo
  保存bytes/hash、commands/source/binary指纹及raw logs/JSON。

A轮是JSON配置字段补充前的开发记录，B是当前代码验收。B/tooling保存
validator版本，源码由manifest/Git追踪。elapsed time包括初始化/checkpoint/
evaluation，不作为训练吞吐benchmark。新增eval/CLI sanitizer证据
`nt-4.4-evaluation-sanitized-20261015-a` passed=true，实际两次update及四基线
isolation通过。完整集成和S4全局review另有证据。

## 复现

构建native_ppo_train（C++23、bindings OFF、isolated --parallel 1）；训练
二进制无Python依赖，evidence harness使用既有runtime解释器：

```bash
python .project/native-training/validate_ppo_experiments.py \
  --build-root /tmp/football-native-validation \
  --work-root /tmp/football-ppo-models-new \
  --output /tmp/football-ppo-evidence-new
```

work-root/output必须不存在，不覆盖旧证据。CLI和resume/eval-only用法见
gfootball/doc/native_training.md；短实证不代替阶段review。
