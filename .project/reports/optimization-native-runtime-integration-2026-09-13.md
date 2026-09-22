# 原生产品入口、权威输入与展示集成 — 2026-09-13

已将共享输入、按帧提交、展示调度和回放保存接入单机、TCP、UDP 三个正式入口，并修复了实际联机中“本地预测有动作、服务器确认输入全为零”的缺陷。当前通过的是以下明确范围的局部验收；整个产品优化阶段尚未完成。

| 里程碑 → 计划 → 任务 | 已落地的实现与证据 | 尚需完成 |
| --- | --- | --- |
| ms-22.1 → plan-22.1.1 → task-22.1.1.1 | 三入口统一完整输入，支持同时按键、松键、短按缓存、焦点与恢复屏障；实际 XTEST 输入进入引擎 | 正式输入门禁整合与刷新 |
| ms-22.1 → plan-22.1.1 → task-22.1.1.2 | 输入只在实际待提交帧消费一次，保留有界历史；共享绝对时钟通过独立调度对照 | 产品节拍与跨语言协议协商 |
| ms-22.1 → plan-22.1.2 → task-22.1.2.1 | 展示所有权覆盖纠正回滚；实际单机暂停不推进逻辑但持续绘制；每次比赛渲染仅换帧一次 | 实际回滚图像连续性及更完整暂停矩阵 |
| ms-23.1 → plan-23.1.1 → task-23.1.1.1 | 实际引擎 TCP／UDP 服务器接入固定容量未来输入缓存；真实确认帧保留非零输入 | 多客户端、乱序、慢端、WAN 与其他服务器实现覆盖 |
| ms-24.1 → plan-24.1.2 → task-24.1.2.1 | 三入口保存并检查真实 SDL 帧缓冲；渲染前后逻辑摘要不变 | GPU 性能、资源故障与产品画面验收 |

## 实现

- [共享入口循环](../../engine/src/frame_sync/native_client_loop.hpp)与[时钟、窗口输入](../../engine/src/frame_sync/native_loop.hpp)：4ms 输入／网络轮询机会，逻辑和展示分别调度；采用绝对纳秒截止时间，60Hz 不再按 16ms 取整。长耗时会错过墙钟机会，但不会跳过模拟帧号。当前逻辑仍为 10Hz。
- [输入缓冲](../../engine/src/frame_sync/native_input_buffer.hpp)、[本地帧历史](../../engine/src/frame_sync/local_input_history.hpp)和[模拟器](../../engine/src/frame_sync/frame_simulation.hpp)：权威追帧后确定实际输入帧；等待或预测关闭时仍可提交输入；同一帧不重复消耗短按或重新取样。TCP／UDP 共用该路径。
- [展示所有者](../../engine/src/frame_sync/native_presentation.hpp)：逻辑端点、纠正前的可见姿态、暂停恢复与渲染时钟由同一对象管理。客户端成员顺序保证该对象比捕获它的引擎回调活得更久。
- [单机入口](../../engine/src/frame_sync/standalone_game.cpp)：完整 SlotInput 一次提交，显式松键，取消旧的单动作优先级和额外换帧；保持原比赛配置并使场上球员可控制。
- [回放保存](../../engine/src/frame_sync/native_replay.hpp)：途中保存当前确认前缀时继续录制，退出时停止；保留实际文件发布与清理错误。TCP／UDP 均使用相同实现。
- [UDP 客户端](../../engine/src/frame_sync/integrated_client_udp.cpp)：网络回调与 GameEnv／SDL 由入口线程处理，取消原后台 IO 线程；独立可靠心跳使输入停止发送时仍能检测失去回程的连接。
- [服务端输入窗口](../../engine/src/frame_sync/server_input_window.hpp)：固定 16 帧 × 22 槽位，3728 字节，无动态增长。相同重复可接受，冲突或非法包整包拒绝；过期或超前超过窗口的包不改变状态。帧开始前的输入保留到对应逻辑边界，断线清除该槽位所有待消费帧。消费先封闭当前帧，再调用引擎。
- [引擎 TCP 服务器](../../engine/src/frame_sync/engine_tcp_server.hpp)与[UDP 服务器](../../engine/src/frame_sync/asio_server_engine.cpp)已接入；UDP 的心跳帧号读取和帧号更新也使用同一互斥锁。其他纯传输／独立示例服务器尚未完成同等改造。

## 发现并保留的失败

1. 原生入口集成 A 在 UDP 回程全部丢失后无法退出：不再重复发输入后，可靠通道没有待重传数据，无法触发失效。B 加入独立心跳，原 60 秒退出条件保持不变，Release／ASan 实际断流用例通过。[失败日志](../optimization/benchmarks/native-runtime-integration-20260913-a/evidence/release-udp-pair.log)
2. 窗口 A 缺少 GLEW 头文件；B 改用 SDL OpenGL 声明与函数查询，编译通过。[A 编译日志](../optimization/benchmarks/native-runtime-window-20260913-a/evidence/trace-build.log)
3. 窗口 B 将加载画面的第一次 SDL 换帧误判为比赛就绪，在初始化期间发送了按键。C 等待实际逻辑帧与比赛渲染出现，并记录每次换帧的归属；加载换帧仍保留。[B 实际轨迹](../optimization/benchmarks/native-runtime-window-20260913-b/evidence/namespace/windows/standalone/trace/events.jsonl)
4. C 的单机功能检查通过后，PNG 导出因缺少 PIL 失败；D 使用标准库无损编码原始 RGB 字节，并核对压缩往返一致。[C 结果](../optimization/benchmarks/native-runtime-window-20260913-c/evidence/namespace/windows/standalone/report.json)
5. D 的本地输入／显示检查通过，但进一步解码回放发现 TCP 13 帧、UDP 12 帧的权威输入全部为零。原服务器只接受当前收集时段内的输入，提前到达的预测帧被丢弃。客户端每帧只发一次后无法补回。[明确的失败证据](../optimization/benchmarks/native-server-input-window-20260913-a/authority-input-failure.json)
6. 增加服务端缓存后，E 在保留此前窗口条件的同时新增确认输入检查；TCP／UDP 都出现了实际移动、冲刺和短按射门，随后真实引擎重放所有确认帧的哈希通过。D 的较窄通过范围与失败文件均未覆盖。

