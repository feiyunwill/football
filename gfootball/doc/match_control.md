<!-- 2026-09-10: v6 真实传输与屏障已接通，保留此前实施状态及格式。
# 权威暂停恢复：客户端执行原语

2026-09-10，ms22 → plan22.1.2 → task22.1.2.1。已实现控制格式、客户端边界执行和图形输入冻结；现有比赛仍协商 v5，尚未接通联机暂停。以下接口需要后续 v6 服务端与传输适配器显式启用。

`match_control.py` 定义不可变 `MatchControl(epoch, phase, next_frame, state_hash)`，控制字段严格校验类型、范围、顺序和字节长度。RUNNING → PAUSED → RESUMING 分别递增代次；同代次的 RUNNING 提交完成恢复，禁止直接跳过准备。控制/确认消息包含权威边界和 uint64 摘要，新输入格式携带代次。旧代次的拒绝仍须由后续服务端实现；格式转换后还要经过既有 FrameInputWindow 的槽位、数值、重复与容量校验。

`ClientLogicLoop.initialize_control()` 只允许在尚未采样的会话原点绑定控制契约，并验证引擎帧号及摘要。默认通用客户端和 v5 比赛不调用此接口。逻辑所有者读取控制状态，IO 所有者不访问引擎。

收到暂停后先停止新输入、重试和预测，在原有每 tick 预算内处理边界之前的权威帧。越过边界的预测通过已有快照回退；核对规范摘要、清空作废的预测与输入、通知输入所有者后，才发送确认。确认摘要的历史保留原有预算，用于处理尚未消费的延迟 hash。缺失回退快照、摘要错误、非法顺序或确认队列拒绝均关闭该客户端，不带着不一致状态继续比赛。

RESUMING 阶段继续冻结。RUNNING 提交在边界验证后由 `commit_control()` 消费本地记录，不发送额外线上 ACK，随后才能重新采样。传输的 `get_match_control()` 必须返回首条尚未应用的控制；不能用最新值覆盖中间提交。客户端传输接入时需要至多两条控制记录的有界存储，支持同批到达的恢复提交与下一次暂停。该存储和服务端 ACK 屏障尚未接入运行中的比赛适配器。

`InputBuffer.set_suspended(bool)` 清空方向和待消费操作边沿。暂停中仍可保存、退出，命令的边沿语义保持独立。恢复要求 UI 在获得焦点时观察到一次无游戏操作的输入，再允许新操作：持续按住的键、互相抵消的方向键、手柄按钮、方向键和死区之外的摇杆都不能被当成释放。保存/退出键不妨碍这次释放观察。已发送输入在原代次中保持不可变；只有控制屏障明确废弃后才能在新代次重新采样该帧号。

暂停发布权威回退快照并标记展示历史中断。之后空闲 tick 不重复序列化或发布相同快照，连接检测和 hash 消费继续工作。该行为由实际 ClientLogicLoop、LogicStateHolder 和 InputBuffer 检查；引擎为明确的独立测试状态机，不是 GameEnv。

```text
python -m unittest gfootball.frame_sync.test_match_control
python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --output <全新证据目录>
```

35 项新增检查分为格式 9 项、逻辑 19 项、输入 7 项。模拟长暂停检查 1000 次逻辑 tick 内无额外步进或重试，另检查 100 次空闲 tick 无重复快照；这不是实际设备、长时间运行、RSS 或输入到显示延迟测量。

下一步按[实施约束](../../.project/optimization/pause-protocol-design.md)接入 v6 原点/Ready、控制收件队列、服务端暂停和恢复屏障、输入代次校验、ACK 超时与断线恢复，再接通 Local/Host/Join 和图形反馈。新暂停按键、真实 TCP/UDP 暂停、原生物理及图像、设备手感和性能验收均未完成，相关 ready 标志继续为 false。
-->

# 比赛 v6：权威暂停与恢复

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
2026-09-10，ms22 → plan22.1.2 → task22.1.2.1。Python TCP/UDP 比赛已接通暂停屏障、恢复提交、输入代次、确认期限与原会话恢复。当前真实 socket/文件证据使用独立测试引擎；LocalPlayer 暂停、新界面按键及真实原生/设备验收继续待完成。
-->

2026-09-10，ms22 → plan22.1.2 → task22.1.2.1。Python TCP/UDP v6 屏障、Local 权威暂停、终端/图形操作和 Host/Join 状态反馈均已接通。真实 socket/文件与窗口协调检查使用独立测试引擎/显示对象；原生 HUD 和键盘绑定已有源码，真实 GameEnv、SDL 设备与画面验收仍待完成。

