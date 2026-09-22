# Python TCP 自动恢复与期限验收

归属：ms-21.1 → plan-21.1.2 → task-21.1.2.1，兼顾后续网络里程碑。状态：实施进展；`memory_budget.ready=false`，总目标保持 ACTIVE。

## 本轮实现

新增 `resume_protocol.py`、`client_reconnect.py`、`test_reconnect_budget.py`、`test_reconnect_native.py` 和 `.project/checks/python_reconnect_probe.py`。公开 `client.py` 现在导出新恢复包装器，旧阻塞/新会话替代实现保留为带日期和原因的注释。修改 `client_tcp.py`、`client_logic.py`、`server_runtime.py`，没有修改 C++ 或 UDP 包装器。

- Python 服务端显式协商 v3 后在初始元数据后签发随机非零 64 位 SessionToken。普通 v2 流程保持兼容，server-first 也可随后显式协商 v3。未改全局 v2 常量，C++ 尚未实现此新增签发消息。
- TCP 客户端新增有界恢复解析器。原 seed、双方槽数、分配槽及已确认帧下界必须匹配；声明大小在分配前验证。1 MiB 快照经最多 4096 字节的实际读取分块接收，固定 bytearray 之后转不可变 bytes。转换期间两份载荷都有明确上限；保留字节数包含对象头。
- TCP 连接建立改为非阻塞 connect/select，最多尝试 DNS 返回的前 8 个地址。关闭可取消 socket 建立和握手，实际 descriptor 由 I/O 所有者在操作退出后释放。DNS 仍为同步 OS 调用；它若迟迟不返回，不创建替代线程。
- 恢复所有者只有一个后台线程、一项在途尝试和一个候选连接。默认首次立即尝试，失败后 1 秒起退避、最多 30 秒、10 次尝试、整次 60 秒。`max_attempts=0` 仍受总期限限制；不会计算无界指数或无限向执行器提交任务。
- 逻辑线程通过 `attach_logic(env)` 和 `run_one_tick()` 自动恢复实际传入的引擎，创建正确下一帧编号的新 ClientLogicLoop，然后发送 Ready。收到所有自有槽位的 Handback 后才报告成功和恢复推进。
- 恢复中服务器继续推进，客户端按序补齐快照后的权威帧和哈希。普通网络故障可重试，非法权威帧、身份/快照错误、逻辑或恢复失败终止；give-up 后的 tick 不重启尝试，异常回调也不重新安排自己。
- 关闭手动驱动的逻辑循环会清理历史、哈希、已采样输入和时间戳，不依赖未来再来一次 tick。活动回调退出时完成退款，活动快照在引擎恢复期间及同时关闭时仍计费。
- 期限贯穿连接和快照，并覆盖 Ready/Handback 阶段。期限已过时不建立连接、不调用引擎恢复。引擎调用与用户回调本身不能被强制终止或保证硬实时。

接口与边界见 [frame_sync_reconnect.md](../../gfootball/doc/frame_sync_reconnect.md)。原生旧握手提供 `set_session_token()` 绑定宿主取得的真实令牌；这个协议路径目前只用真实 Python TCP 服务验证，不能据此宣称 C++ 联调通过。

## 当前通过的证据

```text
python .project/checks/python_reconnect_probe.py --output .project/optimization/benchmarks/python-reconnect-windows-20260910-d
```

**201/201 通过**：7 项恢复解析、4 项真实 TCP 快照传输、16 项自动恢复；完整重跑之前服务端/客户端/逻辑/展示 121 项，以及 UDP 专项 53 项。旧 UDP 86 项中的共用解析/逻辑 33 项已包含在这 121 项中，不重复相加。

