# 原生初次加载与多人开局：实现、回归和剩余问题（2026-09-14）

本轮把图形资源加载与网络 Ready 分开，私有候选已能在 Release 和完整 ASan 构建中实际入场；加载中断线恢复也通过真实双客户端验证。修复了加载期间射门轻点在开球后触发的问题。**加载取消仍未通过：真实窗口按 Q 后等待 2.8934 秒才退出，目标 0.25 秒。主工程尚未接入这些候选，产品级状态不提升。**

本轮属于 milestone-23 → plan-23.1.1 → task-23.1.1.2，关联框架生命周期、网络恢复、窗口输入及渲染加载。延续[上一轮球场优化](optimization-native-pitch-loading-2026-09-14.md)与[原生客户端恢复](optimization-native-client-recovery-render-2026-09-14.md)，已有历史失败记录保留。

具体实现：

- [GameEnv 候选](../optimization/benchmarks/native-initial-loading-20260914-b/game_env.cpp)新增 prepare_game，先创建运行环境和 SDL 窗口，再由游戏／GL 所属线程执行 reset。原 start_game 仍执行完整初始化并保留异常关闭逻辑。没有增加类字段；原生客户端在资源生成期间持续处理网络和窗口事件。尚需补齐 prepared 状态的公开 API 契约：例如 get_info 仍直接解引用未创建的 Match，step 也只有结束／暂停检查；此处为源码审查发现，尚未执行故障注入。
- [协议候选](../optimization/benchmarks/native-initial-loading-20260914-b/overlay/frame_sync/native_recovery_wire.hpp)增加 LoadHello(88)、LoadComplete(89)、LoadReceipt(90)，固定负载分别为 18／58／58 字节；原 80—87 消息保留。Session 的 loading 标志与 restoring 互斥。完整凭证包含 match、slot、generation 和 secret。
- [服务端候选](../optimization/benchmarks/native-initial-loading-20260914-b/overlay/frame_sync/engine_tcp_server.hpp)增加独立 Loading 状态和 120 秒绝对加载上限；原 Ready 30 秒、心跳空闲 3 秒、恢复宽限 30 秒不变。加载完成才开始 Ready 期限，Ready 仍由权威帧线程验证真实初始状态。加载恢复保留首次期限，LoadReceipt 只确认当前连接收到凭证，不给予输入或开赛权限。掉线的加载槽位在有限恢复期内继续阻止提前开赛，期限到达后释放。
- [最终客户端候选 C](../optimization/benchmarks/native-initial-loading-20260914-c/integrated_client.cpp)继承 B 的异步加载／恢复，实现资源加载结束时消费积累的游戏轻点；持续方向和冲刺、独立 UI 命令得以保留。传输线程不访问 GameEnv 或 SDL，初始化完成后才开始发布节拍和 Ready。C 只重建客户端，实际运行使用 B 核心与服务端，B 核心包含上一轮球场优化。

验证均串行执行，候选源文件、构建输入、实际二进制、日志和进程身份随证据保存。实际窗口使用隔离 X11 与 XTEST；未改系统环境、驱动或全局挂载。软件渲染结果不作为硬件或 50ms 手感验收。

