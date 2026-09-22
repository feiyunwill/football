# 原生输入发布节拍修复

已在正式 TCP、UDP 客户端接入独立输入发布时钟。权威数据批量到达时，发布仍按原生 50Hz 节拍推进，避免仅根据最新接收帧号直接跳过输入。当前完整输入检查通过 2,984,826 条断言、零跳过；正式构建的额外 100ms 权威暂缓测试也通过。产品级延迟、完整弱网与发布验收仍未完成。

## 里程碑、计划与任务

本轮继续 ms-22.1 → plan-22.1.1 → task-22.1.1.1，并推进 ms-23.1 → plan-23.1.1 → task-23.1.1.1。保留所有失败记录；未改变服务器规则、协议、画质、冻结算法或原有检查阈值。质量结构验证为 56 个节点、31 个检查，ms-19.1 至 ms-26.1 均仍为 stale，不手动提升状态。

## 问题与实现

上一轮真实 TCP 观察到输入 504 后直接发送 507：权威 503–505 在一次 read 完成时，旧发布方法只计算最新 target=max(authority_count+1,next_simulation)，没有独立节拍继续提交中间帧。

本轮使用真实客户端、真实服务器与透明转发器，在进行中持续按键区间暂缓服务器到客户端的数据 60ms，客户端输入方向继续转发。旧版 TCP 在故障区间缺少 153、154 帧输入，UDP 缺少 154–156 帧；转发字节保持一致。TCP 另有故障区间外第 137 帧空档，原因不由该对照推断。具体数据见[对照报告](../optimization/benchmarks/native-publication-clock-20260913-a/batch-comparison.json)。

[NativePublicationClock](../../engine/src/frame_sync/native_publication_clock.hpp)以 NativeMatchContract::kHz 定义周期，状态占 32 字节：

- 正常情况下保留原有已知权威帧／预测进度决定的下界，按 20ms 机会继续发布；收到新的权威进度时校准下界。
- 已发布帧号只增不减；重复调用不会采样或发送同一帧。过期本地发布机会不以当前按键回填，只提交当前机会。
- 目标最多为已知 authority_count+15，来自服务器 16 帧窗口的实际约束；达到上界或预测暂时超窗时不消费设备边沿。
- 非法时间、时间倒退及整数耗尽明确拒绝。长期停止收权威数据时会有界停止发布，不能据此宣称任意停顿下仍连续或低延迟。

[NativePublishedHistory](../../engine/src/frame_sync/native_input_publication.hpp)新增 PublishTimed：时间在既有账本锁内获取，两个调用者共享时钟及唯一帧输入；容量检查在采样前完成，预测读取同一份不可变输入。调度候选仅在正常返回后提交。原有 Publish 方法仍供既有接口和合同使用。

[TCP](../../engine/src/frame_sync/integrated_client.cpp)与[UDP](../../engine/src/frame_sync/integrated_client_udp.cpp)的实际 pump_input 已切换到 PublishTimed，继续使用上一轮的主线程 SDL 采样、游戏线程和独立网络线程。新增[永久合同](../../engine/tests/engine_native_publication_clock_contract.cpp)注册于 CMake 和[固定输入检查器](../checks/input_contract.py)，包含独立 TSan 运行。

## 验证

| 验证 | 结果与范围 |
| --- | --- |
| 发布时钟 Release / ASan+UBSan / TSan | 各 30,559 条断言、零跳过；6000 个节拍槽、512 帧双调用者竞争、6 个短按与恢复序列帧 |
| 60ms 暂缓对照 | 旧版两种协议均失败；同源码原型两种协议均通过，中央持续输入区间各 70 个权威帧、零空档 |
| 当前完整输入检查 | 2,984,826 条断言、零跳过；standalone/TCP/UDP 正式窗口全部通过 |
| 门禁实际回放 | TCP 519 + UDP 514 = 1033 个确认帧；Release 与 ASan/UBSan 各 452,569 条断言、40000 个时钟事件 |
| 正式构建 100ms 暂缓 | TCP 69、UDP 71 个中央持续输入权威帧，均零空档；暂缓期间各实际发送 5 个不同输入帧，收到的活动期输入与权威均相同 |
| 100ms 故障回放 | TCP 517 + UDP 506 = 1023 个确认帧；Release 与 ASan/UBSan 各 452,531 条断言、40000 个时钟事件 |

两个当前源码批次共 2056 个确认帧，在 Release、ASan/UBSan 中分别逐帧重放一致，启用 LeakSanitizer。实际窗口验证保留短按、释放、失焦、控制暂停／恢复屏障、重新按下、途中保存、最终保存、渲染状态不变及单次显示条件。

证据入口：[完整门禁](../optimization/benchmarks/native-publication-clock-20260913-a/gate/report.json)、[当前 100ms 故障分析](../optimization/benchmarks/native-publication-batch-current-20260913-a/fault-analysis.json)、[故障回放](../optimization/benchmarks/native-publication-batch-current-20260913-a/replay-report.json)。

## 保留的失败与实际边界

- baseline A 缺少测试脚本的 sys 导入，两个真实服务器退出正常，未启动客户端；修正后另存 baseline B。
- baseline B 正确复现严格持续输入失败。TCP 转发器在客户端结束时记录连接 reset 并 exit=1；故障区间在退出前，字节前缀对照通过。后续转发器只将客户端关闭导致的 reset 作为 EOF，应用检查仍要求客户端正常退出。
- prototype A 的观测库相对链接错误，导致预加载失败、无法观察实际窗口；纯合同及两种原型编译成功，但这批窗口／故障证据无效。prototype B 仅修正观测路径，复用相同原型二进制，完成严格对照。
- 正式检查器插入点首次命中历史 CONTRACTS 注释，内存中的候选未通过 Python 编译，未写入也未启动构建；改为匹配实际定义后启动完整门禁。
- 60ms 原型与当前 100ms 故障均为单方向暂缓／批量交付，未构成完整丢包、双向延迟、重连、观战或权威暂停矩阵。UDP 释放积压数据时可能与新数据交错，实际可靠层负责恢复交付顺序。
- 当前门禁本地／TCP／UDP 响应约 83.795 / 59.918 / 76.658ms；100ms 故障批次约 72.797 / 83.066ms。仍未达到 50ms 产品目标，不能用持续输入通过代替手感验收。

## 下一步与证据身份

下一步核实实际硬件渲染上下文与呈现成本，再继续 GL／SSAO 优化和 50ms 输入到球员／显示验收。本轮只读发现 /dev/dxg、Mesa d3d12 驱动和 WSL D3D12 库存在；这只说明有进一步探测条件，不证明硬件上下文可用。当前窗口证据仍来自 X11 软件渲染。1080p 帧时间 p95≤16.67ms 的硬件验收、完整网络与前置质量链、AI 和发布长测继续推进。

8 个正式变更文件见[源码清单](../optimization/benchmarks/native-publication-clock-20260913-a/changes.json)。当前门禁固定 1054 个源码／资产、37 个二进制和 1004 个依赖，运行前后核对一致；Release/ASan 引擎核心及原始性能基线、冻结算法夹具未变。旧版真实客户端二进制保存在 baseline B/original-products，原始源码变更前版本保存在本轮 before 目录。

[独立收据](../optimization/benchmarks/native-publication-clock-20260913-a/verification.json)包含失败、对照、正式门禁和额外故障回放；full_input_gate_passed=true 仅指本轮固定输入检查，product_acceptance=false。
