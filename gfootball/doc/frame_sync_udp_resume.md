# UDP 会话恢复

2026-09-22 更新：恢复终止先进入 giving_up 清理阶段；tick() 或 stats() 确认后台所有者实际退出后才发布 gave_up。终止回调仍由逻辑线程派发一次，清理期间不重试，状态观察不等待线程。 按序 ACK 模式的 due() 只调度 pending 前 64 项，并仅从未重传的首项探针采样 RTT；客户端直接首次发送不受此调度窗口限制。协议及既有期限不变。

以下为原有协议和使用说明。

2026-09-10。`ReconnectingFrameSyncUDPClient` 现在使用显式的 cookie/epoch 协议，配套服务端为 `gfootball.frame_sync.server_udp.FrameSyncUDPServer`。现有 C++ UDP 服务不支持此协议；原始 `FrameSyncUDPClient` 仍用于旧协议的初始会话。

## 使用与生命周期

```python
from gfootball.frame_sync.server_udp import FrameSyncUDPServer
from gfootball.frame_sync.client_udp import ReconnectingFrameSyncUDPClient

server = FrameSyncUDPServer('127.0.0.1', 12345)
server.start()  # 默认构造实际 GameEnv，需要原生运行环境。

client = ReconnectingFrameSyncUDPClient('127.0.0.1', 12345, sample_owned_inputs)
session, slots = client.connect()
client.attach_logic(replica_env)  # 调用方先初始化相同场景的真实引擎。
client.run_one_tick()             # 比赛循环持续调用此入口。

client.close()
server.stop()
```

示例中的 `sample_owned_inputs` 和 `replica_env` 由比赛层提供；复制引擎仍由调用方关闭。服务器 `run_one_frame()` / `run_loop()` 的用法与 TCP 服务一致。异步集成可直接使用 `UDPServerRuntime`，所有操作及原生引擎调用必须留在它的事件循环和线程。

初次 `connect()` 是阻塞 API。恢复尝试由一个后台所有者执行，另有一个实际 UDP I/O 线程；逻辑帧不会执行网络连接、重连等待或后台线程 join。恢复期间旧逻辑停止，完整快照在逻辑线程应用，然后发送 Ready。收到所属槽位的 HandbackNotify 后才报告恢复成功、恢复逻辑推进。引擎与回调自身的执行时间不能被强制中断。

恢复使用最初服务端发出的 token，并核对原会话、槽位和已确认帧下界。不会以新比赛替代旧比赛。UDP 本地关闭不会通知服务端；服务端根据业务空闲期限或可靠传输失败释放旧连接，期间重连请求可能失败并按总期限重试。默认空闲期限为 3 秒，自动恢复总期限为 60 秒、最多 10 次尝试。单调时钟、候选快照容量、逻辑线程所有权和终止语义沿用 [TCP 恢复说明](frame_sync_reconnect.md)。

## 数据报格式

所有整数为小端，协议固定 IPv4，数据报最多 1200 字节。

| 数据报 | 格式 | 长度 |
| --- | --- | --- |
| HELLO / CHALLENGE / CONFIRM / WELCOME | `<BQI16s>`：类型、非零 uint64 epoch、时间桶、cookie | 29 字节 |
| ENVELOPE | `<BQ>`：`0x74`、epoch，随后一个 DATA 或 ACK | 10–1200 字节 |
| 内层 DATA | `<BIH>`：`0x00`、uint32 序号、载荷长度，随后载荷 | 应用载荷最多 1184 字节 |
| 内层 ACK | `<BI>`：`0xff`、uint32 序号 | 内层 5 字节 |

握手类型依次为 `0x70`、`0x71`、`0x72`、`0x73`。HELLO 的时间桶和 cookie 必须为零。每次连接生成新 epoch。服务端 cookie 为随机密钥 HMAC-SHA256 的前 16 字节，绑定 IPv4 地址、端口、epoch、时间桶；默认桶宽 30 秒，只接受当前和前一桶。

客户端必须返回有效 cookie，服务端才分配 Peer。HELLO 的响应与请求同为 29 字节；所有 cookie 请求共享固定大小的速率预算，默认 1000 次/秒、突发 128 次。重发有效 CONFIRM 只重发 WELCOME，不能重置活跃连接序号。同地址的不同 epoch 不会替换活跃连接。默认最多记录 1024 个已准入 epoch；未过期记录不能因容量不足而被淘汰，容量不足时拒绝新准入。活跃连接记录不会被过期清理移除，刷新 cookie 会延长防重放期限。

地址验证用于限制未验证源的资源分配与响应放大。它不提供加密、服务端身份验证或抵御链路内攻击者的能力。token 仍是现有 uint64 会话能力；公网身份认证与传输加密尚未完成。

## 快照、背压与限额

cookie 握手后，内层可靠字节流使用 v3 SessionToken / ReconnectRequest / StateSnapshot 协议。服务端复用 TCP 的解析、槽位输入窗口、bot 接管、快照和 Ready 流程，只替换收发与 socket 关闭钩子。

新协议在载荷按序交付后发送 ACK。先到的未来片段保留在接收队列中，不提前确认；因此缺失片段会保留发送端背压，避免大快照继续推进并撑满接收窗口。已交付的重复包重新 ACK，不再次交付。旧协议继续使用原来的接收确认方式。uint32 序号恰好相差半个序号空间时明确拒绝。

每个服务端输出消息按需切成最多 1184 字节的片段，不预建片段列表。整个活动输出仍计入应用输出预算，可靠层另外计入未确认片段；发送队列满时等待容量，保留原始入队期限。默认快照最多 1 MiB、应用输出 2 MiB、可靠层发送和接收各 256 包 / 256 KiB。自定义两端限额时，接收容量必须覆盖对端发送窗口；目前没有在线容量协商。

服务端使用一个 UDP socket、一个 I/O 任务及原有维护任务。每轮接收最多 64 个数据报，每个连接最多调度 64 个到期发送，然后让出事件循环。Peer 关闭只释放该连接的队列与任务，全部 Peer 退出后才关闭共享 socket。客户端关闭也等待唯一 I/O 所有者退出。DNS 仍调用同步系统解析器；没有为超时解析创建遗留辅助线程。

## 验证范围

```text
python .project/checks/python_reconnect_probe.py --udp-resume --output .project/optimization/benchmarks/new-udp-resume-run
```

输出目录必须不存在。Windows Python 3.14.6 的当前归档包含 219 项检查，其中 18 项为本次 UDP 新增检查，其余 201 项覆盖 TCP、逻辑、表现层和旧 UDP 回归。真实 socket 故障代理在 1 MiB 快照中丢弃 56 次首次发送、加入 45 次重复和 39 次乱序，完整恢复用时约 3.32 秒，最大数据报为 1200 字节。还验证了连续三次恢复、快照后的连续权威帧及哈希、逻辑线程恢复、控制权交还、1000 次非阻塞 tick、未确认大快照超时回收和 cookie 等待中关闭。

原生环境可用后追加 `--native`，必须实际运行 GameEnv；新增 UDP 原生用例没有替代引擎或 skip 分支。当前上述 219 项中的引擎部分使用明确的独立状态归约器，不构成 GameEnv 验收。新协议与 C++ UDP 服务互通、WAN/拥塞控制、容量协商、实际网络性能和整机长期内存增长仍待完成，`memory_budget.ready` 保持 `false`。
