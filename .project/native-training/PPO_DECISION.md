# NT-4.1 接入决策：共享 native 环境上的独立 categorical PPO

2026-10-15。本文记录 NT-4.1 的历史接入决策；NT-4.2–NT-4.4 已实现并通过
S4 review，当前验收与限制见 reviews/S4.md。目标保持离散 PPO、真实足球内核、完整
恢复及纯 C++ 入口，不改为其他算法，也不新增大型依赖。

## 已核对的配置路径

现有真实引擎入口为 `engine/src/frame_sync/rl_training/training.cpp`，使用
`GameEnvWrapper`、`ConfigApproximatorsSequential`、vendored PPO core runner。
另一个 `engine/tests/rl_football_training.cpp` 是2D POC，不能当作真实足球
训练证明。本决策审计真实入口所选路径，不宣称整个 RLtools 所有 backend
都不存在 categorical 支持。

| 范围 | 当前实现证据 | 对新接口的影响 |
|---|---|---|
| 网络输出 | core/config.h 的 Actor 为 mlp_unconditional_stddev，输出 ACTION_DIM=1、log_std | 是 Gaussian mean/std，不能把输出宽度直接改成19/20就视为 categorical |
| 采样 | on_policy_runner/operations_generic_per_env.h epilogue 调用 normal_distribution::sample/log_prob | rollout log-prob 是连续潜在动作的密度 |
| 映射 | GameEnvWrapper::step clamp(raw,0,1)，int(raw*20)，只给最近球员下动作 | 不等于 native default/v2 action-set index 或每个controlled-player的联合动作 |
| 更新 | ppo/operations_generic.h Gaussian log_prob、mean/log_std 导数及 Gaussian entropy，再计算 PPO clipped ratio | clipped surrogate 可保留数学目标，但 likelihood/entropy/gradient 必须更换 |
| 观测/reward | wrapper OBS_DIM=147；±10 goal、possession、approach、penalty 等额外 shaping | 不等于现有 simple115/115v2、scoring/checkpoints 合约 |
| 终止 | wrapper step 强制 next.done=false，terminated 返回 done；runner 用episode step limit或terminated设置truncated/reset | 不等于原生 match terminal 与 horizon truncate 的两种标志 |
| GAE | 非terminal truncated 时 td_error=0，终止要求内部 reset/truncated marker | 不符合本项目 horizon 从最终观测 bootstrap 的要求 |
| checkpoint | core保存 actor/critic optimizer、PPO、runner/dataset、normalizers、rng、step和IDs；runner保存 feature State/raw env bytes | 没有保存外部 g_rl_env 的 Match/ball/referee/PRNG完整内核；不能证明真实引擎续训一致 |
| legacy play | training.cpp eval_mode仍调用rlt::step；core/operations_generic.h step调用collect/GAE/train | 新评估必须走独立inference路径，不复用这个training loop作为冻结策略评估 |

Gaussian latent-action PPO 通过多对一映射可以定义自己的策略；本决策没有把
它泛称为数学无效。它不满足用户路线的**native categorical**要求：真实离散
动作的概率质量是Gaussian区间积分，并不是采样潜变量的density；硬裁剪不能
替代K分类的softmax/log-prob/entropy。

## 编译与实际探针

`evidence/nt-4.1-audit-20261015-b/` 保存13份审计输入的完整原始源码与SHA256，
以及compiler、configure/build/linkage和runtime probe日志。C++23 CPU探针
直接实例化vendored Dataset并调用真实estimate_generalized_advantages，不
是抄写公式做自证。r=1、V=2、final V=3、gamma=.99，实际结果：

| 标志（vendored内部语义） | 实际advantage |
|---|---|
| terminated=false, truncated=false | 1.97 |
| terminated=false, truncated=true | 0 |
| terminated=true, truncated=true | -1 |

