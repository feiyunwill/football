# 原生输入接纳链路与主线程采样原型

2026-09-13。本轮为实际服务器增加分阶段观测，完成真实窗口回放和受控协议故障验证，并运行新的 SDL 主线程采样原型。当前产品源码、资源、原有二进制与验收阈值均未修改；原型尚未作为产品实现通过验收。

## 里程碑 → 计划 → 任务

| 里程碑／计划 | 任务 | 已取得证据 | 后续工作 |
| --- | --- | --- | --- |
| ms-23.1／plan-23.1.1 | task-23.1.1.1 | 接收→回调→接纳→封帧→实际引擎输入；TCP／UDP 受控故障 | 旧偶发异常、完整弱网、产品客户端预测／恢复 |
| ms-22.1／plan-22.1.1 | 输入与设备响应任务 | 主线程采样、单一工作线程模拟／GL 的真实窗口原型 | 正式共享组件、错误退出／并发契约、三个入口及实际延迟 |
| ms-24.1／plan-24.1.2 | task-24.1.2.2 | 稀疏投影与软件线程数实验 | 尚无可靠收益，不采用；继续真实渲染预算优化 |

## 完整输入接纳链路

在覆盖原始头文件的独立服务器构建中，只添加观测，不改变接纳与封帧语句。客户端和引擎核心仍为原有二进制。[三入口严格窗口](../optimization/benchmarks/native-admission-observe-20260913-b/report.json)均通过：TCP、UDP 各保存 518 个确认帧。

[独立对应检查](../optimization/benchmarks/native-admission-observe-20260913-b/analysis.json)确认 TCP 527 次、UDP 519 次接纳全部 Accepted，没有 Stale／OutsideWindow／Invalid／Conflict。对退出操作之前的 TCP 516 帧和 UDP 517 帧，逐一核对发送／接收字节、解析后的槽位、接纳结果、封帧内容及 GameEnv 实际输入，完全一致。退出之后的 11／2 个提前接纳帧单独列出，避免把断连清理误报为输入损坏。

| 阶段 | TCP 中位耗时 | UDP 中位耗时 |
| --- | ---: | ---: |
| 发送完成→接收完成 | 0.452ms | 0.485ms |
| 接收完成→回调 | 0.021ms | 0.005ms |
| 回调→进入接纳 | 0.009ms | 0.020ms |
| 接纳完成→封帧 | 34.518ms | 35.496ms |
| 封帧完成→引擎 Step | 0.035ms | 0.028ms |

本样本没有支持解析或互斥等待是主要耗时的证据。接纳后等待主要来自现有提前发布／固定封帧安排，但不能据此直接缩小网络提前量。之前 TCP 197／198 帧和 UDP 203 帧的偶发问题仍保留，不能用此次通过替代其解释。

[1036 帧重放](../optimization/benchmarks/native-admission-observe-20260913-b/replay-report.json)在 Release 与 ASan／UBSan 下分别通过 452573 条断言、40000 个时钟事件，零跳过，实际引擎全部逐帧哈希匹配；LeakSanitizer 保持启用。

## 受控协议故障

[独立线协议客户端](../optimization/benchmarks/native-admission-faults-20260913-c/faults/report.json)驱动上述实际服务器，两种协议均验证：

- 未收全的应用帧不接纳；相同输入重复发布仍一致。
- 未来帧按不同顺序到达，最终对应的封帧输入正确。
- 缺帧保持中性；封帧后迟到返回 Stale，不能改写过去帧。
- 超出窗口返回 OutsideWindow；同帧冲突返回 Conflict。
- 各检查 4 个实际 GameEnv 输入帧，两个服务器正常退出。
- UDP 额外验证可靠序列缺口阻止后续交付、重复数据报不重复交付，填补缺口后按序处理。

这覆盖权威接纳规则，不覆盖真实产品客户端的完整弱网预测、恢复或 WAN 质量，未标作相应验收通过。

初始服务器观测构建因阶段目录缺少原源码的局部 include 搜索路径而失败，后续只修正构建参数。第一版故障客户端在服务器监听前重用连接失败的 TCP socket，触发 ECONNABORTED；清理时服务器尚未注册信号处理，退出 -15。失败记录完整保留，后续明确等到真实监听日志再建立连接，未修改产品启动或网络规则。

## 渲染实验的结论

- SSAO 稀疏投影原型保留全部 32 个样本和一般矩阵回退。四次真实引擎执行的 RGB 与完整状态仍逐字节一致，但平均整帧耗时为 107.506／59.659／108.026／74.556ms，波动不足以支持收益结论。[比较数据](../optimization/benchmarks/native-ssao-projection-prototype-20260913-a/comparison.json)
- 仅在子进程将 Mesa 软件线程数设为 4，保持原始着色器，画面和状态仍完全相同；四次平均耗时为默认 52.515／4线程 115.046／4线程 121.316／默认 84.132ms。本样本不支持该设置，因此不修改产品或用户环境。[比较数据](../optimization/benchmarks/native-software-thread-probe-20260913-a/comparison.json)

## SDL 主线程采样原型

SDL 事件采样必须留在初始化视频的线程，这是官方约束。[SDL_PollEvent](https://wiki.libsdl.org/SDL2/SDL_PollEvent) 同一 GL 上下文也不能同时成为两个线程的当前上下文。[GLX 1.4 规范](https://registry.khronos.org/OpenGL/specs/gl/glx1.4.pdf)

据此，原型在主线程创建／关闭窗口、采样设备和设置标题；先释放主线程的 GL 当前上下文，再由一个受管理、可 join 的工作线程串行执行 GameEnv 模拟与渲染。输入时间线经短临界区同步，临界区内不执行 GL 或模拟；标题使用有界交接。它没有让模拟与渲染并发访问同一 GameEnv。

[实际 standalone 窗口](../optimization/benchmarks/native-ui-owner-prototype-20260913-a/report.json)完成 443 步、134 次渲染，持续持有区间零空档，状态不被渲染改写，每次渲染一次呈现。[2135 次采样的相邻间隔](../optimization/benchmarks/native-ui-owner-prototype-20260913-a/sampling-summary.json)：中位 4.135ms、p95 7.097ms、最大 15.758ms。相较此前出现 70–100ms 的采样空档，这提供了进一步实施的依据，但两个样本未配对，不声称固定改善百分比。

本轮首个本地响应样本仍为 55.897ms；渲染 p95 104.158ms。采样改善不等于玩家／呈现延迟达标。原型尚未有并发／异常生命周期契约，也未接入两个网络产品入口，不得作为产品级完成证据。

## 下一项具体实现

提取 SDL 无关的主线程服务／工作线程生命周期组件与同步本地时间线；主线程采样无需 GameEnv 锁或 GL 上下文，工作线程停止与异常必须正确传播。接入 standalone 及共享 RunNativeClient，再执行线程所有权、暂停／恢复、错误退出、Release／ASan／TSan、实际三窗口和确认帧回放。继续保留 50ms 实际响应及渲染预算的未完成状态。

[证据清单](../optimization/benchmarks/native-admission-observe-20260913-b/verification.json)区分实际通过、保留失败和未采用原型；清单完整性通过不等于产品验收通过。