## 实际验收结果

| 验收 | Release | ASan／UBSan |
| --- | --- | --- |
| 服务端缓存：独立有序映射对照、重复冲突、非法输入、移除槽位、帧号边界 | 552018 条断言，18000 帧 | 552018 条断言，18000 帧 |
| 集成 C：实际三入口与服务器 | 单机 20 帧；TCP 11 用例；UDP 故障 4 用例、实际对局断流 1 用例 | 相同用例通过 |
| 时钟与实际回放 | 400301 条断言；40000 调度事件；70 个实际确认帧 | 相同数量通过，检测器无错误 |

窗口 E 运行实际 Release 产品程序，使用私有 X11 和 XTEST。单机、TCP、UDP 分别完成 27／47／44 次比赛渲染，每次恰好一次 SDL 换帧；三者各另有一次初始化换帧，均发生在比赛渲染前。所有比赛渲染的前后状态摘要相同。保存了实际 1280×720 RGB／PNG 图像，并查看了三入口的第 24 次换帧图像：

- [单机画面](../optimization/benchmarks/native-runtime-window-20260913-e/evidence/namespace/windows/standalone/trace/frame-24.png)
- [TCP 画面](../optimization/benchmarks/native-runtime-window-20260913-e/evidence/namespace/windows/tcp/trace/frame-24.png)
- [UDP 画面](../optimization/benchmarks/native-runtime-window-20260913-e/evidence/namespace/windows/udp/trace/frame-24.png)

TCP 与 UDP 各有 35 个确认帧、8 个非零输入帧，其中短按射门各 1 帧。途中保存的 28 帧前缀逐帧、逐输入与最终文件相同。TCP 未拥有的槽位保持中性，UDP 两个拥有槽位输入一致。原生 ReplayPlayer 读取两个前缀和最终文件后，实际 GameEnv 在 Release／ASan 各重放全部 70 个确认帧，逐帧哈希、前缀末尾哈希与最终哈希均一致。

回放格式尚未包含完整队伍／节拍元数据，本次重放使用窗口用例明确固定的 1v1、seed 42、每帧 10 次物理步；这不是任意旧回放的通用兼容性证明。截图使用软件渲染和观测钩子，不能作为延迟或渲染性能测量。窗口测试正常退出三个客户端；TCP 服务端退出 0，UDP 服务端仍以 SIGTERM 收尾（-15），其完整退出生命周期还需改进。

## 可复核证据

以下 receipt 均在生成后以固定 SHA-256 再次独立逐文件验证：

| 阶段 | 报告 | receipt：文件数／SHA-256 |
| --- | --- | --- |
| 入口集成 C | [report.json](../optimization/benchmarks/native-runtime-integration-20260913-c/evidence/report.json) | [1106 文件](../optimization/benchmarks/native-runtime-integration-20260913-c/verification.json)／3a2ffdeb860b54cd6b27cdc306a1a9b09198c1f2795a9c872848bebb5ee85bb3 |
| 服务端窗口 A | [report.json](../optimization/benchmarks/native-server-input-window-20260913-a/evidence/report.json) | [1040 文件](../optimization/benchmarks/native-server-input-window-20260913-a/verification.json)／daa0ec6f76d5bd44198b67b47323026083cf981872967c7b279c6cb4bd896ec9 |
| 实际窗口 E | [report.json](../optimization/benchmarks/native-runtime-window-20260913-e/evidence/report.json) | [1126 文件](../optimization/benchmarks/native-runtime-window-20260913-e/verification.json)／aaa8f83838ac5be29b17be40f19bc173d55cfe9e99db1716f479c65808c95390 |
| 时钟与真实回放 A | [report.json](../optimization/benchmarks/native-runtime-clock-replay-20260913-a/evidence/report.json) | [1053 文件](../optimization/benchmarks/native-runtime-clock-replay-20260913-a/verification.json)／5fc70a551aca7a895f6ead87a56e20bcfa8c9975485ca86686b92dab853b811b |

服务端窗口模型执行时的两份旧服务器源码已按哈希保存在 before 目录；receipt 明确记录历史路径迁移。集成 C 保存了改动前四个服务器二进制。原始性能基准、默认场景、AI 对照样本和基线归档未更改。

## 后续任务

1. 为本次输入／时钟／服务器缓存实现建立正式可重复运行的验收入口，并刷新受源码变更影响的前置门禁。本次正常 Program 状态计算表明 ms19～26 当前均为 stale，未手工提升状态；[状态快照](../optimization/benchmarks/native-runtime-progress-20260913-a/program-states.json)。
2. 升级产品节拍与协议协商：当前 10Hz 仍有最长接近 100ms 的理想采样等待，不满足本机动作生效 p95 ≤50ms 的手感条件。需要同时处理物理步数、比赛时长、回放元数据和历史容量；保留原性能基准身份。
3. 扩充真实双客户端非零输入、WAN／乱序／慢端、UDP 退出与异常生命周期，并覆盖其他服务器入口。
4. 继续实际纠正回滚图像连续性、渲染资源失败路径和 AI 行为验收。完成相应证据前，不将产品优化里程碑标记完成。