Gaussian log_prob(mean=0, log_std=0, action=0)为 -0.9189385332046727。
探针与原有 `rl_football_training` 目标均编译成功；ldd无libpython/missing
依赖。旧目标没有设置统一runtime output property，实际在build root。
审计脚本已按真实产物定位；A轮保留该脚本路径假设错误的失败日志，不把它
列为代码构建失败。B轮完成后恢复 BUILD_RL_TRAINING=OFF。
构建可用不代表分类PPO、旧play的评估隔离或真实引擎恢复已正确。

## 方案选择与边界

1. 直接把旧Gaussian接simple115并继续clamp：拒绝，违反动作分布目标。
2. 为当前RLtools runner/PPO/config/persist定制categorical分支：可行，但
   活跃路径在多处绑定mean/log_std、Gaussian导数、输出维度和TAR schema，
   同时仍需替换GAE和真实engine owner。直接改vendor会影响既有模型及其他
   continuous环境，不采用该路径作为本次交付边界。
3. **选择项目独立的CPU categorical PPO模块**，直接调用共享
   `football::training::NativeTrainingEnv`。使用C++23标准库小型MLP、明确的
   analytic backprop/Adam及独立codec；既有RLtools路径和vendor保持原语义。
   模块不依赖Python、GPU、BLAS或新增框架；测试的NumPy参考使用已有依赖。

新增模块不是更换算法。成本是需要严格验证自有loss/backprop/Adam，且不
宣称具备RLtools所有设备优化。相应数学、有限值、恢复和真实更新检查是
NT-4.3/4.4硬性验收，不以“可运行”代替。将来若改为大框架/GPU或其他算法，
应另作影响决策；本方案无需新增外部依赖或重新申请既有实现/提交授权。

## NT-4.2 策略/环境合同

- 输入严格绑定 NativeTrainingEnv 的 rows×columns：1..11个同队受控玩家，
  columns=115或stacked460，simple115/115v2布局身份不同，模型不得静默混用。
- 基线为固定拓扑：flatten全部controlled rows → 最多64个tanh hidden units →
  每玩家K个logits及一个team scalar value head。默认hidden64，参数为float64，
  observation为已有float32；无在线observation standardization，避免遗漏其
  checkpoint状态。后续拓扑/normalization改动必须版本化。
- K=19(default)或20(v2)，动作是native action-set index，按controller row
  次序给所有受控玩家；不重选最近球员，也不直接发送legacy GameAction编号。
- 概率用max-shifted logsumexp/softmax，每玩家inverse-CDF抽样或确定性argmax。
  联合分布为给定共同观测下各玩家categorical的乘积：joint log-prob和entropy
  都是玩家求和。PPO ratio以一个joint transition为单位，不偷偷改成逐agent
  ratio。reward用native per-agent reward的team mean，score仍保留原含义。
- 训练/评估/episode seeds显式，使用版本化确定性随机流；模型初始化、动作
  sampling、shuffle及episode分配的所有RNG state必须纳入checkpoint。
- C++调用者提供ScenarioConfig；native CLI的有限builtin scenario集合必须
  明确记录，不假称可解释任意Python scenario。Cadence、结束规则、左右队
  处理和scoring/checkpoints全部交给已有共享env，不重复实现物理/奖励。
- NT-4.2只验收策略推理/抽样接入、真实单/多player和两action-set语义；
  没有PPO update时不得声称已经学习。

## NT-4.3 PPO 数学与更新合同

每个rollout保存旧policy version下的 observation、joint actions、old joint
log-prob、old value、team reward、final next-observation/value和两种结束标志。
不允许混合多个policy version的数据进行同一次on-policy更新。

