# NT-4.4 — 原生训练入口、多seed冻结评估与跨进程续训

2026-10-15。新增`native_ppo_train`和`EvaluatePpo`，不改旧Gaussian/RLtools
路径、PPO数学或FPPO格式。C++23静态评估库链接已有learner/engine，无Python
依赖。新增CLI没有把纯推理冒称为学习，实际调用PpoLearner.train更新parameters。

## 接口与评估边界

- 有界CLI：updates0..1024为额外完整updates、rollout1..256、players1..11、
  hidden1..64、epochs1..16、minibatch1..256、cadence1..1000、episode limit/
  eval horizon1..4096、eval episodes0..64；strict numeric parse/重复及未知
  option拒绝。支持root/eval seeds、load/save、right/v2/compact/stacked/
  checkpoints；JSON记录完整配置、update metrics/trajectory和state hashes。
- 两个明确的deterministic native templates：sparse empty_goal（2left/1right，
  ball x=.77，duration400，score/out/possession结束）与project default11v11。
  不声称执行任意Python scenario，或与Python stochastic academy的配置相同。
- 四种evaluation策略：模型sample、模型argmax、configured均匀random、
  builtin-AI action19。独立env/RNG，每策略相同engine episode seeds；raw
  eval env启用K20仅为允许AI baseline，model/random仍使用configured K。
- `EvaluatePpo`比较完整learner bytes before/after，覆盖weights、moments、
  三RNG、train env及counters；initial/final evaluation不调用update。
  `--updates0 --load`只评估已恢复weights；horizon保留truncated语义。
- Mean score delta为controlled team的goal difference，不是短horizon的win rate。
  Reward只有配置开启时包含checkpoint shaping。记录每episode seed/length/
  reward/status，不能拿同root seed但不同engine episodes做不公平对比。

## 验证与实证

CLI专项三项通过：strict invalid options；actual update+prefix/resume/frozen
新进程对照；11player right/stacked/compact/v2。Full integration将这些加入
既有69项Python（最终72项）和八个C++ contracts。额外native CLI smoke和
无Python链接检查。最终证据 `evidence/nt-4.4-integration-20261015-a/`。

最终实验 `evidence/nt-4.4-experiments-20261015-b/`：两个scene×三root seeds
7/42/123，每次6updates×128joint transitions、hidden16/epochs4/minibatch32，
episode limit128；eval seed12345、3episodes、96step horizon。每case运行：

1. 新进程full六updates，保存final checkpoint，initial/final evaluation。
2. 新进程prefix三updates，保存中间checkpoint，evaluation采样关闭。
3. 新进程load prefix再三updates，保存resumed checkpoint和final evaluation。
4. 新进程load full final、updates0，验证frozen evaluation。

必须逐项完全相同：full/prefix迭代前半、full/resumed后半的trajectory/reward/
loss/gradient/delta/optimizer steps；完整final checkpoint bytes及SHA256；
full/resumed/frozen evaluations；全量training state的evaluation前后hash。
所有实际update parameter delta须非零。Raw logs/json、command/environment
source manifest及binary/checkpoint hashes保留；二进制checkpoint在isolated
work-root，不把大量生成模型binary提交到仓库。

A轮是JSON配置字段完善前的开发运行；B按最终代码重跑并作为验收证据，
保留A真实manifest，不冒称它覆盖最后版本。ASan/UBSan/LSan增量验证新增
evaluation/CLI路径：`evidence/nt-4.4-evaluation-sanitized-20261015-a/`，actual
library/core instrumentation、真实两次update、initial/final四baseline及state
isolation；NT-4.3全引擎八contracts仍是其历史代码范围，不混称同一source。

## 学习结论限制

短实验用于真实update/恢复和evaluation隔离验收，不是收敛实验。先前A轮
sparse sample mean reward：seed7 0→0、42 0→1/3、123 1/3→0；random2/3，
builtin AI1。11v11所有短evaluations得分0。最终表以B日志/实验报告为准。
最终B已passed=true，六配置/24进程对照通过，checkpoint file SHA256与
full-state hash一致。结果与限制见TRAINING_EXPERIMENTS.md；新增eval/CLI
ASan/UBSan/LSan也passed=true。
最终完整integration passed=true：72项Python（92.670s）、八个C++ contracts、
native CLI smoke及无Python链接通过。Integration、最终B实验和新增eval
sanitizer的source fingerprint相同，任务完成。
不支持通用学习提升或已学会足球的声明；只有一个seed上升且另一个下降，
episode数/horizon太小，不作显著性或完整比赛胜率解释。

Graph Verify project root-work_space-football；existing接口coverage generation
2026-10-14T22:15:01Z，新路径22:25:43Z，metadata match且无记录缺口。
完整sources和真实接口源码核对，coverage不代表穷尽。S4全局review在本任务
提交后另起审查轮次，再进入S5；长期目标保持active。