| 验证 | 实测结果 | 证据 |
| --- | --- | --- |
| 真实 TCP 组件契约 | 两种构建各 11 项、共 1,046 条断言；覆盖慢加载、提前 Ready、伪造凭证、重试不续期、掉线屏障、心跳及加载后 Ready 期限。使用测试状态回调，不是完整 GameEnv | [构建及契约结果](../optimization/benchmarks/native-initial-loading-20260914-b/build-report.json) |
| B 实际图形启动 | Release 整次运行 5.192 秒、确认 100 帧；ASan 62.300 秒、确认 102 帧；真实客户端与服务端均退出 0 | [实际启动](../optimization/benchmarks/native-initial-loading-runtime-20260914-a/report.json) |
| C 图形＋无头双客户端 | 两种构建共 47,055 条断言；测试代理没有人为拦截 Ready。快客户端先就绪仍不推进权威帧，图形客户端加载中断网 0.8 秒后换代恢复；双方均从第 0 帧入场，各场 200 权威帧 | [双客户端与输入](../optimization/benchmarks/native-initial-loading-window-barrier-20260914-c/report.json) |
| 加载期真实按键 | 两种构建均保留 59 帧持续方向＋冲刺，射门轻点泄漏 0 帧 | [同一实际窗口报告](../optimization/benchmarks/native-initial-loading-window-barrier-20260914-c/report.json) |
| 独立核心交叉重放 | 用此次 prepare_game 修改之前的 P 核心，两种构建分别重放两场真实录制，共 4 次、11,448 条断言；每次对照 200 权威帧与 400 实际客户端保存帧，无快照，逐帧状态一致 | [独立重放](../optimization/benchmarks/native-initial-loading-replay-20260914-a/report.json) |
| 加载中 Q 退出 | Release 实际 XTEST：2.8934 秒，失败；客户端退出 0、确认帧数 0，服务端退出 0。没有伪造取消通过或修改 250ms 目标 | [失败实测](../optimization/benchmarks/native-initial-loading-cancel-20260914-a/release-x11/product/report.json) |

保留的失败与修正：

1. [初次构建 A](../optimization/benchmarks/native-initial-loading-20260914-a/build-failure.json)使用的传递头文件仍来自旧协议，测试 main 签名也与 GameEnv 声明冲突；B 补齐私有传递头并改正测试签名，两种配置重新构建通过。
2. [首次双客户端 A](../optimization/benchmarks/native-initial-loading-window-barrier-20260914-a/release-x11/product/report.json)实际完成双方 200 帧，但加载时的射门泄漏 1 帧；C 在加载完成边界清除轻点后，后续两种配置均为 0。
3. [双客户端 B](../optimization/benchmarks/native-initial-loading-window-barrier-20260914-b/release-x11/product/report.json)实际行为已符合要求，但报告读取不存在的 assertions 成员而失败；新测试目录 C 使用 ASSERTIONS，完整重新运行。旧失败未改写为通过。
4. 加载取消失败尚未修复。UI 能采集 Q，但游戏线程仍完成整个 reset 后才处理退出。Match、动画集合、程序球场存在原始资源所有权，不能直接在中途任意抛异常。

接下来的任务顺序：

1. 明确 prepared／loading 状态的公开 API 契约，拒绝不合法的观察、步进和快照操作；验证正常初始化与旧 start_game 行为兼容。
2. 先补齐 Match 部分构造、动画及球场资源的异常清理，再增加有界取消检查点。真实 Q、网络期限、加载错误分别验证；断开期间也不得绕过首次加载期限。取消后的槽位释放需有鉴权协议和断网时有限租约兜底。
3. 继续使用真实 Release／ASan 图形＋无头客户端验证慢加载、加载恢复、取消及故障清理；重放与像素随机序列不能改变。当前没有完整 ASan 取消证据。
4. 候选稳定后才正式接入源码、公共头和 CMake，刷新两种配置全部七个原生入口，再运行架构、输入、AI、网络与历史重放门禁。
5. 继续 UDP 同局恢复和完整弱网矩阵；旧 UDP 200／201 帧缺口、旧 ASan legacy 首次失败根因、硬件及 50ms 延迟、整体 AI 产品质量仍未完成。

本轮没有修改质量阈值、受保护基线、正式源文件或正式二进制。证据汇总与独立校验由 [collect.py](../optimization/benchmarks/native-initial-loading-evidence-20260914-a/collect.py) 和 [verify.py](../optimization/benchmarks/native-initial-loading-evidence-20260914-a/verify.py) 执行；其通过只表示证据可复核，不表示产品验收通过。