```
delta_t = reward_t + gamma * (terminated_t ? 0 : V(final_next_obs_t)) - V(obs_t)
adv_t   = delta_t + gamma * lambda * (terminated_t || truncated_t ? 0 : adv_(t+1))
return_t = adv_t + old_value_t
ratio_t = exp(new_joint_log_prob_t - old_joint_log_prob_t)
loss_t  = -min(ratio_t*adv_t, clamp(ratio_t,1-eps,1+eps)*adv_t)
          + value_coef * 0.5 * (new_value_t-return_t)^2
          - entropy_coef * sum_player_categorical_entropy_t
```

Rollout末端未终止时仍bootstrap最终观测；horizon truncate只切断跨reset的
GAE递归，不把TD error清零。terminal则bootstrap0，且不接下一episode的
advantage。固定rollout的advantage做population标准差归一化（epsilon明确），
old values/log-probs/returns在各epoch内保持不变。

基线采用Adam（m/v、step、bias correction、epsilon明确）、固定epoch/minibatch
及确定性shuffle、global gradient norm clipping。value loss先不引入额外value
clipping，KL/clip fraction/entropy/value loss/gradient norm作为诊断，不假称
PPO形式自动保证单调改进。每个rollout最多256个joint transitions，epoch和
minibatch均有显式上限；拒绝非法shape、越界action、NaN/Inf logits/loss/
gradient/model state，不能通过静默clamp坏数值掩盖失败。

必须验证categorical概率归一化、shift不变、log-prob/entropy及导数；正/负
advantage及clip边界两侧；terminal/truncate/live GAE；MLP及combined loss的
finite difference与独立NumPy参考；Adam早期步和bias correction。数学参考
不得只复制C++实现。真正更新后parameter delta必须非零且值有限。

## 新 checkpoint 与评估合同

- 独立magic/版本、网络尺寸/布局/action-set、算法hyperparameters和engine
  build/resource/ABI身份；不能读取旧TAR当categorical模型或改变旧格式含义。
- 保存全部parameter、Adam m/v/step、policy/update counters、全部RNG、episode
  ID/seed/lifecycle、当前完整NativeTrainingEnv FTRN snapshot和current observation。
  无normalizer或recurrent state的基线要明确。最大文件32MiB且内部计数有界。
- 初版只在**完整update边界**存取，rollout buffer为空。不是减少checkpoint
  内容：该边界没有待处理的on-policy样本；若将来允许mid-rollout，必须扩展
  格式保存buffer和old-policy元数据。restore先验证/准备learner全部对象，
  env用已有transactional set_state，成功后一起提交；失败保留原target状态。
- 文件写入使用同目录temp、flush/fsync、atomic replace，支持格式/截断/超限/
  错误schema拒绝。模型训练checkpoint和inference-only导出用途分开。
- 评估为单独env和RNG、冻结weights的inference；不调用update/shuffle，不
  改训练env、训练RNG或optimizer。需用参数/状态hash证明隔离。
- NT-4.4至少固定多个seed完成真实update、evaluation和checkpoint续训；
  恢复后后续动作/reward/parameter/optimizer/RNG及完整checkpoint与未中断
  baseline一致。报告random/native built-in AI baseline及训练指标，不把有限
  次更新或高吞吐宣称为学会足球。评估策略（sample/argmax）、episode长度和
  所有seed必须明确。

## 证据范围与后续门禁

Graph Verify tier，root-work_space-football。MCP在template/macro-heavy头文件
有parse_partial，函数查询多只返回namespace wrapper；已直接读审相关
声明、实现与所有material missed ranges，并归档13份完整源码。coverage generation
2026-10-14T21:10:28Z / 21:14:12Z；不使用图absence证明全库无categorical。
实际探针补强了Gaussian和截断GAE的结论；checkpoint/global-owner缺口和
legacy play update路径来自明确源码，不声称已做旧模型收敛/恢复实验。

NT-4.2–4.4实现后必须进行S4全局review，重点是数学梯度、joint likelihood、
终态bootstrap、RNG/optimizer/environment恢复和评估隔离。S5再验证CI、wheel、
纯C++仓库外运行与平台矩阵。长期目标仍active。
