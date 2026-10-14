# NT-4.1 — PPO 活跃路径审计与接入决策

2026-10-15。完成范围为现有真实GameEnv入口、其vendoredGaussian PPO/
runner/GAE及core checkpoint路径，不作全RLtools categorical能力的穷尽声明。

决策见 [PPO_DECISION.md](../PPO_DECISION.md)：保留原147-feature Gaussian
入口与模型格式，新增无大型依赖的C++ categorical PPO模块接共享native环境。
离散PPO算法目标不变；网络/联合动作、GAE、loss、Adam、完整update边界
checkpoint、evaluation isolation及后续验收均明确限定。

实证 `evidence/nt-4.1-audit-20261015-b/report.json` passed=true：
13份精确审计源码归档，C++23 CPU probe直接调用真实vendoredGaussian log-prob
和GAE；live/truncated/terminal advantages分别1.97/0/-1。已有真实引擎
rl_football_training target serial build通过且ldd无Python/missing依赖。
configure后恢复BUILD_RL_TRAINING=OFF。未修改production engine/vendor代码。

A轮探针和compile通过，但audit脚本假设legacy exe在bin/，ldd定位失败；
源码CMake确认该target未设置统一runtime output，真实产物在build root。
修复audit脚本并重跑B，保留失败A作为真实开发证据，不宣称old trainer构建失败。

审计发现：旧连续clamp/bin动作、147-feature/reward shaping、强制非terminal
不等于当前numeric native contract；非terminal truncate GAE清零TD error；
checkpoint保存core optimizer/RNG但不包含全局真实engine owner；legacy play
调用training step仍更新weights。新实现的验收明确要求处理这些边界。

Graph查找及coverage先行，macro/template相关partial范围直接读审补证，
完整源文件字节在evidence内；更详细证据范围/限制见决策文档。
本任务没有新PPO实现，不运行无关全引擎测试重复宣称算法正确。

下一任务NT-4.2：版本化policy shape、categorical sample/log-prob/entropy及
NativeTrainingEnv真实策略动作接入。所有update/完整learner恢复属于NT-4.3，
多seed训练/评估/续训证据属于NT-4.4，之后才执行S4全局review。
