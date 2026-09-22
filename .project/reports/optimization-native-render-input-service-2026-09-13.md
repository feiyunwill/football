# 原生渲染期间输入采样优化（2026-09-13）

本轮沿 ms22 手感 → plan22.1.1 输入闭环 → task22.1.1.1 采样推进，同时记录 task23.1.1.1 权威输入窗口与 ms24 渲染的交叉问题。完整产品验收仍在进行，状态由质量检查器计算。

## 实测问题

[只读链路观测 A](../optimization/benchmarks/native-input-latency-trace-20260913-a/analysis.json) 使用实际 XTEST 按键投递、SDL 采样、成功的真实 socket 发送、服务器及客户端 GameEnv Step 和 SDL present 时间。产品源码与 27 个二进制在执行前后均与上一轮 D 门禁一致。

| 首次 D+Shift | XTEST 投递完成→SDL 采样 | SDL→发送完成 | 发送完成→服务器开始应用 | 投递完成→本地应用完成 | 投递完成→之后首次 present 完成 |
|---|---:|---:|---:|---:|---:|
| standalone | 58.03 ms | — | — | 60.95 ms | 143.10 ms |
| TCP | 25.88 ms | 3.72 ms | 36.70 ms | 91.38 ms | 150.60 ms |
| UDP | 45.02 ms | 0.06 ms | 35.10 ms | 133.00 ms | 218.60 ms |

每项是单次观测，不是 p95 或受控性能结论。投递时间以 XTEST 调用与 XSync 返回为边界，SDL state 行不是共享缓冲区精确提交时刻，成功 send 不是对端接收时刻。本地预测可以先于对应服务器 Step 完成。首次后续 present 只是时间关系，尚不能证明球员像素因该输入发生了变化。

约 20 ms 的 V 短按在 A 中分别对应 standalone 5 帧、TCP 1 帧、UDP 4 帧射门位。多帧按住位不等于多次射门动作。

[更细渲染观测 B](../optimization/benchmarks/native-input-latency-trace-20260913-b/partial-analysis.json) 在 TCP 持续输入检查失败，保留原始失败且未执行 UDP。服务器帧 197、198 均为空输入；197 在应用前约 36.75 ms 已成功从客户端发送，198 在捕获的发送中缺失。缺少接收回调时间，原因尚未确定，不能把上一轮零空档样本推广为全部运行。相机阶段平均约 42.56 ms，占本轮 TCP 绘制约 52.05 ms 的大部分。

## 具体实现

- [ScopedRenderService](../../engine/src/systems/graphics/render_service.hpp) 在共享库中保存线程局部的、作用域内有效的回调；按绝对 4 ms 机会调用，跳过已错过机会，防止递归调用，异常正常传播并恢复外层作用域。
- 渲染任务、图元批次、灯光、全屏绘制、帧缓冲切换及读回边界提供采样机会。无活动作用域时不调用时钟或 SDL。
- 原生三个入口由 NativeWindowInput 在绘制期间注册回调，只采样设备并 Feed 到原有共享输入缓冲区。SDL、GL、GameEnv 仍由各自现有线程使用；不在绘制回调中处理暂停、重放保存或推进物理。
- 没有改变 FNAT1、输入帧选择、有界历史、原始 benchmark、场景、AI 对照或验收阈值。
- 新增永久合同验证 10000 个独立时间机会、64 次嵌套和异常生命周期、8 个线程的作用域隔离，以及 60 ms 绘制过程中的 20 ms 短按被采样并释放。

回调不能打断单次阻塞的 GL 调用，因此 4 ms 是调度机会间隔，不是设备响应上界。服务器输入空档、控制暂停处理延迟、完整弱网矩阵和真实球员 50 ms 响应还需要后续验收。

## 验证结果

