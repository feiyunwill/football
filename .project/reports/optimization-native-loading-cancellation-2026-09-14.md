# 加载生命周期、资源取消与退出响应 — 2026-09-14

本轮继续里程碑 23 → plan-23.1.1 → task-23.1.1.2。已实现私有候选的 prepared API 防护、可中断加载、部分资源回收和 Tracker 配对同步修复。实际 Release 加载退出的四个采样均满足 250ms；ASan 仍未全部通过。正常加载、像素、混合客户端及独立旧核心回放已完成。没有正式接入或提升产品级状态。

## 实现与审查

| 环节 | 发现与修改 | 验证范围 |
| --- | --- | --- |
| 框架 / 生命周期 | prepare_game 后尚无 Match，旧 get_info 会直接解引用空指针。统一检查 Match 是否已初始化；公共序列化入口也检查所有权及空参数 | 19 个 prepared 操作、嵌套环境恢复、20 帧旧入口对照、快照往返与重启 |
| 架构 / 线程 | 公共 ProcessState 加锁会使 Tracker 配对校验再次获取已暂停工作线程的锁。保留公共入口保护，Tracker 在既有配对同步范围内调用私有序列化函数 | 实际双工作线程：旧核心通过 → 首个加锁候选 watchdog 退出 42 → 修复候选通过 |
| 资源 / 性能 | 生成动画、创建球员及草皮时原先不能处理退出。加入线程局部的加载作用域与检查点；部分动画、SDL surface、Perlin、数组和 Match 资源由明确的清理责任覆盖 | 分阶段检查 26 个取消边界，Release / ASan 共 52 个场景、892 条断言；其中两处取消后重试还核验初始及首帧哈希 |
| 渲染 / 手感 | 加载页构建和首次绘制之间存在长时间不读取取消的问题。给加载页增加 10 个安全边界及构造回滚；首次绘制使用已有 ScopedRenderService 检查取消 | 真实 XTEST 按键、实际客户端，Linux pidfd 观察自然进程退出 |
| 网络 | 加载检查点同时读取已有退出、连接终止及绝对加载期限；取消后停止并回收 IO 工作线程，再由原有所有者关闭窗口和引擎 | 实际取消保持 confirmed=0；Release / ASan 实际加载中断线、第 0 帧开局、200 帧完整运行通过 |
| AI / 确定性 | 本轮未修改 AI 决策；资源取消不能改变正常开局的输入、比赛 RNG 或草皮视觉 RNG | 两种构建全量纹理、比赛与视觉 RNG 对照一致；旧核心四次交叉回放一致 |

最终候选组合是 cancellation D 核心、cancellation B 实际客户端与 initial-loading B 服务端。D 使用 C 的 game_env 对象、B 的核心资源及 Tracker 对象，并增加 loadingmatch 对象。类字段布局保持兼容。所有改动保留在私有候选，原代码副本与被替换段落均有记录。

源代码入口：

- [GameEnv 生命周期与重置](../optimization/benchmarks/native-loading-cancellation-20260914-c/game_env.cpp)
- [加载作用域及资源清理](../optimization/benchmarks/native-loading-cancellation-20260914-b/game_load.hpp)
- [Tracker 配对序列化](../optimization/benchmarks/native-loading-cancellation-20260914-b/main.cpp)
- [Match 部分初始化回收](../optimization/benchmarks/native-loading-cancellation-20260914-b/match.cpp)
- [动画资源所有权](../optimization/benchmarks/native-loading-cancellation-20260914-b/animcollection.cpp)
- [草皮生成资源与检查点](../optimization/benchmarks/native-loading-cancellation-20260914-b/proceduralpitch.cpp)
- [加载页构造回滚](../optimization/benchmarks/native-loading-cancellation-20260914-d/loadingmatch.cpp)
- [实际客户端加载取消](../optimization/benchmarks/native-loading-cancellation-20260914-b/integrated_client.cpp)

取消仅在资源已经有明确所有者的边界抛出。reset 回滚会结束部分 Match、清理待用 MatchData 与部分缓存、恢复随机数及 Tracker 状态，同时保留仍由 UI 线程使用的运行环境。加载开始之前的取消保留已有完整比赛；加载中途取消后的环境允许重试。渲染后草皮缓存与视觉 RNG 的取消后重试像素一致性尚未完整验证，不能由无渲染重试测试推断。

## 实际窗口结果

以下为最终 D 核心 + B 实际客户端，未使用诊断计时客户端。每个阶段各一次采样；结果不能当作 p95 或稳定性能收益。

| 请求 Q 时的阶段 | Release 退出耗时 | ASan 退出耗时 | 250ms 结果 |
| --- | ---: | ---: | --- |
| 初始加载窗口 | 117.104ms | 443.796ms | Release 通过，ASan 失败 |
| 动画文件加载 | 46.025ms | 205.499ms | 两者通过 |
| 草皮漫反射生成 | 115.998ms | 721.149ms | Release 通过，ASan 失败 |
| 草皮法线生成 | 122.389ms | 428.310ms | Release 通过，ASan 失败 |

八个场景均观察到真实加载窗口、正常客户端退出、双方退出码 0、零比赛确认帧，没有发现 sanitizer 错误。最终 ASan 初始场景和法线场景的服务端绑定分别耗时 41.881s 与 34.224s，也超过原定 30s。诊断观察允许等待 120s，但通过标准仍为 30s，未放宽验收。