## 所有者接口

已启动的 `HostedMatch` 提供 `set_paused(bool)`、`pause()` 和 `resume()`；调用必须来自比赛所有者线程。直接嵌入服务端可使用 `MatchServer` 或 `MatchUDPServer` 的同名接口。返回值是当前不可变 `MatchControl(epoch, phase, next_frame, state_hash)`，不保证请求返回时所有客户端都已确认。

若权威帧已经开始收集，先完成该帧，再建立暂停边界。等待期间主机仅保留最新暂停意图；继续调用玩家 `tick()` 或主机 `advance()`，使控制确认、心跳和恢复能够进行。暂停时 `HostedMatch.advance()` 返回 false，服务端公开 `run_loop()` 也停止物理推进。直接 `run_one_frame()` 在暂停中报告 `match_paused`，不会因此关闭健康服务。

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
`NetworkPlayer(..., on_control=callback)` 和 `HostedMatch(..., on_control=callback)` 在玩家逻辑所有者上通知控制变化。Join 接收和确认权威状态，目前没有向 Host 请求暂停的线上命令。图形 Host/Join 已把此通知绑定到输入冻结与等待状态；图形界面尚无暂停请求入口。
-->

`NetworkPlayer(..., on_control=callback)`、`HostedMatch(..., on_control=callback)` 和 `LocalPlayer(..., on_control=callback)` 在比赛逻辑所有者上通知控制变化。图形入口绑定输入冻结与画面状态，终端菜单打印去重后的控制提示。Local/Host 可按 K 或图形手柄 Guide 暂停/恢复；Join 显示主机暂停状态，其暂停键不能改变权威比赛。保存和退出继续独立工作。

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
## 协议与状态
-->

## 本地同步边界

`LocalPlayer.set_paused(bool)`、`pause()` 和 `resume()` 只由比赛所有者调用。当前输入采样或帧回调中提出的请求，在该权威帧与副本完成后生效；控制回调中的递归暂停/推进明确拒绝。暂停时 `step()` 返回 None，不采样、不推进、不重复快照；实时循环继续读取命令，暂停 tick 不消耗帧数上限。初始与续玩创建新的 RUNNING 控制原点。

Local 仍使用专属的同步 TCP 服务与副本，不预测，也不运行独立自动权威循环。每次推进后等待并消费对应 StateHash，再核对双方完整摘要，因此控制边界前没有未完成的本地输入或校验消息。暂停核对同步帧号/摘要并清空未来输入；恢复在同一所有者上完成 RESUMING 和 RUNNING 通知。它不通过通用 v2/v3 连接发送 v6 控制消息，也不调用原生物理 `pause/resume`。

## 协议与状态

比赛显式协商 v6，初始和恢复原点使用 `FMATCH6\0`，严格元数据新增 `control` 的 epoch/phase。17 字节 MatchReady 回传节拍与原点 epoch；过期确认被拒绝，已有客户端可使用原 token 重试原会话。具体字节格式见[节拍契约](match_cadence.md)。

| 阶段变化 | 代次 | 行为 |
| --- | --- | --- |
| RUNNING → PAUSED | 加一 | 封住权威边界并清空后续输入窗口，等待在线玩家确认 |
| PAUSED → RESUMING | 再加一 | 保持同一物理状态，等待在线玩家确认恢复准备 |
| RESUMING → RUNNING | 不变 | 广播提交后允许新输入和物理帧 |

控制消息 19 长 18 字节；确认消息 20 长 17 字节；输入消息 21 包含 11 字节头和每槽 12 字节。多字节整数为小端。控制确认绑定 epoch、下一帧号和规范状态的 64 位校验值；此值用于一致性检查，不提供远端身份认证。

新输入必须携带 epoch。服务端对旧 epoch 输入先执行结构、槽位所有权和数值校验，再丢弃；未来 epoch、当前暂停状态输入及旧格式输入被拒绝。恢复后可以在新 epoch 重新采样相同帧号，同一 epoch 内已发送输入仍不可变。UDP 的 cookie/连接 epoch 与比赛控制 epoch 分开管理。

## 客户端边界与输入

`ClientLogicLoop.initialize_control()` 在初始或恢复原点核对帧号和规范摘要，之后才发送 Ready 或采样。大厅通过同一逻辑循环处理控制和不可变首帧输入，尚未收到权威帧时不预测。通用 v2/v3 客户端不启用比赛控制契约。