[当前固定输入门禁](../optimization/benchmarks/native-render-input-service-20260913-a/gate/report.json) 通过 **2,625,238 条断言、零跳过**。实际 standalone 442 步／95 次绘制，TCP 516 个确认帧、UDP 514 个确认帧；1,030 个确认帧在 Release 与 ASan 中逐帧哈希全部一致，各 452,557 条时钟／回放断言。两个网络窗口中央持续区间分别 70／70、69／69 完整输入；释放、失焦、控制暂停、恢复保持屏障及重新按下通过，本轮射门位各 1 帧。所有产品进程正常退出，绘制均单次 present 且不改变逻辑摘要。

[补充验证](../optimization/benchmarks/native-render-input-service-20260913-a/followup-report.json)：新服务在 Release、ASan/UBSan、TSan 各 20,522 条断言通过。TSan 范围是服务组件及原有输入泵组件，不是整个图形引擎。实际 GameEnv 画面与附件姿态回归在 Release、ASan 各 439 条断言，分别覆盖 8 个卡牌场景及 6 张中间帧，LeakSanitizer 开启并通过。已查看本轮 TCP／UDP 真实比赛图，HUD 为 00:25／00:26。

[修改后链路复测 C](../optimization/benchmarks/native-input-latency-trace-20260913-c/analysis.json) 的源码、二进制和依赖在执行前后与当前门禁一致；三个窗口及严格持续／焦点／暂停检查均通过。C 另外保存 TCP 517、UDP 516 帧，其保存输入已独立解码，未另外宣称完成这 1,033 帧的全引擎重放。

| 首次 D+Shift | 投递完成→SDL 采样 | SDL→发送完成 | 发送完成→权威应用开始 | 投递完成→本地应用完成 | 投递完成→后续 present |
|---|---:|---:|---:|---:|---:|
| standalone | 0.76 ms | — | — | 73.00 ms | 142.64 ms |
| TCP | 9.41 ms | 10.04 ms | 32.30 ms | 76.48 ms | 151.25 ms |
| UDP | 3.81 ms | 20.27 ms | 27.43 ms | 73.79 ms | 173.22 ms |

C 中释放到 SDL 采样分别 1.69／0.78／0.42 ms，但释放到本地应用分别 63.68／128.43／57.59 ms。实际短按持续约 24／20／22–24 ms，standalone／TCP／UDP 射门位分别保留 3／1／1 帧。绘制期间及时采样并未解决本地批量追帧使用当前输入的时间归属问题。

[采样间隔对照](../optimization/benchmarks/native-render-input-service-20260913-a/sampling-comparison.json) 显示 C 的完整绘制帧均出现内部采样，A 为零。C 的按住区间采样间隔中位数约 5.66／5.92／7.20 ms，p95 仍为 40.89／41.34／48.69 ms，TCP 最大间隔 84.83 ms。A/C 是非配对单次观察，不能据此宣称性能百分比提升或延迟上界。

当前 Release 核心 SHA256 为 `8552274451f2355a3891842b52afafdf36e9aef41211b69785d3b83f35ba5179`，ASan 核心为 `85821530decb12ad033ad48e2ba177ec1959abf21cedee7c9e9c5cdac9a6d8e5`。旧核心已按阶段备份；原始性能基线和对照未改动。质量结构校验为 56 节点／31 检查，ms19–26 当前均为 stale，未手动提升。

## 后续任务顺序

1. task22.1.1.2：明确本地欠帧与设备事件的时间归属，避免一次当前按键被追溯应用到整批过去的固定帧。
2. task23.1.1.1：补齐 socket 接收、解析和实际采用时间，定位 B 的帧 197／198 空输入；在实际弱网及调度停顿下验证，不凭单次零空档结论通过。
3. task24.1.2.2：定位单次 40–85 ms 绘制阻塞并减少串行等待，继续检查输入提交、预测应用与展示延迟。
4. 当前源码上刷新前置质量链，完成固定步长、插值、原生重连／旁观者、权威暂停与最终产品验收。

证据文件的独立 SHA256 清单见[验证收据](../optimization/benchmarks/native-render-input-service-20260913-a/verification.json)。