早期诊断另发现：

- 取消读取前曾等待 0.892s 与 1.453s；后者日志将范围缩小到加载页构建期间，不能仅凭旧日志认定为首次 GPU 绘制。
- 草皮后期曾有约 190–257ms 的资源展开回收、108–179ms 的引擎关闭、336–499ms 的引擎关闭后进程退出耗时。
- 最后一段成本尚未区分泄漏扫描、驱动或其他全局销毁，不能直接归因于 LSan。
- 同机启动与退出耗时有明显波动；本轮没有硬件性能或 50ms p95 验收结论。

证据：[实际窗口结果](../optimization/benchmarks/native-loading-cancellation-window-20260914-b/report.json)、[精确分段诊断 A](../optimization/benchmarks/native-loading-cancellation-timing-20260914-a/report.json)、[早期边界诊断 B](../optimization/benchmarks/native-loading-cancellation-timing-20260914-b/report.json)。

## 失败与证据保留

- 生命周期 A 使用不存在的 GetGameTLS 名称导致测试编译失败；B 测试将带 pickle 前缀的快照交给空前缀比较入口，导致夹具失败。最终 C 使用真实 GetGame 接口并分别检查 pickle 往返及空前缀比较。
- 旧核心 prepared get_info 的 Release 空指针崩溃与 ASan UB 是明确的失败对照，没有纳入 sanitizer 干净结果。
- cancellation A 的 Tracker 锁回归由双线程 watchdog 明确复现。退出 42 表示失败对照，不能证明资源回收成功。
- 旧窗口 A、计时 A/B 与最终窗口 B 的所有超时或耗时失败均保留。没有覆盖旧日志、重复运行原证据目录或修改阈值。
- 计时 B 的一个窗口枚举遇到 Xlib BadWindow，默认处理器在 Python finally 前退出。已通过 PID 与启动 ticks 核验并用 pidfd 终止残留服务端；客户端已不存在。两者退出码无法追溯，明确保留为未知。新测试只容许枚举期间已销毁窗口的 BadWindow，其他 X11 错误仍失败。

## 正常加载与回归终态

- GPU 对照共 4 次：新旧核心 × Release / ASan。每次完整读取 12 张纹理、18,874,368 像素；纹理表摘要、视觉 RNG 及初始比赛哈希完全相同。
- 单次加载时长：Release 13.120s → 11.660s；ASan 52.457s → 80.939s。候选在这次 ASan 对照中更慢，原因尚未归属。采样数不足，不能认定稳定收益或排除性能退化。
- 混合客户端 A 的 Release 场景通过；其 ASan 场景在绑定前超过 30s，退出码 -15，未启动客户端。
- 新诊断 B 的 ASan 约 13.373s 完成绑定并通过全部后续场景，先前失败仍保留。两种构建均在加载中切断连接 0.8s，恢复后从第 0 帧共同开局，各完成 200 个权威帧和 400 个客户端保存帧。
- 两种构建前 60 帧均有 59 帧保留方向及冲刺，加载期射门轻点为 0；全部服务端和客户端正常回收。两场共记录 57,333 条断言，其中包含随运行时长变化的网络轮询检查，数量不代表新增覆盖率。
- 独立旧核心四次交叉重放全部通过，共 11,448 条断言。使用前一版未修改的核心、未重新编译的验证器，对两种构建的新录制各核验 200 个权威帧、400 个客户端保存帧，未使用恢复快照替代初始加载结果。

证据：[独立旧核心回放](../optimization/benchmarks/native-loading-cancellation-replay-20260914-a/report.json)、[GPU 全量对照](../optimization/benchmarks/native-loading-cancellation-textures-20260914-a/report.json)、[Release 混合客户端](../optimization/benchmarks/native-loading-cancellation-mixed-20260914-a/release-x11/product/report.json)、[首轮 ASan 启动失败](../optimization/benchmarks/native-loading-cancellation-mixed-20260914-a/sanitized-x11/product/report.json)、[ASan 补充诊断](../optimization/benchmarks/native-loading-cancellation-mixed-20260914-b/report.json)。

## 后续任务与完成条件

1. 继续缩短加载页操作及草皮后期资源销毁的阻塞，给 ASan 超时、进程尾部销毁和服务端慢启动补上可归因的证据。
2. 补充认证的加载取消与席位释放。当前取消依靠连接关闭及既有有限租约 / 宽限期，不等同于立即释放。
3. 验证图形加载取消后重试的草皮缓存、视觉随机状态及像素一致性。
4. 将已验证的生命周期、加载协议、客户端恢复和资源所有权实现正式接入，再执行相应完整门禁。
5. 继续原生 UDP 恢复、完整弱网矩阵、旧 UDP 第 200/201 帧缺口定位、50ms p95 与硬件验收，并完成其他优化里程碑中尚未满足的 AI 和产品质量条件。

新证据收集器与独立验证器位于 [collect.py](../optimization/benchmarks/native-loading-cancellation-evidence-20260914-a/collect.py)、[verify.py](../optimization/benchmarks/native-loading-cancellation-evidence-20260914-a/verify.py)。前向链继承原先的未知结果与未验收事项。本轮不改变源码清单、正式产物或五份受保护基线；最终以收集与独立复验终态为准。
