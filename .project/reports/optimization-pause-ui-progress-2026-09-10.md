# 优化进展：本地与界面暂停、长局校验回收

2026-09-10。对应 ms22 → plan22.1.2 → task22.1.2.1，并补齐 task21.1.2.1 的本地接收缓存回收。Local 权威暂停、终端/图形命令和 Host/Join 状态反馈已接通；复查发现并修复本地逐帧 StateHash 不消费导致的长局断线。完整比赛回归 379 项通过，原生/设备/画面与产品整体验收仍未完成。

## 实现与发现

[LocalPlayer](../../gfootball/frame_sync/local_runtime.py) 新增 `set_paused/pause/resume` 和控制回调。在同步权威/副本边界核对帧号与规范摘要，清空未来输入并建立控制状态；帧内请求在当前帧完成后生效，控制回调重入明确拒绝。暂停时不采样或推进，`step()` 返回 None；实时循环仍处理命令，暂停 tick 不消耗帧数上限。保存/退出、录制收尾和恢复后的新输入沿用原有所有者与持久化路径。

本地继续使用专属的同步 TCP 服务和副本，没有预测或独立自动权威循环。暂停控制在本地所有者上完成，不向通用 v2/v3 连接发送 v6 控制包，也不修改 GameEnv 物理暂停状态。恢复依次通知 RESUMING、RUNNING，物理存档不保存临时控制代次。Host/Join 继续使用前轮已实现的 v6 网络屏障。

本地原实现虽然直接比较了双方规范摘要，却没有消费网络 StateHash。默认缓存最多 1024 条，长局会耗尽并断线。本轮以真实 TCP 和一个 hash 槽复现了 `hash_capacity`，随后改为每帧等待、消费并验证帧号/64 位值，再检查完整双方摘要。新检查在同一槽位容量下连续推进 64 帧，再暂停/恢复推进一帧；缓存回到零。延迟分片会等待，错误帧号或值会关闭比赛并保留已有录制，没有扩大容量掩盖问题。

[InputBuffer 与终端控制](../../gfootball/frame_sync/graphical_input.py) 增加 K/Guide 暂停命令，按住不重复触发；逻辑读取前的多次切换仅保留最终意图，不保存事件队列。原 `commands()` 二元返回仍可用，协调器显式读取暂停字段。暂停/失焦/退出清理对应命令和动作；恢复要求中立输入，重复 RUNNING 原点恢复也清理旧短按，首次启动保留新输入。终端持续方向在暂停中清空，保存与退出继续有效。

[多人循环](../../gfootball/frame_sync/multiplayer_runtime.py) 把命令交给 Host 权威接口，Join 只观察控制状态。输入冻结由实际逻辑控制通知驱动，避免用尚未应用的旧 phase 提前解除冻结。全部参与者曾 Ready 后，首帧前主动暂停不会再触发大厅超时；尚缺参与者时原期限仍有效。

[图形协调](../../gfootball/frame_sync/graphical_runtime.py) 通过锁保护的固定字段传递状态，UI 不访问权威引擎。画面提示暂停、等待恢复和释放输入，只在文本变化时跨入显示引擎；没有配置保存路径时不显示保存快捷键。终端菜单也打印去重后的暂停/恢复提示和相应角色的操作说明。

[原生 HUD](../../engine/src/onthepitch/match.cpp) 增加独立、按需创建的 caption，由显示所有者调用 `set_match_status()`。接口限制最多 96 个可打印 ASCII 字符，状态独立于进球消息的到期时间，不进入 ProcessState；关闭时释放。SDL 键盘表增加 K，仍保持事件/设备处理上界。相关 C++ 源码尚未编译，当前没有真实 HUD 或设备通过证据。

## 自动验证

新增 [test_match_pause_ui.py](../../gfootball/frame_sync/test_match_pause_ui.py) 共 25 项：命令 6 项、本地/主机/逐帧校验 13 项、图形协调 6 项。使用实际 TCP/UDP、线程、存档与回放，引擎和显示为明确的独立 oracle。

覆盖首帧前暂停、采样中请求、暂停保存与退出、持键释放、重连输入清理、重复意图与非法所有者、回调失败、摘要不一致、实际心跳保活、已 Ready/缺参与者两种大厅期限、Local/Host/Join 画面状态、Join 不能恢复主机、HUD 失败清理，以及 hash 单槽运行、延迟分片和错误校验。3.2 秒心跳观察与 1000 次空闲 tick 是有限检查，不是长时间 RSS、设备延迟或性能结论。

接入时曾误用权威窗口的 `frame` 字段，已修正为实际 `frame_id`；一个 HUD 故障夹具把每次轮询都当作新按键，改为单次持续按住后验证通过。最初完整 376 项通过后，进一步审查发现上述 StateHash 漏消费问题，增加三项检查并完整重跑。前一 a 目录保留为历史；最终证据使用 b 目录。

| 检查 | 当前证据 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、文件/存档/回放 | 本轮 379 项通过，124 个来源文件 | [最终报告](../optimization/benchmarks/python-pause-ui-match-windows-20260910-b/report.json) |
| 共享 TCP/UDP、恢复、预测与展示 | 219 项通过；45 个来源文件及日志仍匹配，本轮未重跑 | [复用报告](../optimization/benchmarks/python-pause-v6-network-windows-20260910-a/report.json) |
| 所有权、资源池、录制与回放组件 | 146 项通过；36 个来源文件及日志仍匹配，本轮未重跑 | [复用报告](../optimization/benchmarks/python-pause-v6-recording-windows-20260910-a/report.json) |
| 资源和策略文件读取 | 21 个来源文件仍匹配，本轮未重测 | [复用报告](../optimization/benchmarks/python-pause-v6-identity-files-windows-20260910-a/report.json) |

最终完整运行无失败、错误、跳过、已检测异步警告或受检线程/进程/锁遗留。四份报告、226 个来源条目和三个日志的 SHA256 均重新核对，见[证据清单](../optimization/benchmarks/python-pause-ui-evidence-20260910.json)。a 目录与前轮比赛报告的部分源码指纹已过期，不作为当前最终证据。

实际执行 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0。比赛探针解析 43 个 Python 3.9 语法文件，未运行 Python 3.9。既有最大原点 UDP 故障回归本轮观察 1 MiB、5 帧、丢弃 55、重复 44、乱序 37 个数据报，耗时 3.4264 秒、最大数据报 1200 字节；这是本机观察，不据此宣称性能提升或 WAN 验收。

## 未完成的产品验收

[原生图形检查](../../gfootball/frame_sync/test_graphical_native.py) 新增真实 Local 暂停与 HUD 用例，要求物理摘要不变、HUD 改变实际像素、重复恢复后提示持续、清空后回到原图。比赛/图形原生检查总数由 11 增至 12，当前均未执行；独立持牌契约、另 28 项环境/原生/渲染检查也继续待执行。

下一步继续实际原生/SDL 输入与 HUD、暂停恢复、持牌/插值图像的运行验收，并审查渲染异常清理、资源字节、长期 RSS/p99、C++ 比赛互通、WAN、AI 和发布要求。本輪没有 C++ 构建、WSL 重试、安装或 Git 操作。四个相关 ready 标志保持 false，里程碑和整体目标继续自动推进。
