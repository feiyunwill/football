# AI 触球修复与网络时序诊断 — 2026-09-14

本轮沿 ms-22.1（手感）、ms-23.1（网络）、ms-25.1（AI）的既有计划推进。已正式修复 Humanoid::NeedTouch 的速度判断，并把真实控球动画回归加入固定输入和完整架构检查。产品验收仍未完成，原 UDP 缺口和性能失败保留。

实现：原分支把“outgoing_velocity != idle”的布尔值传给速度分档函数；0 和 1 都低于 1.8 的空闲阈值，因此移动分支恒不触发。现在先对真实浮点速度分档，再比较速度类别。其余控球、来球速度、方向和偏差条件保留。旧代码按仓库规则注明日期与原因后保留为注释。调用链为 Humanoid::Process → SelectAnim → NeedTouch，只有 BallControl 选择使用该方法。

[实际实现](../../engine/src/onthepitch/player/humanoid/humanoid.cpp)；
[真实 GameEnv 回归](../../engine/tests/engine_ai_touch_contract.cpp)；
[固定输入检查](../checks/input_contract.py)；
[完整架构检查](../checks/architecture_regression.py)。

三个种子为 42、43、20260914；每个加载 1452 个项目自带动画，从中筛选实际用于控球的 90 个。静止、盘带、行走、冲刺类别分别为 28、26、18、18。旧实现漏判的移动控球动画分别为 6、6、10，共 22 个；候选修复均判定需要触球。每个种子仍保留 8 个无需反复触球的静止控球动画。用例还覆盖启动移动、空闲阈值、快速来球、查询不修改状态以及完整快照恢复。测试通过继承开放基类成员指针访问真实对象，没有把基类对象强转为派生对象，没有改变生产类的访问权限或布局。

独立候选已在 Release/ASan+UBSan 下验证（579 断言/构建，泄漏检测开启）；正式用例增加资源规模断言后为 586 断言/构建。候选引擎对既有 512 帧比赛前缀、57 帧死球过渡和 AI 恢复检查也通过。这里仅声明已验证的输入序列；不据此承诺所有旧版本回放或混合版本客户端兼容。

[旧实现失败与候选结果](../optimization/benchmarks/native-ai-touch-contract-20260914-b/report.json)；
[初步候选与历史回放](../optimization/benchmarks/native-ai-touch-prototype-20260914-b/report.json)；
[正式变更、旧源码与 42 个旧产物备份](../optimization/benchmarks/native-ai-touch-integration-20260914-a/canonical-changes.json)。

网络诊断使用行为不变的客户端副本，在真实 X11/SDL 输入、真实 TCP/UDP 会话中记录每线程 CPU 时间、墙钟时间、锁等待与发布帧号。新增时序日志按线程缓冲写入，避免共用日志锁。诊断保持原输入窗口和断言，只改变观察范围为 TCP、UDP 两个用例，且在首例失败后仍采集第二例。

| 观察量 | TCP | UDP |
| --- | ---: | ---: |
| 连续按住区间的非零权威帧 | 69/69 | 68/68 |
| 发布帧号缺口 | 0 | 0 |
| 网络工作耗时 p95 / 最大值 | 0.236 / 17.244 ms | 0.155 / 9.410 ms |
| 4ms 等待的超时唤醒 p95 / 最大值 | 3.152 / 17.708 ms | 2.846 / 11.009 ms |
| 传输状态锁最大等待 | 9.936 ms | 5.519 ms |
| IO 分派锁最大等待 | 14.848 ms | 2.545 ms |
| 采样缓冲锁最大等待 | 0.685 ms | 4.365 ms |
| 实测发布领先上限 | 3 帧 | 3 帧 |

本次未复现旧固定门禁的 UDP 第 200、201 帧缺口，不能确认其根因或宣布修复。精确分析修正了中途按最长总耗时样本读取的粗略锁等待值；上表使用各锁全部记录中的最大等待。网络锁内的 VerifyHash 只进行已存哈希查表比较，不执行昂贵引擎哈希计算。等待唤醒确有抖动，但这些观察不足以解释原失败。软件渲染 p95 为 TCP 121.93 ms、UDP 142.44 ms，仍不符合产品性能目标；单次响应也不构成 50ms p95 手感验收。

