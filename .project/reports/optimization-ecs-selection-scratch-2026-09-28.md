# 动画选择缓冲区复用：分配与整场性能复核

归属 ms-21.1 → plan-21.1.1 → task-21.1.1.2。以 `24b09cf` 的 Release 二进制为变更前参考，候选版只修改 `HumanoidBase` 每个球员的动画选择临时结果：主选择与其可能调用的空闲动画回退分别保留 `DataSet` 容量，每次使用前清空。两个缓冲区不属于比赛状态，`ProcessState` 不读取它们。保留启动阶段 `SelectRetainAnim` 的局部缓冲区。

现有完整比赛分配采样器在种子 42/43 的 2,000 个稳态帧中，分别记录到帧内分配从 656,253 降至 482,054、从 674,471 降至 492,607 次，下降 26.5%/27.0%；帧内分配字节从 68,421,236 降至 47,130,528、从 75,299,113 降至 53,904,593。旧版 `AnimCollection::CrudeSelection` 的 174,199/181,864 次分配调用点在候选版热点列表中消失。两种子的仪表化比赛轨迹相同。候选版 Release 编译成功，`engine_animation_query_contract` 通过 30,079 项断言、无跳过。

未插桩的整场比较按每种子 15 对、交错顺序执行，共 60 个独立进程；每对的固定输入、预热状态、检查点及最终状态均一致。候选/参考 CPU 几何均值比：种子 42 为 0.9881，95% bootstrap 区间 0.9688–1.0052；种子 43 为 1.0256，区间 0.9606–1.1300。墙钟结果相近，配对 p99 中位比为 0.9967/0.9934。种子 43 最后一对候选 CPU 为 10.91 秒，参考为 5.89 秒；这是原始样本的一部分，未删改。两个种子的 CPU 改善可信上界均未小于 1，**整场提速未获证明**。

[机器可读摘要](../optimization/evidence/ecs_selection_scratch_20260928.json)保存源码、二进制及归档哈希；[完整配对原始数据](../optimization/evidence/ecs_selection_scratch_20260928_paired.json.gz)、[独立分配采样](../optimization/evidence/ecs_selection_scratch_20260928_profile.json.gz)和[复测脚本](../optimization/evidence/ecs_selection_scratch_probe.py)保留复核路径。

当前源码重新运行了正式质量链：框架与架构里程碑均为 `verified`；正式 11v11 基准也为 `verified`，两种子各 5 个独立进程、各 10,000 个稳态帧，p50 为 2.583/3.090ms，p95 为 3.910/4.665ms，p99 为 4.943/6.266ms，状态哈希在同种子内一致，RSS 最大增长各 40KiB。[当前版完整比赛归档](../optimization/evidence/ecs_selection_scratch_20260928_current_match.json.gz)记录逐帧样本、编译及机器身份。正式 `ecs_performance` 仍因其旧 `/tmp` 基线引擎二进制缺失而在比较前失败，见[正式失败日志](../optimization/evidence/ecs_performance-1790590603384028262.log)。`task-21.1.1.2` 与 ms-21.1 当前均为 `failed`；这次参考版只有变更前当前源码的语义，不能冒充缺失的历史基线。后续应继续定位实际 CPU 热点，并建立可持久复现的正式比较基线。
