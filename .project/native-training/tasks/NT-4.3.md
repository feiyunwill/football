# NT-4.3 — categorical PPO 更新与完整 learner checkpoint

2026-10-15。按PPO_DECISION实现 `ppo_math` 与 `PpoLearner`。本任务包含真实
update与恢复合约；多seed评估/学习实验仍由NT-4.4执行，未宣称学会足球。

## 数学和原子更新

- GAE每步保留old value、reward、final next value及两种结束标志；terminal
  bootstrap0，horizon/live bootstrap最终观测；terminal/truncate切断递归。
  Return用未归一化advantage，population std+1e-8归一化只用于policy loss。
- 每player categorical构成joint distribution，logP和entropy求和。PPO clip
  区分正/负advantage的饱和侧；shared tanh MLP analytic backprop覆盖logit/
  value两head。无value clipping或隐含Gaussian/nearest-player映射。
- Adam m/v、step、bias correction、epsilon显式；minibatch平均gradient做
  global norm clipping。Epoch1..16、minibatch1..256、rollout1..256。
- 先验证所有old version/value/logP与当前frozen native policy，再在副本上
  全epoch更新。完成后model/optimizer/shuffle RNG一起commit；非法shape、
  mixed/stale policy、NaN/Inf或overflow不留下partial update。
- PolicyRng增加无偏rejection-sampling index，用于Fisher–Yates shuffle和
  engine seed抽样；sampling/shuffle/episode streams由独立root-seed tags生成。

## learner与checkpoint边界

- 一个owner-thread/process learner拥有模型、优化器、三个live RNG和native
  env；generic ScenarioConfig做canonical identity clone，配置getter也返回
  detached scene。采样过程中episode按limit/terminal显式reset，seed更新
  independent；return和episode/transition/version counters均保存。
- 一次iteration的sampling已推进env。如果随后update失败，数学状态仍保持
  原模型/optimizer，但learner关闭已推进的env，必须load checkpoint恢复，
  不假称整次simulation已回滚，也不自动retry。
- FPPO v1：独立magic/schema，length+SHA256，32MiB总预算；网络/算法/RNG
  版本、配置/hypers、全部参数/m/v/Adam-step、三RNG、policy/transitions/
  episode counters、base/current完整scenario身份、episode return、FTRN
  native snapshot、float32 current obs与lifecycle全部记录。checksum不等于
  authenticity。旧RLtools TAR/FTRN/FPTR含义不改。
- 只在完整update边界（含zero-update初始状态）存取，buffer为空；不支持
  mid-rollout。恢复先检查config、内部shape/count/finite/moments/counters，
  再创建staging engine，reset已保存当前scenario/seed，恢复完整FTRN。
  current obs与restored engine independently核对，成功后无throw commit所有
  learner字段；失败不改变原target，包括late observation mismatch。
- NativeTrainingEnv.current_observation读取缓存或stack ring，不追加frame/
  推进物理；NativePolicyEnvironment.restore是staging接口，失败关闭staging。
- 复用既有bounded atomic-file helpers并指定32MiB预算；same-dir temp/fsync/
  replace，nonregular/symlink读取拒绝。文件语义为Linux/POSIX范围。

## 证据与验收

专项C++ math和独立NumPy三项参考已通过：五个joint两player clip/sign分支，
每个579个参数完整finite differences（C++和独立NumPy目标）、value/entropy
shared backprop、live/truncate/terminal GAE、population normalization、Adam
前两步及bias correction、invalid-gradient/mixed-version atomicity、seeded
完整update重放。真实update参数delta非零且finite。

真实engine checkpoint contract覆盖plain单人/default和stacked右队多人/v2/
compact/checkpoints两模式：save/restore后完整state bytes一致，继续9-step
update的trajectory/reward/参数delta和完整checkpoint同未中断baseline。
拒绝magic/checksum/truncation、valid-checksum非法shape、late duplicated obs
损坏、foreign seed；失败后target不变。另验证file load/save/nonregular/
symlink、wrong-thread及configuration pointer isolation。

完整release证据 `evidence/nt-4.3-integration-20261015-a/report.json`；完整
ASan/UBSan/LSan证据 `evidence/nt-4.3-sanitized-20261015-a/report.json`。
最终passed、数量与source manifest以报告为准。验证器纳入69项Python
（含新增独立reference）和八个C++ contracts，sanitizer检查八个实际core/
policy/learner target的编译flags与ldd，使用isolated C++23 serial builds。

任务自审重点是joint gradient、截断bootstrap、不可混用policy-version、
完整optimizer/RNG/environment及late-failure staging。Graph Verify coverage
generation 2026-10-14T21:38:43Z及21:55:36Z，已有和新material路径metadata
match、无记录缺口；源码已直接核对，coverage不是穷尽证明。

最终Release passed=true：69项Python（82.218s）、八个C++ contracts、native
rollout及无Python链接检查通过。完整ASan/UBSan/LSan passed=true，八个实际
core/policy/learner targets instrumentation及八个contracts全部通过；不是
沿用NT-4.2 standalone-math的证据。两轮源码fingerprint一致：
`7f05ac73e33d26e6c2e9d2bba5e77cf516a8bed489d1f7e06e24b2c7bcea76c3`，1220项。
任务完成。

NT-4.4再提供真实native CLI、多seed冻结评估/随机及builtin-AI baseline、
跨进程恢复实验；之后执行S4全局review。当前不把这些update/恢复contracts
当作学习收益或整个长期目标完成的证据。
