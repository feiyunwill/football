# 多人比赛入口与有界恢复

2026-09-10。Host、Join 和 Settings 已连接实际 Python TCP 服务、客户端比赛推进、原点恢复及持久化设置。默认工厂使用真实 GameEnv；当前执行证据来自明确的独立状态归约器和真实 socket、文件。原生引擎与图形体验尚待验收。

## 使用入口

在具备原生依赖的 Linux 项目目录中分别打开两个终端：

```text
python -m gfootball.frame_sync.main_menu --mode host
python -m gfootball.frame_sync.main_menu --mode join
```

Host 默认场景为 `11_vs_11_stochastic`，左右各一个受控槽位，端口 12345。Host 自己占一个槽位；Join 填写 Host 地址与实际监听端口。每个受控槽位需要一位连接玩家，未受控球员由引擎 AI 控制。Host 可输入端口 0，由服务绑定后输出实际端口。Join 的场景、槽位、种子和初始状态全部来自服务端。

<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
双方在终端使用 WASD 设置持续方向、0 停止移动、Z/X/C 传球、V 射门、空格施压、Q 离开。Host 配置存档路径后可按 P 保存；正常结束会保存并发布配置的完整录制。Ctrl+C 封存已有录制但不自动覆盖存档。终端没有按键松开事件，目前没有 SDL 图形窗口或自然比赛结束画面。
-->

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
双方在终端使用 WASD 设置持续方向、0 停止移动、Z/X/C 传球、V 射门、空格施压、Q 离开。Host 配置存档路径后可按 P 保存；正常结束会保存并发布配置的完整录制。Ctrl+C 封存已有录制但不自动覆盖存档。增加 `--graphics` 使用[图形输入与窗口协调](graphical_match.md)；实际 SDL、原生自然结束画面与设备体验尚待验收。
-->

双方在终端使用 WASD 设置持续方向、0 停止、Z/X/C 传球、V 射门、空格施压、Q 离开。Host 按 K 暂停/恢复，配置存档后可按 P 保存；Join 显示主机控制状态。暂停清空终端持续方向，恢复后需重新输入方向命令。正常结束保存并发布配置的完整录制；Ctrl+C 封存录制但不自动覆盖存档。`--graphics` 接入[图形输入](graphical_match.md)，真实 SDL 和设备体验仍待验收。

菜单会询问帧数上限；非交互输入必须给出 1–1000000 帧。Host 默认等待参与者最多 60 秒，全部 Ready 后才推进首帧。Join 提前达到自己的帧数上限或按 Q 会退出；Host 比赛结束则向仍连接的客户端发送统一最终帧和状态校验值。

```text
python -m gfootball.frame_sync.main_menu --mode settings
python -m gfootball.frame_sync.main_menu --settings-file recordings/preferences.save
```

Settings 保存本地/Host 场景与控制槽位数、种子、Join 地址、端口、帧数、回放和存档路径。Enter 保留当前值，`-` 清除可选帧数或输出路径。默认文件为 `~/.football/settings.save`；未保存时只读取内置默认值。各入口读取相应默认值，包括 Continue 和 Replay。无效设置、损坏文件或不同类型的集合会报错，失败写入保留之前的完整文件。

## 所有权与嵌入接口

`HostedMatch` 拥有一个服务端权威引擎和一个本地 TCP 玩家副本；每个 `NetworkPlayer` 拥有自己的客户端引擎。服务端线程独占权威状态，玩家创建线程执行输入、预测、回滚和恢复。跨线程、跨进程和重入推进会被拒绝；关闭尝试释放全部已拥有资源，并保留最初的运行错误。

```python
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer

# Host 进程；另一个进程连接这个端口。
with HostedMatch(scenario='11_vs_11_stochastic', port=12345,
                 record_path='recordings/network.jsonl',
                 save_path='recordings/network.save') as match:
    result = match.run(300)

# Join 进程。
with NetworkPlayer('127.0.0.1', 12345) as player:
    result = player.run(300)
```

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
手动调度使用 `start()`、`HostedMatch.advance()` 或 `NetworkPlayer.tick()`、`finish()` 和 `close()`。工厂及输入回调可显式注入；自定义引擎必须提供存档身份，不能自动退回到未知实现。`run()` 在退出时关闭资源，返回关闭后的统计。程序性测试应显式提供输入回调和帧数。
-->