[原始观察与执行清单](../optimization/benchmarks/native-pump-lock-observe-20260913-a/x11/windows/report.json)；
[时序分析脚本与结果](../optimization/benchmarks/native-pump-lock-review-20260914-a/analysis.json)；
[保留的 UDP 缺口证据](../optimization/benchmarks/native-publication-bot-current-review-20260913-a/gate-udp-held-gap.json)。

试验失败全部保留：最初测试在 start_game 后尚未推进逻辑，缺少 MentalImage，崩溃已由 GDB 定位；修正为正常推进一帧。增强用例曾误把 SetMomentum 的预测缓存失效计为查询修改状态，现先检查查询纯度，再单独做快速来球与完整快照恢复。它们均为测试准备问题，没有放宽行为断言，也没有删除失败记录。

正式回归已经完成，整条驱动退出 0，耗时 1900.56 秒，没有新增产品回归失败。完整输入门禁 36 项检查、2,989,298 条断言通过，独立游戏/TCP/UDP 实际窗口操作通过；完整架构回归 19 项检查、1,591,402 条断言通过，覆盖 154 个 ASan/UBSan 编译单元，开启泄漏检测且没有抑制项。多实例的预热 RSS 为 342,642,688 字节，最终为 341,405,696 字节；双图形上下文使用 llvmpipe 软件渲染。

三组已有真实权威输入共 3,089 帧，加本轮保存的 1,035 帧，共 4,124 帧分别在 Release 与 ASan 下重放，全部状态哈希一致。保存的失败 UDP 输入序列也在其中；重放一致不会抹去原来发生过的输入缺口。当前构建再次通过 512 帧前缀、57 帧死球过渡以及 30 帧无选中球员后的 AI 恢复检查。

本轮正式窗口中，独立游戏、TCP、UDP 的单次响应分别为 102.18、117.27、102.45 ms；软件渲染 p95 分别为 146.93、128.29、171.08 ms。固定功能门禁通过，50ms p95 手感和硬件渲染仍未通过验收。严格持续按键区间内，UDP 108.27 ms 渲染与 5 个非零权威帧重叠；这也说明单凭渲染持续约 108 ms，无法解释此前第 200、201 帧的缺口。

[正式结果汇总](../optimization/benchmarks/native-ai-touch-current-review-20260914-a/analysis.json)；
[完整输入门禁](../optimization/benchmarks/native-ai-touch-integration-20260914-a/gate/report.json)；
[架构及历史回放记录](../optimization/benchmarks/native-ai-touch-integration-20260914-a/report.json)；
[渲染与权威帧重叠记录](../optimization/benchmarks/native-ai-touch-current-review-20260914-a/held-render-overlap.json)。

里程碑结构校验通过：56 个节点、31 个检查定义有效；质量系统仍将 ms-19.1 至 ms-26.1 标为 stale，本轮未手工提升状态。后续继续定位实际 UDP 缺口，验证弱网与版本兼容，推进硬件渲染、50ms 手感及战术决策的剩余条件。6 个正式变更、1059 个源码条目、1004 个外部依赖和当前产物由最终证据清单复核；旧 42 个产物保存在正式接入目录中。观察阶段曾使用指向当前构建的库软链接，其运行时版本以当时的产物清单和已保存旧库为准。

补充实现复核：TacticsController 仍把场地中心设为 x=50、对方球门设为 x=100，体力固定为 1，剩余时间实际读取已进行时间；决策权重和按钮未逐次清空，传球候选也没有排除当前球员。分析阶段使用最近球员，而防守/支援使用名单首位球员，且读取显示几何位置。图中构造函数和 Update 的入站调用均为零；对 engine/src、engine/tests 和 engine/ai.cpp 的限定检索同样只找到定义。这不构成全仓所有间接调用不存在的证明，但目前没有找到生产接入依据。task-25.1.1.1/2 应先统一受控球员和逻辑状态，再完成方向、时间、权重重置、动作释放及不传给自己的真实比赛验证，之后接入可审计的生产调用点。

[限定范围与逐项代码依据](../optimization/benchmarks/native-ai-touch-current-review-20260914-a/tactical-followup.json)。