收到屏障后先停止新预测，在每 tick 原预算内处理边界前的权威帧，撤销越界预测，核对规范摘要并清空作废输入与重试记录，再确认。历史中的延迟 hash 仍按原有预算消费。RESUMING 保持冻结；逻辑应用 RUNNING 提交后才重新采样。协议/摘要失败明确关闭客户端，控制处理期间的实际断线沿用自动恢复流程。

IO 缓冲最多保留两条待消费控制：一条 RUNNING 提交和紧随其后的一条屏障。逻辑读取首条尚未应用的记录；ACK 被可靠发送队列接纳后才消费屏障，RUNNING 仅本地消费，不发送额外线上确认。重复消息不会跳过新的屏障。同批到达的提交、再次暂停或权威帧保持有序。

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
`InputBuffer.set_suspended(bool)` 清空方向和待消费操作边沿，暂停中保存/退出命令继续有效。恢复后必须先在有焦点时观察一次无游戏操作的输入，再接受新操作。持续按住的键、相互抵消的方向键、手柄按钮/方向键以及死区外摇杆均不能充当释放；保存/退出键不妨碍中立观察。暂停发布权威回退和展示历史中断，空闲 tick 不重复序列化相同快照。
-->

`InputBuffer.set_suspended(bool, reset=False)` 清空方向和待消费操作边沿，暂停中保存/退出有效。恢复必须先观察有焦点且无游戏操作的输入，再接受新操作；持续按住、相反方向组合和死区外摇杆都不能充当释放。K、Guide、保存/退出不妨碍中立观察。图形同阶段重连以 reset=True 清理旧输入，首次启动不强制清空新按键。暂停发布一次状态变化，空闲 tick 不重复序列化相同快照。

## 期限、恢复与保存

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
每个在线 Peer 只保留一个待确认屏障，期限为 `min(3 秒, ready_timeout)`；心跳不会延长期限。超时或断线按已有 AI 接管政策移除该参与者，剩余玩家可以继续完成屏障。恢复时核对新原点的控制状态，确认后才交还槽位；恢复期间代次改变会使旧 Ready 失败并触发重试。
-->

每个在线 Peer 只保留一个待确认屏障，期限为 `min(3 秒, ready_timeout)`；心跳不会延长。超时或断线沿用 AI 接管政策，恢复核对原点后才交还槽位。全部参与者曾 Ready 后，首帧前的主动暂停不会触发大厅等待超时；尚缺参与者时原有大厅期限仍有效。

保存记录物理权威状态，临时会话控制不写入存档物理格式。暂停保存、恢复运行、完整录制和独立回放已经通过实际文件检查。MatchEnd 在暂停中仍能核对并确认；结束排空优先于尚未消费的暂停确认期限，保留既有 UDP 退出等待。

## 当前验证与待办

```text
python -m unittest gfootball.frame_sync.test_match_control gfootball.frame_sync.test_match_pause_network
python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --output <全新证据目录>
```

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
控制原语 35 项继续通过；新增真实接入检查 22 项，包含缓冲 6 项和 TCP/UDP 集成 16 项。覆盖控制/确认丢失与重复、预测回退、旧输入、确认超时、收集中请求、暂停原点恢复、过期 Ready 重试、连续再暂停、处理控制时断线、保存回放、终局与公开服务端循环。完整比赛组 354 项、共享网络 219 项、录制 146 项及实际文件指纹均通过，见[本轮报告](../../.project/reports/optimization-pause-v6-progress-2026-09-10.md)。
-->

控制原语 35 项与网络接入 22 项继续通过；本轮新增 25 项，包含命令 6 项、本地/主机与状态校验 13 项、实际窗口协调 6 项。完整比赛组 379 项重跑通过；共享网络 219 项、录制 146 项和实际文件证据经源码/日志指纹验证后复用，见[本轮报告](../../.project/reports/optimization-pause-ui-progress-2026-09-10.md)。

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
下一步接通 LocalPlayer 权威暂停与界面请求/反馈，再验收 GameEnv、实际键盘/手柄、暂停后的真实图像、长时间运行、GPU/RSS、输入到显示延迟及长期 p99。C++ 通用协议仍为 v2，本轮未实现 C++ 比赛 v6 互通。四个相关 ready 标志保持 false，完整约束见[实施设计](../../.project/optimization/pause-protocol-design.md)。
-->

下一步验收真实 GameEnv/SDL 暂停、键盘/手柄事件、HUD 可见性与恢复后的实际图像，并继续原生资源、长时运行、GPU/RSS、输入延迟与长期 p99。C++ 通用协议仍为 v2，比赛 v6 互通未实现/验证。四个 ready 标志保持 false，完整约束见[实施设计](../../.project/optimization/pause-protocol-design.md)。
