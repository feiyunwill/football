# 原生窗口与游戏线程职责：实现、回归及剩余发布空档

本轮将主线程采样正式接入 standalone、TCP、UDP，保留游戏计算与渲染的单一所有者。新并发组件和三个真实入口的线程观测通过，但固定输入门禁 B 捕获 TCP 权威第 138 帧的持续输入空档，完整验收仍未通过。后续独立观测的成功不覆盖这次失败。

## 里程碑 → 计划 → 任务

推进 ms-22.1 → plan-22.1.1 → task-22.1.1.1，并向 task-23.1.1.1（网络）和 task-24.1.2.2（渲染）回填证据。下一项是接收批次导致的发布帧号跳跃及实际弱网验证。质量结构检查通过 56 个节点、31 个检查；ms-19.1 至 ms-26.1 均仍为 stale，不手动提升状态。

## 具体实现

- [NativeUIOwner](../../engine/src/frame_sync/native_ui_owner.hpp)：创建线程服务窗口，一个可回收的 jthread 执行游戏。拒绝外部线程和重入；工作异常回传；UI 异常请求停止并等待工作退出，捕获对象销毁前完成 join。4ms 是服务机会，不是硬延迟保证；停止检查仍需等待当前阻塞 GL 调用返回。
- [同步时间线](../../engine/src/frame_sync/native_shared_timeline.hpp)：短锁串行化采样、暂停和固定截止时间消费；时间戳在取得锁后记录，避免与暂停操作逆序。占用 6328 字节，原有时间线的未来输入不回填旧帧、恢复屏障、溢出和重复截止时间规则保持原样。采样锁不覆盖 GameEnv 或渲染。
- [窗口入口](../../engine/src/frame_sync/native_loop.hpp)：主线程创建窗口、处理 SDL 输入、设置标题和销毁设备；缓存窗口与 GL 上下文身份，交接及每次渲染均验证实际选择结果；不持有引擎锁跨越整个工作线程生命周期。标题使用固定 256 字节缓冲。headless 路径仍直接运行。
- [本地入口](../../engine/src/frame_sync/standalone_game.cpp)与[网络共享循环](../../engine/src/frame_sync/native_client_loop.hpp)：模拟、画面状态与 GL 操作在游戏线程串行执行；现有网络工作线程继续独立发布及接收。
- [TCP](../../engine/src/frame_sync/integrated_client.cpp)和[UDP](../../engine/src/frame_sync/integrated_client_udp.cpp)：画面状态对象在首次实际 tick/render 的所有者上创建，包裹回调后再初始化。保留 NativePresentation 原有严格线程归属检查。
- [永久合同](../../engine/tests/engine_native_ui_owner_contract.cpp)已注册到 CMake 和[固定输入检查器](../checks/input_contract.py)，包括独立 TSan 运行。