手动调度使用 `start()`、`HostedMatch.advance()` 或 `NetworkPlayer.tick()`、`finish()` 和 `close()`。Host 所有者可调用 `set_paused(bool)`、`pause()`、`resume()` 请求权威暂停/恢复，返回当前控制状态；收集中的帧完成后才建立屏障。暂停时 `advance()` 返回 false，继续调度玩家以处理确认和恢复，详见[暂停接口](match_control.md)。工厂及输入回调可显式注入，自定义引擎必须提供身份；`run()` 退出时关闭资源并返回统计。程序性检查应显式提供输入回调和帧数。

Host 录制权威端实际执行的输入、位置与最终摘要，沿用[本地存档与回放](local_match_storage.md)的原子发布和容量限制。保存文件可以通过本地 Continue 创建新的本地时间线；当前没有恢复整个多人房间或重新连接其他参与者的持久化接口。

<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
## v4 会话约定
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
## v5 会话约定
-->

## v6 会话约定

<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
新增比赛协议显式协商版本 4，旧 v2/v3 协议保持原行为。v4 不接受旧版连接或裸重连请求；v4 客户端连接旧服务也会失败，不自动降级。
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
比赛协议显式协商版本 5，要求[节拍契约](match_cadence.md)。v5 不接受旧版连接或裸重连请求；客户端连接旧服务也会失败，不自动降级。通用 v2/v3 API 保留原协议。
-->

比赛协议显式协商版本 6，要求[节拍与控制原点契约](match_cadence.md)。v6 不接受旧版比赛连接或裸重连请求，客户端连接旧服务也失败，不自动降级。通用 v2/v3 API 保留原协议。

<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
初次连接依次接收 SessionStart、受控槽位、恢复 token、完整原点快照。快照包含 `FMATCH4` 标记、场景设置、实现/资源身份、原始状态 SHA256、规范状态摘要及原始状态字节。完整性与格式检查先于客户端引擎创建；身份比较先于原生 `set_state`，状态摘要核对后才发送 Ready。服务端收到全部参与者的 Ready 才允许首帧，大厅期间客户端不预测。
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
初次连接依次接收 SessionStart、受控槽位、恢复 token、完整原点快照。快照包含 `FMATCH5` 标记、场景设置、实现/资源身份、节拍、原始状态 SHA256、规范摘要及原始状态字节。完整性与节拍检查先于客户端引擎创建；身份比较先于原生 `set_state`，摘要核对后才发送带节拍确认的 MatchReady。全部参与者确认后才允许首帧，大厅期间客户端不预测。
-->

初次连接依次接收 SessionStart、受控槽位、恢复 token、完整原点快照。快照包含 `FMATCH6` 标记、场景设置、实现/资源身份、节拍、控制 epoch/phase、原始状态 SHA256、规范摘要及原始状态字节。完整性与契约检查先于引擎创建；身份比较先于 `set_state`。核对摘要并绑定控制状态后，发送带节拍和 epoch 的 MatchReady；全部参与者 Ready 后才允许首帧。大厅通过同一逻辑循环处理控制与首帧不可变输入，此时不预测。

<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
重连使用带版本号的原 token 请求，复用现有恢复状态机、快照和 Ready/handback；不会静默新建比赛。运行中快照再次核对场景和身份。曾 Ready 的大厅玩家断开后保留原槽位，期限为 `min(30 秒, ready_timeout)`；未 Ready 的失败初始化会释放槽位。过期的大厅保留项在新连接时清理，Host 另有总大厅等待期限。
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
重连使用带版本号的原 token 请求，复用现有恢复状态机、快照和 MatchReady/handback；不会静默新建比赛。运行中快照再次核对节拍、场景和身份。曾 Ready 的大厅玩家断开后保留原槽位，期限为 `min(30 秒, ready_timeout)`；未 Ready 的失败初始化会释放槽位。过期的大厅保留项在新连接时清理，Host 另有总大厅等待期限。
-->

