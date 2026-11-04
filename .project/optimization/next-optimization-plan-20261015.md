# 下一阶段优化目标与执行计划

日期：2026-10-15。状态：执行中；实际进度与证据见 [执行状态](next-optimization-state.json)。
范围：足球仿真、原生训练、非 GPU 产品质量；GPU 验收沿用现有暂停安排。
本文是后续工作计划，不改写现有 program、state 或历史验收状态。

## 决策依据

- native-training/state.json 记录 S0–S5 complete，说明共享环境、恢复、采样、分类 PPO 和交付链路已建立。
- TRAINING_EXPERIMENTS.md 的每配置 768 步实验验证更新与恢复，未证明学会足球；空门成绩不稳定，11v11 短窗口均未得分。
- PERFORMANCE.md：诊断计时中 engine step 约占 93%–98%；不能把该比例直接用于估算未插桩吞吐。
- tasks/NT-3.2.md 已有内部 CPU 样本，空间递归更新与 Ball::Mirror 是候选关注点；list→deque 候选收益不稳定，已经撤回。下一步应重新核验热点，避免重复该实验。
- optimization/README.md 明确暂停 task-24.1.2.2；PLATFORMS.md 只确认当前 Linux/WSL、CPython 3.14 交付实测，远端 3.11 CI 尚无本轮结果。
- 工作区存在大量既有源码及动画资源修改。基准必须绑定工作区内容及资源指纹，Git HEAD 本身不足以标识被测版本。

以上是仓库记录核对，尚未在本轮重跑验收或性能实验。图索引 generation 为 2026-10-15T02:53:03Z；覆盖元数据为 best-effort，文档结论已直接读取原文。没有进行全库结构穷尽审计。

## GitHub 参考与采用方式

2026-10-15 通过公开 README 核对，按任务相关性选择，不按 star 数排序。实施时记录所参考的具体 commit、文件和许可。

本轮已冻结[上游commit、README链接与公开许可元数据](../native-training/evidence/open-source-references-20261015.json)。
参考限于实验与分析方法；新增工具直接复用本项目现有C++策略和PPO数学代码。

