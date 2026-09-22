2026-09-13：当前 Python 比赛已升级为 [v7／50Hz](match_cadence_v7.md)。下文保留v5／v6历史记录；当前实现、存档和验收范围以上述v7文档为准。

<!-- 2026-09-10: v6 真实传输与屏障已接通，保留此前实施状态及格式。
# 比赛 v5：显式节拍契约

2026-09-10。TCP/UDP 比赛层现在使用 v5。初始连接和恢复都要求服务器提供完整节拍，客户端验证后回传相同参数，服务器确认一致才释放 Ready 屏障。支持集合目前只有以下一组，参数不兼容时拒绝连接；不自动改物理步长或降级到 v4。

| 字段 | 固定值 | 含义 |
| --- | --- | --- |
| `input_hz` | 10 | 每秒模拟时间的输入采样数 |
| `network_hz` | 10 | 每秒模拟时间的权威帧数 |
| `physics_steps` | 10 | 每个权威帧调用的原生物理步数 |
| `physics_step_us` | 10000 | 一个物理步对应的微秒数 |

`MatchCadence` 是不可变值，JSON 只接受这四个字段及精确整数值，布尔、浮点、缺失、额外字段和其他频率均拒绝。一帧名义模拟时间为 100 ms；物理管线因比赛状态提前返回时，不据此承诺比赛计时器每次都增长 100 ms。

## 握手和恢复

1. 新连接发送 `VersionNegotiate(5, 5)`；恢复发送 `MatchReconnectRequest`，载荷是版本 5 和原 token。
2. 服务器发送 SessionStart、SlotAssignment；新连接额外发送 SessionToken。随后发送 StateSnapshot，内部标记是 `FMATCH5\0`。
3. 原点元数据严格包含 `settings`、`identity`、`sha256`、`digest`、`cadence`。原始状态仍最多 1 MiB，元数据仍最多 4096 字节，内部头仍为 12 字节。
4. 传输缓冲仅在完整快照和节拍通过验证后进入 ready。比赛所有者在创建引擎前再验证元数据，在恢复前核对身份、设置，恢复后检查规范摘要。
5. 客户端发送 MatchReady。服务器只接受与本地支持值完全一致的确认，之后才进入 streaming 或 handback。旧的一字节 Ready 会被拒绝；不完整确认不释放槽位。首帧仍要求全部配置槽位就绪。

MatchReady 的消息类型是 18，总长 13 字节，全部多字节整数采用小端序：

| 字节偏移 | 类型 | 内容 |
| --- | --- | --- |
| 0 | uint8 | 18 |
| 1 | uint16 | 比赛版本 5 |
| 3 | uint16 | input_hz |
| 5 | uint16 | network_hz |
| 7 | uint16 | physics_steps |
| 9 | uint32 | physics_step_us |

完整十六进制向量：`12 05 00 0a 00 0a 00 0a 00 10 27 00 00`。独立测试使用此字节向量，不用同一打包器生成预期值。

恢复时也要求相同节拍。改变参数的快照在进入原有引擎 `set_state` 前失败；不消耗原有恢复状态。UDP 的 cookie、epoch、排序、重传及各项容量上限保持原有语义，MatchReady 作为有界可靠字节流的一部分发送。

## 运行约束

比赛实时循环和 MatchReconnectingClient 的逻辑循环只接受 10 Hz。`FramePacer` 的比赛默认值、原生初始化的 physics_steps 和原生适配器的配置检查均读取同一个契约。原生适配器每次 `step_with_input` 前做所有者及配置检查，不进行文件重哈希；改变物理步数、渲染角色或分辨率会在推进前报错。

手动 `advance/tick/run_one_frame`、`realtime=False` 和离线回放可由调用方更快或更慢地执行，模拟帧定义不变。通用 v2/v3 客户端和服务端仍保留原有可配置速率。协议确认不承担时钟同步、网络时延保证或远端执行证明。实际输入边沿与慢帧调度见[固定节拍](frame_pacing.md)。

原生兼容性指纹新增 `match_cadence.py`，相关策略源码也已变化。因此以前原生版本产生的存档可能在实现身份比较处被拒绝；没有自动迁移。存档文件格式本身没有变更。

## 当前验证范围

新增 13 项必需检查：6 项契约/报文/分片/原生适配器边界及 7 项真实 TCP/UDP 连接、恢复和拒绝路径。引擎归约器及适配器夹具均明确独立于 GameEnv。实际原生测试还要求改变 physics_steps 后推进失败且规范摘要不变，该测试尚未执行。

```text
python -m unittest gfootball.frame_sync.test_match_cadence
python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --output <新目录>
```

C++ 通用 `protocol.hpp` 声明的版本仍是 2，其消息表与 Python 比赛扩展并非统一版本；本次没有实现或验证 C++ 比赛 v5 互通。真实原生步数、SDL 输入、暂停恢复、位置/相机插值、广域网及长期 p99 仍需验收，`fixed_timestep.ready` 保持 false。
-->

# 比赛 v6：显式节拍与控制原点

2026-09-10。TCP/UDP 比赛层现在使用 v6。初始连接和恢复均要求完整节拍与控制原点，客户端核对后回传确认。支持集合目前只有以下一组；不兼容参数或旧比赛版本拒绝连接，不自动改变物理步长。

