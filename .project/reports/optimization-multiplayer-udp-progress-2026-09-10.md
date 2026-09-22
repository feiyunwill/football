# UDP 多人比赛进展（2026-09-10）

归属 `ms-21.1 → plan-21.1.2 → task-21.1.2.1`。本轮将比赛 v4 接入已有有界 UDP 传输并执行自动回归，属于实施进展。`memory_budget.ready=false`，当前任务、计划与后续手感、网络、渲染、AI、发布里程碑仍未通过整体验收，目标继续自动推进。

## 实现与修复

新增 multiplayer_udp.py，以 UDPServerRuntime 的实际 socket、cookie/epoch、分片、重传和关闭逻辑，配合 MatchServerRuntime 的原点、Ready、恢复和结束协议，共用一个权威引擎与 Peer 集合。客户端提取 MatchClientProtocol，让 TCP 和 UDP 共用 v4 应用协议；client_udp_resume.py 增加保持 v3 默认行为的缓冲/握手/限制类型钩子。已有 UDP 算法、原始消息版本和共享服务端核心没有修改。

HostedMatch 和 NetworkPlayer 增加明确的 `transport='tcp'|'udp'` 选择，Host/Join 菜单支持 `--transport udp`；默认仍为 TCP，设置文件格式不变。选择 UDP 后仍由相同的比赛循环执行输入、预测与回滚、原会话恢复、结束、保存、录制和独立回放。使用与容量说明见 [UDP 多人文档](../../gfootball/doc/multiplayer_udp.md)。

真实 socket 回归发现并修复：

- 1184 字节 UDP 载荷直接进入用户配置的 512 字节字节流缓冲，会触发 receive_capacity。现在按缓冲容量分段交给原解析器，整个数据报接受后才确认。
- 结束后新心跳仍产生发送，且应用队列清空不能证明 UDP 已交付。EndAck 入队后停止新探测，退出同时等待应用队列和 UDP 未确认包；超时明确失败。
- 服务端收到 EndAck 后立即关闭，可能无法重发丢失的 UDP 交付确认。现在区分应用确认与传输退出等待，UDP 收齐确认后保留接收约 1 秒，外层结束期限仍有上界。真实 run/close 用例分别丢弃第一次 EndAck 数据和第一次交付确认，验证重传后正常退出。
- Host 在两次服务端调用之间收到最后确认时，可能已经结束却返回 end_acknowledged=false。现以已完成退出等待的结果确认收齐，原 TCP 回归捕获的问题已修复。

首轮检查还纠正了测试对 read_checkpoint、token API 的错误引用。大快照归约器最初把全部填充状态作为规范摘要，违反独立的摘要预算；现明确使用可序列化的大状态和独立短摘要，真实验证 1 MiB 原点与等待权威帧的容量退化路径，没有放宽生产预算。短恢复测试最初把总期限设为 3 秒、单次握手保留 5 秒；改为明确的单次 0.3 秒，使恢复在服务端 0.4 秒空闲检测后有重试时间。没有改变生产默认值或虚构网络拒绝反馈。

## 验收证据

Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0。新增 UDP 15 项，以及原有多人/菜单 38 项，先完成 53 项局部回归；最终重新执行下列两组归档。均无失败、错误、跳过、受监控资源告警或测试拥有的线程残留；196 项归档另记录子进程与目录锁描述符残留均为零。23 个生产路径额外通过 Python 3.9 AST 检查，没有执行 Python 3.9。

| 当前归档 | 用例 | 源码指纹 | 本轮执行 |
| --- | ---: | ---: | --- |
| python-multiplayer-udp-windows-20260910-a | 196 | 77 | 是 |
| python-multiplayer-udp-network-windows-20260910-a | 219 | 41 | 是 |
| python-save-recording-windows-20260910-a | 129 | 28 | 否，源码及日志仍匹配 |
| python-multiplayer-identity-files-windows-20260910-a | 两组文件读取测量 | 16 | 否，导入源码指纹仍匹配，输入未改 |

196 项包含新增 15 项与既有 181 项。新增覆盖全部 Ready、无大厅预测、终点预测回退、两位玩家实际 7 帧 run/close、保存/录制/独立回放、最大快照故障传输、大厅/比赛客户端单边断线后复用原 token/引擎/槽位、新 epoch 与旧包拒绝、初次/恢复身份不符时零次非法恢复、无效原点工厂前拒绝、512 字节缓冲、持续 EndAck 丢失时的期限、v3/v4 双向拒绝、参数前置验证、真实 Host/Join 菜单及公开 UDP 服务循环。

1 MiB 原点故障比赛实测 5 帧，55 次丢弃、44 次重复、37 次重排，最大数据报 1200 字节；从玩家开始连接到最终结束确认共 4.423024 秒。219 项共享网络回归中的原始 1 MiB 恢复测量约 2.244923 秒、54 次丢弃、44 次重复、37 次重排。两者范围不同，均为本地功能证据，不是原生、广域网或性能提升结论。

源码、报告和日志 SHA256 已逐项核对。聚合证据：[python-multiplayer-udp-evidence-20260910.json](../optimization/benchmarks/python-multiplayer-udp-evidence-20260910.json)，SHA256 `cd2297f852357cd97205d8f1b2487516db86dffc256b86a6cd9a4e7bd25ae2a3`。

- 196 项报告：`334a0464ad01adb62ffb23cafcefa7baa6a2a8b03f99597f193a418e7987e4dd`；日志：`2bb6bba5d4a18fd825bd462560aa2174b20fa2f58fe3c3fb7a304bb5a59332c7`。
- 219 项报告：`1b8b7c11464a951ef868d46d23939da74e02cbef199432cf83069f900f99894c`；日志：`85cbe3fffcb510309e41103336b7d98ae42fd97e453e47929d9a5b461af4d974`。
- 129 项报告仍为 `131be1fd3fcfb2bb5bc6e37c7d228447ee08b4bd8ff2512b4a6f2426779eff6a`；文件读取报告仍为 `e1559093ede7986bf9c78da900069fc5488ecb3cd40742e76bdbf1cfda1834be`，本轮均未重跑。

上一轮多人 b181 与网络 a219 因源码变化过期，保留历史记录，不能当作当前源码通过证据。`main_menu --help` 本轮实际退出 0，显示 TCP/UDP 选项。

## 后续工作

新增 NativeMultiplayerUDPTest 复用相同真实 GameEnv 多人验收步骤，使用实际 UDP 构造三个引擎、推进、结束和原生回放。加上既有库身份、本地比赛和 TCP 多人，比赛检查的 `--native` 分支要求 4 项，全部尚未执行。WSL 原生命令执行问题本轮没有新的诊断假设，未重复超时探测；也没有假造 GameEnv 导入、抽取类体或把归约器结果当原生证据。

下一步审查直接原生引擎创建的资源分配准入，补齐 Core 池之外的所有权和容量；之后继续真实引擎/C++ v4 互通、自然结束、SDL 输入与渲染、POSIX 文件、长时内存/性能、手感、AI 和发布门禁。当前没有整个进程 RSS 上限、原生并发实例预算或广域网/来源认证通过结论。

本轮未执行 Git 操作、C++ 修改或构建、安装、WSL 重置、正式门禁绕过或子代理；原始基线及优化指针未改。