SDL 事件处理遵循[SDL_PollEvent 官方线程要求](https://wiki.libsdl.org/SDL2/SDL_PollEvent)；上下文交接依据[GLX 1.4 规范](https://registry.khronos.org/OpenGL/specs/gl/glx1.4.pdf)。本轮实际窗口证据限于 Linux/X11 软件渲染环境，未构成其他平台或硬件性能验收。

## 已执行的验证与保留的失败

1. [实施 A](../optimization/benchmarks/native-main-ui-20260913-a/exit.json)：standalone 和并发检查通过；TCP 首次运行触发 “Presentation belongs to its creating thread”。原有保护准确发现了初始化边界错误，记录保留。A 的实施版本已存于 B/before，原始旧文件存于 A/before。
2. [修正版 B](../optimization/benchmarks/native-main-ui-20260913-b/exit.json)：Release 与 ASan/UBSan 合同通过，新 owner 合同分别 27603、46418 条断言；TSan 43656 条断言。每组覆盖 64 次线程生命周期、256 个截止时间交接和 20000 次并发观察，零跳过。实际 standalone 440 步、98 次渲染通过；TCP 正常退出并保存 515 个确认帧，但持续按键中央区间 70 个权威步中第 138 帧（观察编号 139）为中性输入，严格窗口检查失败，未进入 UDP 和门禁内回放。B 的整体 exit=1。
3. [独立真实线程观测](../optimization/benchmarks/native-main-ui-observe-20260913-a/analysis.json)：三个当前正式入口均通过原有严格窗口条件，所有 SDL PollEvent/GetKeyboardState 调用发生在进程主线程；StepWithInput 与 render_interpolated 在同一个独立线程；加载画面在主线程显示、比赛画面在游戏线程显示；实际上下文选择全部返回成功。每次比赛渲染恰好一次显示，渲染前后游戏状态摘要相同。
4. [当前实际回放](../optimization/benchmarks/native-main-ui-observe-20260913-a/replay-report.json)：独立观测产生 TCP 514、UDP 521 个确认帧，合计 1035 帧。在当前 Release 与 ASan/UBSan 实际引擎中逐帧重放，各 452572 条断言、40000 个时钟事件，零跳过，启用 LeakSanitizer。此回放包含该观测批次的数据，不是失败门禁 B 的 TCP 回放。

| 当前独立观测 | 本地 / TCP / UDP |
| --- | --- |
| 实际 Step 数 | 447 / 515 / 522 |
| 比赛渲染次数 | 126 / 139 / 130 |
| 慢渲染期间仍有至少 3 次采样的次数 | 126 / 139 / 130 |
| 采样间隔 p95，ms | 7.678 / 7.351 / 7.743 |
| 采样间隔最大值，ms | 18.212 / 38.934 / 32.114 |
| 本地响应完成时间，ms | 30.075 / 38.197 / 70.277 |

上述观测带日志和软件 GL 开销，不能视为无观测器吞吐或硬件基准。B 的 standalone 响应为 67.623ms；另一批次出现 30.075ms 不足以宣称稳定达到 50ms。1080p 帧时间 p95≤16.67ms 仍未验收。

## 新的可复现网络证据与下一步

[发送／接收／权威对应](../optimization/benchmarks/native-main-ui-observe-20260913-a/wire-analysis.json)中，已收到的活动期输入均与实际权威输入相同。但 TCP 在释放后的第 505、506 帧没有捕获到任何发送或接收，权威使用中性输入，因此该批次持续按键检查没有暴露这两个空档。

[原始发布空档证据](../optimization/benchmarks/native-main-ui-observe-20260913-a/publication-gap.json)显示：输入 504 发出后，权威 503、504、505 在同一次 TCP read 完成；54.374ms 后直接发送输入 507，中间 505、506 缺失。该序列与当前 target=max(received_authority_count+1,next_simulation) 的逐次目标计算一致，支持“接收批次可以跳过发布帧”的判断。它不是 B 第 138 帧的同一次失败，也不能证明内核到达时间或封帧接纳时间。

下一项先以真实客户端和可控接收延迟／批量到达复现，再验证有界的独立输入发布节拍；需同时保持唯一帧输入、短按一次消费、恢复屏障、服务器窗口和时钟漂移约束，不能仅缩小提前量或以延长输入延迟换取本地通过。完成后重新执行未放宽的固定输入门禁。随后继续 GL/SSAO 成本、完整弱网与重连、当前源码全质量链、AI 和发布长测验收。

## 证据身份

11 个最终实现文件见[B/changes.json](../optimization/benchmarks/native-main-ui-20260913-b/changes.json)。独立观测固定 1052 个源码/资产条目、33 个二进制和 1004 个依赖，执行前后均核对。Release/ASan 引擎核心、原始性能基线和冻结算法夹具均未变；本轮没有修改协议、服务器、画质或验收阈值。

[独立证据收据](../optimization/benchmarks/native-main-ui-observe-20260913-a/verification.json)包括 A/B 失败和成功观测。收据通过仅表示文件、命令结束状态和证据身份完整，full_input_gate_passed=false、product_acceptance=false。