- 原生 socket 实际传输最大 1 MiB 快照，验证内容完全一致、分块接收与释放；超大声明、截断等待、过期连接和错误元数据均拒绝。
- 自动收到真实随机令牌；断线时服务器在快照之后继续推进 3 帧；客户端先在所属线程恢复，再确认 Handback，逐帧补齐并校验 3 个哈希，随后另 5 帧仍一致。引擎为明确独立的 Adler32 归约器，没有冒充 GameEnv。
- 实际重复断线恢复 5 次，每次旧 I/O 线程退出，服务端只留一个已连接客户端。
- 一次真实在途恢复握手停滞时，1000 次 tick 的总耗时小于 150 ms，显式关闭小于 500 ms 且线程已退出。这是本地回归上限，不是目标硬件延迟或引擎 restore 性能承诺。
- 3 次拒绝连接后 give-up 只通知一次，后续 1000 次 tick 不重启；另覆盖失败回调、引擎恢复失败、逻辑错误、错误权威帧、所有权线程、关闭时预测退款、活动快照计费以及 deadline 在 UI/后台边界过期。
- 没有 skips、失败、错误、观察到的资源/线程/异步警告或残留自有线程。

当前报告：`.project/optimization/benchmarks/python-reconnect-windows-20260910-d/report.json`

- report SHA256：`fcea50abdc62f9e4bcf20be80e7a227eaddbe675f954e54ff6b807771231c298`
- tests.log SHA256：`ae67b2a0bcc696fcefb0bb6b33cd65d7bd1589fe21de361688c02b792de149d4`
- 36 个本地依赖/检查文件及读取的 C++ UDP 头文件有源码指纹，当前匹配。
- Windows 11、Python 3.14.6；六个相关生产文件执行了 Python 3.9 语法解析，未运行 3.9 解释器。

## 保留的失败和复验

开发阶段补强成功语义后，原测试仍期待 Ready 入队即触发成功；已改成实际等待并验证 Handback。扩展测试时发现一个状态机测试片段被误置到 socket 测试类，以及初始 Ready 尚未真正送出就主动断线的 fixture 竞态，均修正后验证。

归档 a 为较早的 198 项通过结果。归档 b 的 199 项中，一项关闭测试在 Windows 收到 `ConnectionResetError(10054)`，当时 fixture 只接受 EOF；取消带未读握手数据的连接允许 reset，现测试接受 EOF 或该明确异常，其他异常继续失败。归档 c 的 199 项通过；随后增加期限边界两项，最终 d 的 201 项通过。保留全部归档，不将重复执行累加为新增覆盖。

服务端模块改动使旧 frame-replay 64 项归档的导入指纹过期，已重跑：

```text
python .project/checks/frame_replay_probe.py --output .project/optimization/benchmarks/frame-replay-windows-20260910-b
```

64/64 通过，39 个源码指纹当前匹配，无资源/锁描述符/自有线程/跟踪进程残留。

- report SHA256：`c615901f406a306a9f8cc9ff11323758217b5b07389ef90e9ace39b9aafa0968`
- tests.log SHA256：`279e3bad0f69c39b882e88ede479c2bd879664cd949d38fc11ad730aba13bb63`

环境流式回放 `python-replay-windows-20260909-b` 的 108 项、24 个源码仍匹配，本轮未重跑。旧 server121、UDP86 的部分指纹因本轮修改已过期，其受影响测试由当前 201 项完整覆盖，不继续标注旧归档“源码当前”。原始性能基线及优化基线指针没有变化。

## 仍需推进

本轮没有再次执行已证实无效的 WSL 启动探测，也未重置 distro、VM、服务或接管其他进程。原生执行入口仍缺少恢复证据；有用的 Python 工作继续进行，所以不将总目标标为 blocked。

新增 `test_reconnect_native.py` 使用真正的 GameEnv 和 Python 原生服务，计划验证 5 人控帧、3 接管帧和恢复后 5 帧，共 13 帧以及恢复后的 8 个确认哈希。`python_reconnect_probe.py --native` 还包含原有 2 项 GameEnv 服务端测试。这三项均未执行，不计入 201 项。

下一步仍包括 UDP 自动恢复与快照协议、C++ 双向排序/去重和令牌签发、真实 GameEnv 联调、产品房间和场景信息接入、引擎池及通用保存预算、真实比赛录制/UI 和全部原生内存验收。之后继续内存增长/性能、手感、完整网络、渲染、AI 和发布里程碑。没有用局部通过代替产品级质量，也没有执行 Git、C++ 编译、安装包或绕过 Windows 正式验收入口。