| 参考项目 | 可借鉴做法 | 本项目落地 | 适用边界 |
|---|---|---|---|
| [Google Research Football](https://github.com/google-research/football) | academy 场景、训练示例、回放、基线 | 从空门到带门将射门，再到小规模对抗 | 当前原生 CLI 只有有限场景；新增场景先做环境对照，不直接复用旧 TF1 依赖 |
| [CleanRL](https://github.com/vwxyzjn/cleanrl) | 可读 PPO 实现、种子、曲线、基准与实验追踪 | 核对 PPO 配置语义，保存多种子学习曲线和完整指标 | 保留本项目 joint categorical、恢复和 GAE 合约，不机械复制公式或增加框架 |
| [Gymnasium](https://github.com/Farama-Foundation/Gymnasium) | 标准环境 API、terminated/truncated、环境版本 | 新场景、奖励和观测变化具有独立身份与兼容性测试 | 不把 truncated 当作 terminated；不静默改变既有模型含义 |
| [RLtools](https://github.com/rl-tools/rl-tools) | C++ 训练、设备后端、独立基准 | 分开测量 rollout、推理、更新与端到端训练成本 | 当前 vendored 路径与独立 categorical PPO 差异已有 PPO_DECISION.md；不直接替换，亦不采用示例 fast-math |
| [Tracy](https://github.com/wolfpld/tracy) | CPU/GPU、内存、锁、帧时间分析 | 借鉴阶段划分，必要时可选编译接入 | 先复用已有 gprofng；插桩关闭版用于最终性能验收，GPU 工作仍暂停 |

下列数字均为本计划提出的目标或预算，不是上游项目承诺，也不是本轮测量结果。

## 执行顺序与验收

### O1：建立当前版本的统一基线（P0，预计 1–2 人日）

1. 固定源码、动画及其他资源 manifest、构建参数、编译器、Python/依赖、CPU 和运行方式；保留现有修改归属。
2. 分开记录环境 step、真实 PPO rollout/推理/update、reset、checkpoint、worker IPC 和总墙钟，明确 joint transition 与单玩家 action 的统计单位。
3. 复用已有 quality.py run/verify 和 profile 工具；冻结 1/11 受控玩家 × cadence 2/10、预设动作/反馈闭环矩阵。
4. 每个计时配置至少 8 组配对交错运行，包含进程 CPU、墙钟、p50/p95/p99、RSS、逐步或最终状态 digest。初始化与稳态分别记录。

验收：得到可重放的 baseline manifest、原始样本和阶段分解；确认现有质量证据哪些仍新鲜、哪些需要重验。若 WSL 波动淹没收益，记录环境限制并停止性能归因，先处理测量稳定性。

### O2：证明基础任务具有稳定学习效果（P0，预计 3–5 人日工程工作，训练时间另计）

依赖 O1。

1. 先复核当前 empty_goal 配置、episode horizon、动作集和场景是否适合学习；设置独立训练、调参与最终评估种子集合。
2. 对同一环境比较初始模型、训练模型、uniform random、builtin AI；分别报告 sample 与 argmax，不选择性报告较好结果。
3. 初筛预算为每配置 10^5 joint transitions，最多 3 组预先登记的超参数；择优后以 5 个训练种子运行，每种子最多 10^6 transitions。先估算实测墙钟与存储需求，超出预算则登记部分结果并缩小实验，不无界运行。
4. 最终每个训练种子在同一组至少 200 个未用于调参的 episode seeds 上评估。episode 必须运行到真实终止或事先固定的完整 horizon；单独报告超时。
5. 保存成功率、进球/失球、episode 长度、学习曲线、entropy、KL、clip fraction、value loss、gradient norm、训练耗时和完整配置。
6. 空门通过后，新增或核对带门将射门场景，再进入传射/小规模对抗。每次场景扩展先补 Python/C++ 语义、镜像和恢复测试。

第一关目标：空门 argmax 成功率跨 5 个训练种子的均值 ≥90%，每个种子 ≥80%；相对初始模型和随机基线的成功率提升，其配对、分层 bootstrap 95% 区间下界 >0。分别报告训练种子和评估 episode 的不确定性，不能把所有 episode 当成独立训练重复。若随机基线已接近满分，则该场景缺乏区分度，记录后改选更有区分度的任务，再冻结新的验收协议。

builtin AI 是参照，不要求第一关超过它。后续任务阈值在看训练结果前登记；11v11 完整比赛成绩属于后续阶段，不用当前短窗口奖励替代胜率。

停止条件：预算耗尽仍无改善，先审查奖励稀疏性、动作/观测、探索及 PPO 诊断，每次只改一个因素。奖励 shaping 单独版本化，最终仍以真实进球与任务成功评估。

### O3：降低引擎内部热点成本（P1，预计 3–5 人日）

依赖 O1。执行与 O2 的计时实验串行，避免争抢 CPU。

1. 复用 gprofng 对当前真实 rollout 采样，核对已有空间更新、Mirror 样本是否仍成立，区分 exclusive/inclusive 和调用次数。
2. 沿图索引与精确源码核验候选读写、镜像、回放与状态所有权；对 partial/missing coverage 直接读源码补证。
3. 每轮只实现一个候选，例如去除经证明重复的空间计算、复用临时缓冲、缩小不必要遍历。不得跳过会影响物理、AI 或状态序列的工作。
4. 原版/候选使用相同构建与工作负载；功能对照、短基准、长局、内存和恢复按影响范围逐级执行。

保留目标：预先指定的主工作负载 CPU/transition 中位成本下降 ≥10%，配对 95% 区间支持正收益；其余矩阵中位成本回退不超过 3%，并检查尾延迟。波动导致无法判断则增加至预先约定的样本预算，仍不确定就不保留。目标值不能用于放宽现有门禁。

硬性验收：同输入观测、奖励、终止和状态 digest 一致，回放/恢复正确；现有逻辑 p99 <50ms 与 RSS 预算继续生效。不得用 fast-math 或改变求和顺序换取确定性损失。

### O4：提高真实训练的多进程效率（P1，预计 2–4 人日）

依赖 O1、O2 的固定真实策略配置；若使用 O3 候选，先完成其验收。

1. 已有 1/2/4 worker heuristic 基线保留；新增真实 PPO inference/update 的端到端基准，不将 heuristic 吞吐冒称训练吞吐。
2. 保持同一 policy version 的 on-policy rollout，比较相同总 transitions 与训练配置，禁止通过改变样本量、算法或更新次数制造加速。
3. 分析 IPC、parent 推理、序列化、reset 和慢 worker；再决定是否需要共享内存或批推理。

目标：资源允许时，4 worker 相对 1 worker 的真实端到端训练吞吐 ≥2 倍，单 worker 无 >3% 稳定回退；不达标时提交瓶颈结论，不强行改为异步采样。固定任务/种子映射，逐 episode 轨迹一致；训练汇总顺序固定，并验证各自恢复可重复。parent/worker/tracker 的 RSS、FD、PID、退出与超时清理均纳入检查。

### O5：形成可验证的交付矩阵（P1，预计 2–3 人日）

1. 从现有 native-training CI 配置出发，优先补齐 Ubuntu/CPython 3.11 与当前 3.14 的干净构建、wheel 安装、资源定位、短训练、续训和冻结评估。
2. 轻量正确性检查用于 PR；长训练与性能运行使用固定环境、独立日志与产物，避免共享 CI runner 的波动成为性能结论。
3. 发布前实际运行原生包在仓库外的 probe；所有声明绑定实际产物、平台、依赖及资源身份。

验收：保留真实 CI 运行与产物报告；无远端执行证据时保持“待验证”。Windows/macOS 和 manylinux 扩展另立任务；不以本机成功推断跨平台成功。既有产品质量链仍按自身依赖执行。

### O6：恢复 GPU 验收与完整产品发布（P2，条件触发）

仅在当前暂停安排结束后执行。先重建目标 GPU、驱动、实际窗口与 1080p 基线，分开测 CPU、GPU passes、提交与 swap 等待；然后一次优化一个 pass 并执行图像对照。维持原 16.67ms 门槛，完成 task-24.1.2.2 后重跑渲染及最终产品依赖链。训练路线完成不能自动关闭产品发布阻断。

## 首轮排程与交付

- 第 1 周：O1 → O2 初筛与问题诊断；产出当前基线及第一版学习曲线。
- 第 2 周：O2 多种子评估；穿插串行执行 O3 的一个热点候选。先完成在途测量再修改其输入。
- 第 3 周：根据已验证瓶颈推进 O4，并完成 O5 实际交付验证。
- O6 不排入当前三周承诺。以上是工程估算，训练与机器可用性可能延长周期。

每个 O 项执行前拆为独立子任务，登记依赖、输入、预算和命令；每次只推进一个实现子任务。每阶段交付 manifest、commands、raw samples、report、复现说明和 review。失败、撤回与预算耗尽均保留原始证据。

总体完成条件：基础任务稳定学习、一个经验证的性能改进或明确的无收益结论、真实训练并行效率报告、目标平台实际交付证据，以及原有正确性/恢复/内存门禁无回退。开始执行时先做 O1，不重复宣称已完成的 S0–S5 为新成果。
