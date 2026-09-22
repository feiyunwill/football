# Python UDP 有界传输与实际客户端验证

归属：ms-21.1 → plan-21.1.2 → task-21.1.2.1。状态：实施进展，`memory_budget.ready=false`，未通过整体内存或网络验收。总目标继续 ACTIVE。

## 实现与影响

- 新增 `udp_state.py`、`udp_transport.py`、`client_udp_runtime.py`。公开 `client_udp.py` 导出新实现，原实现按仓库规则保留为带日期和原因的注释。
- 可靠 DATA/ACK 格式、1200 字节数据报上限与当前 C++ 常量一致。发送容量可恢复，收到 ACK 释放实际持有字节；uint32 序号回绕、有限接收窗口、按序单次投递、重复冲突检测、缺口与交付期限、重传耗尽整体关闭均有检查。
- 发送与接收默认各 256 包 / 256 KiB，历史摘要 256 条，RTT 32 条。计费包括不可变字节对象头；活动回调直到返回才退款。时间使用单调时钟，RTT 使用 Karn 规则，统计计数饱和。
- FrameSyncUDPClient 只有一个非 daemon I/O 线程；Connected UDP 过滤其他源端点。复用既有 ClientBuffers 和 BufferedClientAPI，统一队列预算、协议错误、输入所有权、连续帧与哈希验证。旧连接回调不能向下一代连接发送。
- 关闭不会在 select/recv 尚未结束时释放 descriptor；握手超时、取消、重传失败、显式关闭均清理并 join。正在持有的临时数据报引用在空闲等待前释放。OS DNS 和调用方回调本身不能被强制打断。
- `test_e2e_udp.py` 原先缺少 authority/hash/heartbeat 也返回成功，且 heartbeat 使用初始化时间作为证据。现改为必须实际观察三类数据。CLI 使用一场连接，避免历史服务器保留槽位造成下一项测试无槽可用；单项外部检查各要求新比赛/新服务。收到哈希不表示已验证 GameEnv 的 canonical digest。

具体接口、限额和使用边界见 [frame_sync_udp.md](../../gfootball/doc/frame_sync_udp.md)。

## 可复现证据

命令：

```text
python .project/checks/python_udp_probe.py --output .project/optimization/benchmarks/python-udp-windows-20260910-a
```

- 86/86 通过：18 项状态机，9 项独立 socket 通道，26 项实际 UDP 客户端/CLI/逻辑集成，7 项共用帧解析器回归，26 项既有逻辑预算回归。没有 skips、失败、错误、观察到的资源/线程/异步警告或残留自有线程。
- 实际双向 UDP 测试每方向 40 个载荷，首份 DATA 和 ACK 按固定规则丢弃，批量逆序并重复注入；最终载荷按序各交付一次，未确认和接收载荷全部退款。这是 loopback 的确定性故障注入，不是 WAN 性能测量。
- 实际客户端有 40 个连续权威帧的丢包/重复恢复、22 槽位输入与权威字节比对、30 次连接退出、内核源过滤、超长报文、连续性/非法数量/NaN、哈希容量与冲突、应用背压、缺口超时、心跳存活、取消握手和回调换代隔离。
- UDP+ClientLogicLoop 使用已有独立整数 reducer，实际经历三帧回滚并校验三个确认哈希，发送输入与初次预测的输入字节一致。它没有使用或冒充 GameEnv。
- CLI 正例实际收到 10 帧/哈希/心跳；分别缺失其中任一类时测试都确认失败。
- 首轮开发检查遇到 C++ 源文件被 Windows 默认 GBK 解码的错误，测试改为显式 UTF-8 后通过。中间 26/45/51/26 的重复执行不是新增覆盖，不与最终 86 相加。

当前归档：`.project/optimization/benchmarks/python-udp-windows-20260910-a/report.json`

- report SHA256：`b44f0f790a47a9e9d666bd1a42524826bc374df869a8e29e02963796da586ed2`
- tests.log SHA256：`94e0a5c407a6c22b1ceb5fb307de186cbe9aa9017a4ba3159b8eaa2c1660bc22`
- 26 个实际导入本地源码/读取的 C++ 头文件均有哈希，当前内容与归档匹配。
- 实际平台 Windows 11 / Python 3.14.6。五个相关生产/CLI文件通过 Python 3.9 语法解析，Python 3.9 运行时没有执行。
- 前次 frame-replay 64 项的 38 个源码、Python server 121 项的 23 个源码、环境 replay 108 项的 24 个源码仍与原归档匹配，本轮未重跑这些整套检查。共同的少数解析/逻辑用例本轮另列，不累加为独立覆盖。

## 原生执行环境与待完成工作

两次有界新假设探测已归档：本地 Windows cwd 启动 `/usr/bin/true` 以及让 WSL 命令在项目内写标记。二者都在 12 秒超时，标记未产生。每次只停止本次带唯一标签的一个子进程及其父启动器，最终匹配进程 0。内核、UNC 文件与代码索引仍可访问，但该事实不能代替原生命令执行。没有重置 distro、VM、服务或接管用户终端。

没有修改 C++、没有编译、没有安装包、没有 Git 操作，也没有绕过 Windows 正式验收入口。基线和优化基线指针不变。

以下工作仍必须完成：

1. 原生 UDP 接收排序/去重、服务端输入时序、连接保留与限流，及真实 C++/GameEnv 双向故障验证。
2. 自动重连改为有界后台尝试、单调退避、终止状态稳定、完整关闭；token 发放/校验、快照恢复和 Ready 交接完成后才能宣布恢复原比赛。旧 TCP/UDP 包装器仍在 UI tick 中阻塞并建立新会话。
3. 现有 UDP 服务没有大快照分片恢复协议，不能把 1200 字节数据报上限放大来替代设计与验收。
4. 引擎池及通用保存对象预算、比赛帧回放接入真实比赛录制/UI、原生环境回放/目录 POSIX/最大长度持久化等内存任务；然后运行整体 memory_budget 与增长/性能验收。
5. 后续手感、网络完整契约、渲染、AI 和发布里程碑继续按原计划推进。局部队列和 loopback 测试不是整体产品质量完成证明。
