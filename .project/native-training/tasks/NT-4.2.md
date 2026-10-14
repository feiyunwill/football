# NT-4.2 — 原生 categorical 策略与共享环境动作接入

2026-10-15。按PPO_DECISION实现推理/抽样接口，本任务没有PPO update或learner
checkpoint，也不宣称已经学习。新代码与旧Gaussian入口/vendor分离。

## 实现边界

- `CategoricalPolicy`：PolicySpec锁定1..11players、115/460features、compact/
  fixed布局、19/20actions及1..64hidden。Joint observation flatten → tanh →
  每player categorical logits和team scalar value；float64 parameters/math、
  float32 observations；无在线normalization。初始化和抽样RNG独立。
- `CategoricalDistribution`：max-shift logsumexp、log-prob/entropy、inverse CDF
  或argmax。联合log-prob/entropy按player求和，tie选首index；underflow bins
  不被CDF round-off意外选中。拒绝shape/action/非有限值/算术overflow。
- `PolicyRng` v1：SplitMix64+固定53-bit uniform映射，state get/set；固定gold
  vector验证，seeded draws可重放。deterministic argmax不消耗RNG。
- `NativePolicyEnvironment`：拥有一个匹配的NativeTrainingEnv，ScenarioConfig
  和cadence由caller给定；控制顺序和action index直接遵守既有env，不选最近
  player、不发送legacy GameAction编号、不另写奖励/物理。返回copied pre/
  post observation、joint decision、per-agent/score及team mean reward。
  Team mean用float64累加，Gym float32 mean允许rounding差异。
- 身份/推理失败不改变env/RNG；engine或post-output失败关闭adapter；RNG
  仅在step成功后commit。真实terminal优先于caller horizon，二者都需显式
  reset。创建thread/process拥有adapter，fork/错线程使用拒绝。
- 两个standalone static libs不加入simulation core/Python binding。CMake
  登记targets/header/runtime output，native_policy_rollout示例仅inference，
  支持seed/player/step，固定FrameDefaultScenario、left/default/115v2/cadence10。
  它的engine seed是root seed modulo2000000001，不冒称Gym PCG64场景发现。

## 合约与验证

`categorical_policy_contract`：已验证3分类解析概率/logP/entropy、joint分布、
logit shift invariance、20000次固定seed frequency/replay、underflow、NaN/
Inf/shape/action拒绝、最大11×460模型、参数替换失败保留原模型。
NumPy参考独立重构矩阵/tanh/softmax，逐值验证真实C++输出和value/logP/
entropy。只验证forward；analytic backprop、loss和Adam验收留给NT-4.3。

`engine_native_policy_contract`：32组合（1/11人×左/右×default/v2×两layout×
plain/stacked），288真实transitions，逐值与直接NativeTrainingEnv比较pre/
post observation、actions、rewards、terminal、score和canonical kernel bytes。
另检查wrong-layout/count拒绝、horizon/terminal/reset、engine状态与sampling
RNG保持、finite但导致forward overflow的参数、wrong thread及fork拒绝。

Standalone policy ASan/UBSan/LSan证据：
`evidence/nt-4.2-policy-sanitized-20261015-a/report.json` passed=true；实际
library编译flags和ldd证明instrumentation。仅覆盖math/buffers，不冒称覆盖
整个engine或native adapter sanitizer。

最终完整构建/集成证据：`evidence/nt-4.2-integration-20261015-a/report.json`。
验证器将新的NumPy参考、两个C++ contracts、11player rollout和无Python
linkage纳入现有65项Python/四个C++合同路径。结果与source manifest以报告
为准。构建C++23、isolated、--parallel 1；原native/Gym和snapshot继续回归。

最终 passed=true：66项Python测试（75.025s）、六个C++ contracts、11player
inference rollout及native无Python链接检查通过。完整集成与policy sanitizer
的source fingerprint一致：
`0cf10426b7b9bb0ce6a8d3243f4d997406328a3d8ab2d1f785b0ebdd9345ae27`，1213项。

提交前修正了engine main.hpp所声明的main(int,char**)签名冲突，以及明确
aggregate default initialization以消除ObservationBuffer explicit ctor告警。
这两项是本任务开发中的修正，不把早期编译失败当作旧项目缺陷。

Graph Verify：project root-work_space-football，已有接口coverage generation
2026-10-14T21:21:49Z，新文件21:31:59Z；material paths metadata_match且无
记录缺口。已读审相关源码，coverage不代表穷尽。

下一任务NT-4.3：实现决策规定的categorical PPO loss/GAE/backprop/Adam和
完整update-boundary checkpoint，进行独立数值与恢复对照；完成NT-4.4后
进行S4全局review，长期目标保持active。