| 字段 | 固定值 | 含义 |
| --- | --- | --- |
| `input_hz` | 10 | 每秒模拟时间的输入采样数 |
| `network_hz` | 10 | 每秒模拟时间的权威帧数 |
| `physics_steps` | 10 | 每个权威帧配置的原生物理步数 |
| `physics_step_us` | 10000 | 一个物理步对应的微秒数 |

`MatchCadence` 是不可变值，JSON 只接受这四个字段及精确整数值，布尔、浮点、缺失、额外字段和其他频率均拒绝。一帧名义模拟时间为 100 ms；物理管线因比赛状态提前返回时，不据此承诺比赛计时器每次都增长 100 ms。

## 握手和恢复

1. 新连接发送 `VersionNegotiate(6, 6)`；恢复发送 `MatchReconnectRequest`，载荷是版本 6 和原 token。
2. 服务器发送 SessionStart、SlotAssignment；新连接额外发送 SessionToken。随后发送 StateSnapshot，内部标记是 `FMATCH6\0`。
3. 原点元数据严格包含 `settings`、`identity`、`sha256`、`digest`、`cadence`、`control` 六个字段。`control` 严格包含 epoch/phase；下一帧号来自外层快照，控制校验值取规范摘要的前八字节，以小端 uint64 解释。原始状态仍最多 1 MiB，元数据仍最多 4096 字节，内部头仍为 12 字节。
4. 传输缓冲在完整原点及契约通过验证后进入 ready。比赛所有者在创建引擎前验证元数据，恢复前核对身份和设置，恢复后检查规范摘要并初始化控制契约。
5. 客户端发送 MatchReady。服务器要求节拍一致，且回传 epoch 同时等于该 Peer 的原点 epoch 与当前控制 epoch，之后才进入 streaming 或 handback。旧一字节 Ready 和旧版比赛确认均拒绝；首帧仍要求全部配置槽位就绪。

MatchReady 的类型是 18，总长 17 字节，全部多字节整数为小端序：

| 字节偏移 | 类型 | 内容 |
| --- | --- | --- |
| 0 | uint8 | 18 |
| 1 | uint16 | 比赛版本 6 |
| 3 | uint16 | input_hz |
| 5 | uint16 | network_hz |
| 7 | uint16 | physics_steps |
| 9 | uint32 | physics_step_us |
| 13 | uint32 | 原点控制 epoch |

epoch=0 的完整向量：`12 06 00 0a 00 0a 00 0a 00 10 27 00 00 00 00 00 00`。独立检查使用固定字节预期，并另验证非零 epoch；不使用同一打包器生成预期值。

恢复时重新核对节拍和控制状态。参数非法的快照在原引擎 `set_state` 前失败；原点过期的 Ready 不释放屏障，可由既有恢复流程重试同一会话。UDP 的 cookie、连接 epoch、排序、重传和容量限制继续独立生效，MatchReady 和控制消息使用同一个有界可靠字节流。

## 运行约束

比赛实时循环和 MatchReconnectingClient 的逻辑循环只接受 10 Hz。`FramePacer` 的比赛默认值、原生初始化的 physics_steps 和原生适配器的配置检查读取同一个契约。原生适配器每次 `step_with_input` 前做所有者及配置检查，不进行文件重哈希；改变物理步数、渲染角色或分辨率会在推进前报错。

手动 `advance/tick/run_one_frame`、`realtime=False` 和离线回放可以更快或更慢执行，模拟帧定义不变。通用 v2/v3 仍保留原有可配置速率。协议确认不承担时钟同步、延迟保证或远端执行证明。慢帧调度见[固定节拍](frame_pacing.md)，屏障和输入代次见[权威暂停恢复](match_control.md)。

原生兼容性指纹包含 `match_cadence.py` 及相关策略源码；旧实现存档可能因身份不同被拒绝，没有自动迁移。存档物理格式本身没有因临时控制代次而改变。

## 当前验证范围

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
节拍组共 13 项：6 项契约/报文/分片/原生适配器边界及 7 项真实 TCP/UDP 连接、恢复和拒绝路径；v6 暂停另增加 22 项接入检查。当前完整比赛/图形组 354 项通过，见[实施报告](../../.project/reports/optimization-pause-v6-progress-2026-09-10.md)。归约器及适配器夹具均明确独立于 GameEnv。
-->

节拍组仍为 13 项，v6 控制接入 22 项；本轮 Local/UI 暂停及逐帧校验回收再增 25 项。完整比赛/图形 379 项通过，见[实施报告](../../.project/reports/optimization-pause-ui-progress-2026-09-10.md)。原生适配器夹具和显示均明确独立于 GameEnv。

```text
python -m unittest gfootball.frame_sync.test_match_cadence
python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --output <全新目录>
```

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
C++ 通用 `protocol.hpp` 的版本仍为 2，其消息表与 Python 比赛扩展并非统一版本；本轮没有实现或验证 C++ 比赛 v6 互通。真实原生步数、Local/UI 暂停、SDL 设备、位置/相机插值、广域网及长期 p99 仍待验收，`fixed_timestep.ready` 保持 false。
-->

C++ 通用 `protocol.hpp` 仍为 v2，未实现或验证比赛 v6 互通。Local/Host/Join 暂停与图形命令已有实际协调证据；真实原生步数、暂停/HUD、SDL 设备、插值图像、广域网及长期 p99 仍待验收，`fixed_timestep.ready` 保持 false。
