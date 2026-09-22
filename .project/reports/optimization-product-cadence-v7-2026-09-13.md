# Python 产品比赛 v7：50Hz 节拍实施

2026-09-13。本轮沿 `ms-22.1 → plan-22.1.1 → task-22.1.1.2` 推进；涉及 `task-23.1.1.1` 网络准入和 `task-24.1.2.1` 图形链路。Python 比赛层已由10Hz／10物理步切换为50Hz／2物理步，并通过当前 Release 引擎上的真实比赛与回放回归。整体产品优化仍未完成。

## 实现

| 边界 | 当前行为与代码 |
| --- | --- |
| 节拍 | [MatchCadence](../../gfootball/frame_sync/match_cadence.py) 严格接受50/50/2/10000；3000帧场景换算15000帧，并校验有符号范围 |
| 原生初始化 | [server_runtime](../../gfootball/frame_sync/server_runtime.py) 为明确选择比赛契约的工厂换算时长；通用旧工厂保留10步和原时长 |
| 身份 | [match_identity](../../gfootball/frame_sync/match_identity.py) 的真实逻辑／显示共用物理2步与cadence50身份 |
| 握手与恢复 | [match_bootstrap](../../gfootball/frame_sync/match_bootstrap.py) 使用版本7／FMATCH7；原点、Ready和重连都验证一致契约 |
| 存档和回放 | [match_archive](../../gfootball/frame_sync/match_archive.py) checkpoint v3必需cadence；回放50Hz与20ms时间戳；旧存档在解码／建引擎前失败 |
| 调度 | [frame_pacing](../../gfootball/frame_sync/frame_pacing.py) 保留通用10Hz默认；比赛循环显式使用50Hz |
| 权威收集 | [multiplayer_transport](../../gfootball/frame_sync/multiplayer_transport.py) 默认收集预算20ms；[HostedMatch](../../gfootball/frame_sync/multiplayer_runtime.py) 使用这一预算 |
| AI 接管 | [BotTakeoverManager](../../gfootball/frame_sync/server.py) 按权威频率换算3／4秒冷却，避免采样率改变行为冷却时长 |

永久新增 [test_product_cadence.py](../../gfootball/frame_sync/test_product_cadence.py)，8项契约／真实传输测试及2项真实原生测试已加入正常 [frame_replay_probe](../checks/frame_replay_probe.py) 的必需组。实际原生测试在比赛进入进行中状态后保存原点，重放50帧完整输入并逐帧比较规范摘要；另验证缩短场景换算为15帧后的自然终止和中途恢复。更换节拍后的开场等待上限保持原有10秒模拟时间，未放宽墙钟延迟或性能门槛。

## 实际执行

最终阶段 [python-product-cadence-20260913-d](../optimization/benchmarks/python-product-cadence-20260913-d/report.json) 的驱动PID2588874／start_ticks35120462，exit=0，finished=1789280728.2051957。

| 检查 | 实际结果 | 命令墙钟耗时 |
| --- | --- | --- |
| 新增产品节拍组独立执行 | 10项通过 | 6.285s |
| [比赛、联机、图形与原生回放](../optimization/benchmarks/python-product-cadence-20260913-d/match/report.json) | 402项通过，零跳过 | 157.158s |
| [旧接口与原生服务器](../optimization/benchmarks/python-product-cadence-20260913-d/legacy-server/report.json) | 123项通过，零跳过 | 6.544s |

402项包含上述10项，不重复累计。完整组没有遗留受管线程、子进程或文件锁，也没有资源警告／未处理协程等失败标记。它包含真实SDL/OpenGL、暂停HUD、骨骼／球／相机插值像素、实际TCP／UDP、恢复、结束确认以及持久回放。此次执行使用Release核心；不宣称已完成v7全链路ASan验收或物理输入延迟测量。

- 总报告SHA256：`5f5af72e54d2ce4db3ccdd8af1d2874e4ca87cde080c36a45bc1fb2cdf34e65a`。
- 比赛报告SHA256：`b510c4efe9cd9370c639808533376969b13a271ab2dabb16a9072f784a8179e1`。
- 旧接口报告SHA256：`31d36228e2632e569faabc9f4543f0f4837d432c367d0c3d39735bc67986ae2e`。
- 当前实际映射的核心：`/tmp/football-optimization-native/libfootball_engine.so`，SHA256 `2836c626ddb31ea3f38b7268ba7845c740eb20dde2f7011e095a3de93ba4730b`。
- Python绑定仍为已安装绑定，SHA256 `7fbd727facffe81f5f3326222732df36916016d5543b8ed4602875bc296bb80c`；数据来自当前 `engine/data`，字体路径记录在报告中。

## 发现并修复的证据错误

[native_runtime_identity](../checks/native_runtime_identity.py) 原先按安装目录查找引擎文件，LD_LIBRARY_PATH选择其他核心时会记录错误身份。Linux现在复用已校验设备／inode的进程映射解析器，记录真正映射的绑定和核心；其他平台明确标为仅文件观察。

[两个真实子进程的差分证据](../optimization/benchmarks/python-product-cadence-20260913-d/identity-differential.json) 使用同一绑定，分别加载安装核心0965455…与当前核心2836c626…，记录器均返回实际映射路径和对应哈希。该报告SHA256为 `8e65a18a6639383ef2d09b3e5ea18ac7e23a42c4d60a5fdb7b561d8e64136dbd`。此前A/B/C阶段没有被改写为当前引擎的通过证据。

## 失败记录保留

- [A](../optimization/benchmarks/python-product-cadence-20260913-a/run.log)：驱动误用了命令工具参数，未启动测试子进程。
- [B](../optimization/benchmarks/python-product-cadence-20260913-b/execution/product-contracts.log)：10项中2项测试假设失败；100帧在新节拍仅2秒，尚未走完开场；原始InputBuffer不负责客户端重发历史。分别保持原10秒模拟时间上限、改为验证一次消费语义。
- [C](../optimization/benchmarks/python-product-cadence-20260913-c/match/report.json)：402项中1项失败，资源身份测试把配置恢复成旧10步，导致提前在配置校验处失败；改回v7的2步再独立校验资源变化。其原生测试实际加载安装核心，不能代替D对当前核心的验证。

修改前文件、命令、输出和源文件哈希均保留在各阶段。[最终校验清单](../optimization/benchmarks/python-product-cadence-20260913-d/verification.json)覆盖证据、当前实现和实际运行库，由独立校验脚本逐项复核。

## 当前任务状态与下一步

[正常Program状态快照](../optimization/benchmarks/python-product-cadence-20260913-d/program-states.json)验证通过；input_contract=pending、fixed_timestep=planned，相关任务及ms21..26仍为stale。没有通过手写质量记录提升任务状态。本轮源码变更也使此前输入验收证据成为历史版本证据。

下一步继续原生三个产品入口的节拍／版本／回放元数据升级、服务端绝对收集截止时刻、真实设备到球员响应、双客户端和网络故障下的50Hz测量，再刷新完整前置验收链。C++原生v2／10Hz与Python比赛v7仍属不同协议族，不能仅修改一个共享版本常量来互通。

原始性能基线、C++默认场景、短／长性能夹具、AI对照夹具和核心二进制均未被本轮Python节拍修改覆盖。使用方法见[当前v7契约](../../gfootball/doc/match_cadence_v7.md)。