重连使用带版本号的原 token 请求，复用恢复状态机、快照和 MatchReady/handback，不静默新建比赛。原点重新核对节拍、控制、场景和身份；过期 epoch 的 Ready 拒绝后重试原会话，暂停中的恢复仍保持暂停。曾 Ready 的大厅玩家断开后保留原槽位，期限为 `min(30 秒, ready_timeout)`；未 Ready 的失败初始化释放槽位。过期大厅保留项在新连接时清理，Host 另有总大厅等待期限。

结束消息携带下一帧号及 64 位状态校验值。客户端处理完全部权威帧后撤销超过终点的预测，核对最终状态并发送 Ack；结束后不再接受权威帧。Host 默认等待确认 2 秒，`end_acknowledged` 表明是否全部确认。超时允许关闭并返回未全部确认状态，不能据此宣称每位远端玩家都已完成。公开服务端 `run_loop()` 同样等待 Ready 并处理结束退出。

## 容量与验证边界

原始快照最多 1 MiB，元数据最多 4096 字节，内部头 12 字节，完整载荷最多 1,052,684 字节。采用原始字节传输，增量接收沿用有界缓冲；超长声明在分配载荷前拒绝。初始原点在服务端只缓存一份不可变字节串，首帧后释放；发送仍计入各连接发送预算。恢复、预测历史和发送队列继续受现有共享限制约束。设置集合只有一个槽位，载荷 32 KiB、图结构 64 KiB。

```text
python .project/checks/frame_replay_probe.py --match --multiplayer --output <不存在的目录>
python .project/checks/python_reconnect_probe.py --udp-resume --output <另一个不存在的目录>
```

<!-- 2026-09-10: 自然终局及当前回归取代旧说明，保留历史。
当前 Windows Python 3.14.6 第一组 181 项通过，包括新增多人 29 项、设置与菜单 9 项和既有 143 项；第二组共享 TCP/UDP/重连 219 项通过。测试覆盖真实双玩家 socket、首帧屏障、预测结束回退、大厅/比赛恢复、身份拒绝、异常清理、录制/保存/独立回放、菜单和公开服务循环。归约器没有替代或伪造 GameEnv 导入。
-->
<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
当前 Windows Python 3.14.6 完整比赛组使用 `--match --multiplayer --udp-multiplayer`，228 项通过；共享 TCP/UDP/重连 219 项通过。检查包含 27 项新增自然终局、预测回滚和实际比赛收尾用例。使用独立归约器、真实 socket 和文件，没有替代 GameEnv 导入。
-->

<!-- 2026-09-10: 展示插值实现及当前证据更新，保留原说明。
当前 Windows Python 3.14.6 使用 `--match --multiplayer --udp-multiplayer --graphics` 的完整组 283 项通过；共享 TCP/UDP/重连 219 项通过。包含 13 项新增节拍契约检查。使用独立归约器、真实 socket 和文件，没有替代 GameEnv 导入。
-->

<!-- 2026-09-10: 暂停执行原语与当前证据已更新，保留此前记录。
当前 Windows Python 3.14.6 使用 `--match --multiplayer --udp-multiplayer --graphics` 的完整组 297 项通过；共享 TCP/UDP/重连 219 项通过。包含 13 项节拍契约和 14 项[展示插值](render_interpolation.md)检查。使用独立归约器、真实 socket 和文件，没有替代 GameEnv 导入。
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
当前 Windows Python 3.14.6 使用 `--match --multiplayer --udp-multiplayer --graphics` 的完整组 332 项通过，共享 TCP/UDP/重连 219 项通过，见[实施进展](../../.project/reports/optimization-pause-primitives-progress-2026-09-10.md)。其中新增 35 项客户端暂停原语检查使用独立引擎与可控消息投递；当前真实比赛仍协商 v5，未启用网络暂停。
-->

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
当前 Windows Python 3.14.6 使用 `--match --multiplayer --udp-multiplayer --graphics` 的完整组 354 项通过，共享 TCP/UDP/重连 219 项、录制 146 项通过，见[实施进展](../../.project/reports/optimization-pause-v6-progress-2026-09-10.md)。新控制接入 22 项包含 6 项缓冲和 16 项真实 TCP/UDP 集成检查，覆盖暂停、恢复、故障、超时、保存回放与结束；引擎为明确的独立 oracle。
-->

