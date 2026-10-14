# FPPO v1 learner checkpoint layout

2026-10-15。实现入口为 `engine/src/training/ppo_learner.cpp`；算法语义见
PPO_DECISION.md，环境FTRN格式见SNAPSHOT.md。本文只描述当前已实现的
complete-update-boundary状态，不包含待更新rollout或inference-only模型。

## Envelope

所有整数字段little-endian；f32/f64保存IEEE-754原始bits。实际native环境
仍要求相同build/resources/ABI，格式本身不承诺跨build迁移。

| offset | 长度 | 字段 |
|---|---|---|
| 0 | 4 | ASCII FPPO |
| 4 | 4 | checkpoint version=1 |
| 8 | 4 | payload bytes，须恰好等于file size-44 |
| 12 | 32 | SHA256(payload)，原始32-byte digest |
| 44 | payload bytes | 以下顺序的payload |

总文件最多32MiB。magic/version/length单独检查，checksum用于损坏检测，
不是签名或鉴权。任何尾随字节均拒绝。

## Payload 顺序

bool一律u32且仅接受0/1；blob为u32 length+原始bytes，length必须非零且
不超过对应上限。参数和obs都是固定派生长度，不信任文件提供的任意长度。

1. u32 algorithm schema=1、u32 categorical policy version=1、u32 RNG version=1。
2. PolicySpec五个u32：players、features、hidden、fixed_positions、builtin_ai_action。
   players1..11，features115/460，hidden1..64；actions由bool派生19/20。
3. 十个f64：gamma、lambda、clip、value_coefficient、entropy_coefficient、
   learning_rate、beta1、beta2、adam_epsilon、max_gradient_norm。
   随后三个u32：epochs、minibatch、normalize_advantage。
4. root seed u64；cadence、episode_limit、checkpoint_rewards三个u32。
5. base ScenarioIdentity blob、current ScenarioIdentity blob，各最多4096bytes。
   ScenarioIdentity v1包含所有显式scenario/formation初始值，不保存mutable
   caches或struct padding。current只能在base基础上改变engine random seed。
6. 四个u64：policy version、total transitions、current episode ID、next episode ID。
   随后episode steps u32、episode return f64。
7. 三个u64 live SplitMix64 states：sampling、shuffle、episode-seed streams。
   权重初始化stream仅在构造时使用，其结果已完整保存为parameters。
8. parameter count u32；依次parameters、Adam first moments、Adam second
   moments，三组各count个f64；随后Adam step u64。
9. 完整native FTRN blob，限制为现有training snapshot预算（包括其envelope）。
10. observation count u32，必须等于players×features；随后该数量f32，row-major。
11. terminated、truncated两个u32；payload必须结束。

参数顺序沿用categorical_policy.hpp：input weights[hidden,input]、hidden bias、
output weights[players*actions+1,hidden]、output bias，最后output为team value。
最大338269个parameter，三组float64数组约8.12MB；文件预算还包括完整env
和duplicated observation，不省略optimizer或RNG以满足上限。

## 校验与事务

读入后先验证envelope、exact config/root seed/hyperparameters/scene身份、
所有finite数值、参数数量、Adam second moments非负、counter关系和lifecycle。
Counter上限1e12；next_episode=current_episode+1，current_episode不大于
total transitions，episode steps不超过horizon/total。Update count与采样总数
及epoch/minibatch可产生的Adam step范围一致；zero-update状态的moments为0。

terminated和truncated不能同时true；到horizon但未terminal时必须truncated。
零episode step不得带结束标志或非零return。FTRN native-ready与terminal对应；
horizon允许native内核仍live而adapter需要reset。

所有learner对象与一个独立staging NativePolicyEnvironment先准备好。staging
reset saved current scene/seed，再调用现有transactional FTRN restore，读取
不推进物理/stack的current observation，精确比较duplicated float32数组，并
确认模型能有限地forward。成功后以no-throw move/swap提交weights、moments、
RNG、env、scene和counters；任何早期或晚期失败保持原target完整状态不变。

文件层复用SaveCheckpointFile/ReadCheckpointFile，限制32MiB：regular files、
no-follow/nonblocking read、same-dir temporary、flush/fsync/atomic replace。
Before-publication错误保留旧文件；after-publication错误可能留下完整新文件。
当前为Linux/POSIX验收，不宣称Windows/macOS文件语义已经验证。

## 明确未包含的状态

初版只允许initial zero-update和完整update边界，没有pending on-policy
rollout需要保存；不允许mid-rollout snapshot。基线没有normalizer、recurrent
hidden state或GPU状态。UI/diagnostic timers、外部callbacks和评估env不影响
未来train，不纳入格式。若增加这些影响训练的状态，必须先升级格式并补恢复
对照；不得直接沿用v1并声称完整恢复。