当前 Windows Python 3.14.6 的完整比赛/图形组 379 项重跑通过，新增 25 项包括本地暂停、GUI/终端命令、真实 TCP/UDP 状态反馈和本地逐帧校验回收。共享网络 219 项、录制 146 项与文件证据按当前匹配的指纹复用，见[实施进展](../../.project/reports/optimization-pause-ui-progress-2026-09-10.md)。引擎与显示为独立 oracle。

<!-- 2026-09-10: UDP v4 已有局部实现，保留原说明。
第一条命令增加 `--native` 会强制执行 3 项真实 GameEnv 检查：既有库身份和本地存档/回放，以及新增三引擎多人比赛/结束/回放。三项均尚未执行。v4 当前仅 TCP，UDP v4、C++ 互通、广域网、图形输入、自然结束、原生分配准入和长时内存/性能预算仍待完成。身份检查需要边界文件读取，其原生线程延迟尚未测量。
-->

<!-- 2026-09-10: 自然终局及当前回归取代旧说明，保留历史。
UDP v4 已接入同一比赛循环和菜单，使用 `--transport udp`，见 [UDP 多人文档](multiplayer_udp.md)。自动检查增加 `--udp-multiplayer` 后执行 196 项，已全部通过；旧 181 项归档指纹过期，当前由 196 项重新覆盖。`--native` 在同时选择多人和 UDP 后要求 4 项真实 GameEnv 检查：实际库身份、本地存档/回放、TCP 与 UDP 三引擎多人比赛/结束/回放，四项全部尚未执行。C++ v4 互通、广域网、图形输入、自然结束、原生分配准入及长时内存/性能仍待完成。身份边界的原生线程延迟尚未测量。
-->
<!-- 2026-09-10: v5 节拍实现和当前证据取代之前说明，保留历史。
UDP v4 使用 `--transport udp`，见[UDP 多人文档](multiplayer_udp.md)。默认工厂已实现自然终局和共享实例准入；结束帧进入录制、存档及状态校验，客户端等待权威结果后确认结束，详见[比赛生命周期](match_lifecycle.md)。完整原生组现有 7 项，均未执行；C++ v4 互通、广域网、图形输入、原生字节预算与长时内存/性能仍待验收。
-->

<!-- 2026-09-10: 展示插值实现及当前证据更新，保留原说明。
UDP v5 使用 `--transport udp`，见[UDP 多人文档](multiplayer_udp.md)。默认工厂已实现自然终局和共享实例准入，详见[比赛生命周期](match_lifecycle.md)。完整原生组为 7 项，增加图形后为 10 项，均未执行；C++ 比赛协议互通、广域网、原生输入与渲染、原生字节预算及长期性能仍待验收。
-->

<!-- 2026-09-10: v6 暂停传输及本轮证据取代原说明，保留历史。
UDP v5 使用 `--transport udp`，见[UDP 多人文档](multiplayer_udp.md)。默认工厂已实现自然终局和共享实例准入，详见[比赛生命周期](match_lifecycle.md)。完整原生组为 7 项，增加图形后为 11 项，均未执行；C++ 比赛协议互通、广域网、原生输入与渲染、原生字节预算及长期性能仍待验收。
-->

<!-- 2026-09-10: Local/UI 暂停与逐帧校验回收已接通，保留此前记录。
UDP v6 使用 `--transport udp`，见[UDP 多人文档](multiplayer_udp.md)。默认工厂已实现自然终局和共享实例准入，详见[比赛生命周期](match_lifecycle.md)。完整原生组 7 项，增加图形后为 11 项，均未执行；Local/UI 暂停、C++ 比赛协议互通、广域网、原生输入/渲染、字节预算及长期性能仍待验收。
-->

UDP v6 使用 `--transport udp`，见[UDP 多人文档](multiplayer_udp.md)。默认工厂包含自然终局和共享实例准入。完整原生组 7 项，增加图形后为 12 项，均未执行；真实暂停/设备/HUD/渲染、C++ 比赛协议互通、广域网、原生字节预算及长期性能仍待验收。