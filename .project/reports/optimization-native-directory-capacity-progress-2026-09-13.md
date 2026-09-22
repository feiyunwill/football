# 原生回放目录与容量验收进度

2026-09-13。归属 ms-21.1 性能与容量 → plan-21.1.2 容量与预算 → task-21.1.2.1 网络与回滚内存预算。

<!-- 2026-09-13：保留正式 a 之前的进度描述。
修复了原生回放只有单文件上限、不同种子的文件可在同一目录持续累积的问题。当前实现增加每目录的数量和字节预算，并已接入真实客户端。综合容量检查已实现，正式依赖链正在执行；本报告不宣称任务或整个优化阶段已通过。
-->

<!-- 2026-09-13 正式 c 终态取代以下进度记录。
原生回放已接入每目录数量/字节预算、协作写入锁与中断恢复。综合正式 a 在突然关闭服务器后的回放比较环节失败；前置九项检查通过。现已修正终止边界的测试假设，保留原断线检查并新增固定边界的真实双客户端验收，专项 224 次执行全部通过。[正式 b](../optimization/benchmarks/native-capacity-formal-20260913-b/run.log) 的前八项通过，但 CPU 收益的两个置信区间未满足要求，正式链已退出 1。现在单独执行完整容量检查以取得其实际证据，任务仍未通过；详见[当前性能证据](optimization-performance-evidence-review-2026-09-13.md)。

[容量契约](../optimization/capacity-contract.md)定义默认边界、拒绝与恢复行为、证据范围和复现入口。[已终止的正式执行日志](../optimization/benchmarks/native-capacity-formal-20260913-b/run.log)保留最新检查进展，最终状态以 `python3 .project/quality.py status` 为准。

正式运行和状态复核使用已归档的[运行环境](../optimization/benchmarks/native-capacity-formal-20260913-b/environment.json)：项目质量 venv、对应 PATH/TMPDIR，以及 `DISPLAY=:football-test`、`SDL_VIDEODRIVER=offscreen`、`PYTHONOPTIMIZE=0`。改变这些已声明的验收输入会产生不同指纹，需要重新验收。

-->
正式 c 已完成全部十项检查，退出码 0；当前容量任务由质量入口计算为已验证。最终容量报告包含 1390 次执行、零跳过：360 次 C++ 单元执行、98 个原生／协议场景、758 次 Python 回归与 174 次录制检查。所有检测构建、实际客户端、回放与资源回收检查均完成。

[正式日志](../optimization/benchmarks/native-capacity-formal-20260913-c/run.log)、[固定运行环境](../optimization/benchmarks/native-capacity-formal-20260913-c/environment.json)和[最终容量报告](../optimization/benchmarks/memory-budget-1789247728408090274/report.json)共同标识本次版本。容量报告 SHA256：`327949323ee85f26498ba6c042452012252aa1c7d63c410aca44dd3950a75b73`，包含 418 个结果文件、1121 项源码和 57 项二进制身份。当前状态仍由 `python3 .project/quality.py status` 根据源码、工具和已声明环境计算，后续输入变化会使旧证据过期。

[容量契约](../optimization/capacity-contract.md)规定预算、拒绝与恢复行为。先前正式 a 的终止边界失败、正式 b 的统计收益失败和各次独立检查均保留为历史证据；它们不会被此次通过改写。[性能报告](optimization-performance-evidence-review-2026-09-13.md)记录当前固定 CPU 比较及保留的全部样本。

新增 [replay_directory.hpp](../../engine/src/frame_sync/replay_directory.hpp) 默认每目录最多保留 64 个文件、256 MiB 逻辑文件数据。替换时同时计入旧目标文件和新临时文件；满额拒绝发布，已有回放不自动删除。协作写入者通过父目录文件描述符上的进程间锁共享准入，等待默认最多 2 秒；扫描每个目录默认最多 4096 项。预算不可在构造后修改，扫描下限必须容纳文件和专属临时目录。

新临时文件写入保留的 0700 目录 `.football-replay-tmp-v1`。持锁后只清理其中严格匹配应用临时文件名、属于当前用户且无额外硬链接的常规文件。未知文件和父目录遗留临时文件保留、计入容量；遇到不安全链接或目录权限时拒绝保存。它是每目录、Linux 本地文件系统上的协作写入约束，不代表用户所有目录或任意外部写入者的磁盘总额限制。

[replay_file.hpp](../../engine/src/frame_sync/replay_file.hpp)仍负责分块写入、短写/EINTR、文件同步、原子发布和错误处理。新适配层将临时文件定位到专属目录，在发布后同步两侧目录。发布后的同步错误仍报告 `committed=true`；发布前失败保留旧文件。共享序列化新增精确字节查询，不为准入再生成一份完整回放。[客户端](../../engine/src/frame_sync/integrated_client.cpp)实际调用新入口，保存失败继续明确记录原因并返回失败状态。

[目录测试](../../engine/tests/replay_directory_test.cpp)包含 16 项：默认第 65 个文件拒绝、数量与峰值字节边界、替换与释放恢复、最小扫描配置、不安全链接、三个进程争抢容量、实际写入进程被 SIGKILL 后恢复、100 次分配异常后的锁/描述符/临时文件回收、发布后同步失败及 100000 帧 × 22 槽位最大回放。测试已经登记到 CMake 和 sources.cmake。

[扩展回放检查](../checks/replay_persistence.py)还通过真实 GameEnv 客户端验证默认数量/字节满额拒绝、已有文件不变、显式释放测试容量后成功保存，以及专属临时文件恢复。独立解码器检查实际确认帧、输入和哈希；真实服务端双客户端的回放一致性单独验证。协议故障夹具不冒充完整服务端或真实键盘输入。

| 执行记录 | 结果与范围 |
| --- | --- |
| [回放专项 b](../optimization/benchmarks/native-replay-directory-20260913-b/evidence/report.json) | 普通与 ASan/UBSan 合计 208 次单元用例执行、14 个实际 GameEnv 场景通过，无跳过 |
| [综合预检 a 的命令与日志](../optimization/benchmarks/native-memory-budget-20260913-a/evidence/commands.json) | 两种构建各 76 项 TCP/UDP/大厅容量测试通过；原生运行时、服务端/客户端、恢复、慢连接、故障及独立 TCP CLI 检查通过；再次通过回放专项 |
| [综合预检 a 的 Python 失败记录](../optimization/benchmarks/native-memory-budget-20260913-a/evidence/python-frame-sync.log) | 755 通过、3 失败；完整失败输出保留，没有计为通过 |
| [图形入口修正后的复验](../optimization/benchmarks/native-memory-python-20260913-b/graphical.log) | 全部 5 项实际图形用例通过 |
| [录制与资源回收复验](../optimization/benchmarks/native-memory-python-20260913-b/recording/report.json) | 174 项通过，无跳过；实际 GameEnv 与渲染子套件通过；结束后池内 live/leased、渲染预留、持有锁、所属线程和子进程均归零 |
| [断言开关检查](../optimization/benchmarks/native-memory-python-20260913-b/commands.json) | `-O` 以及父进程忽略、子进程继承优化环境的两种调用均在创建输出或运行原生检查前被拒绝 |

这些是执行次数，不能按新增测试数量相加；图形复验与先前套件有重叠。回放专项 b 之后新增了综合检查和显式特殊成员声明，其完整输入指纹属于历史局部记录；综合预检中的回放专项已重新编译并验证后续原生实现。正式检查仍会针对冻结的最终输入重新执行全部必要门禁。

综合预检的三个失败来自本轮新入口错误复用了原生 EGL 探针的环境：没有 DISPLAY 时可以渲染图像，但 `poll_input()` 正确拒绝没有 SDL 窗口的上下文。现已为完整 Python 图形回归配置 SDL offscreen 驱动，创建真实 SDL 窗口、GL 上下文和事件队列；原生运行时继续单独覆盖 EGL。未跳过用例、模拟输入返回值或放松退出断言。失败时使用的[完整初版检查脚本](../optimization/benchmarks/native-memory-budget-20260913-a/memory_budget_before_sdl.py)按其原始 SHA256 归档。

正式 a 的[失败日志](../optimization/benchmarks/memory-budget-1789239179430327335/replay.log)和[十项正式记录](../optimization/benchmarks/native-capacity-formal-20260913-a/failure-records.json)完整保留。两端确认数为 20/21，各自回放有效且与遥测一致；[独立诊断](../optimization/benchmarks/native-replay-cutoff-20260913-a/failed-pair-diagnosis.json)确认全部 20 个共享帧的输入/哈希相同。服务器正在广播时直接 SIGTERM，不构成同一确认边界；旧完整字节相等断言把这个终止竞态误判为持久化差异。

修正后，原突然断线场景继续检查每个完整文件、实际确认数及每一个共享帧的输入/哈希。新增 [有界固定帧探针](../checks/fixed_frame_relay.py)原样转发真实服务器第 0–20 帧及其三个哈希，不生成或修改输入与哈希；停止后续转发后保留 2 秒消费时间，再关闭客户端连接。两端必须各确认 21 帧、核验 3 个哈希，且完整文件逐字节相同；延迟到未完成的客户端会使检查失败。独立解码器还将全部输入和检查点与捕获的实际网络字节对照。它是验收边界，不是新实现的产品终局协议。

[最终回放专项](../optimization/benchmarks/native-replay-cutoff-20260913-b/evidence/report.json)合计 208 次单元用例与 16 个原生场景通过，无跳过；两种构建都保持完整固定回放相同。[质量入口自检](../optimization/benchmarks/native-replay-cutoff-20260913-b/oracles.log)为 50 项通过，含新增 8 项证据校验，能拒绝共享输入、哈希、会话差异和截断文件。原失败运行仍为失败，新的局部通过不追溯改变它的状态。

新增 [memory_budget.py](../checks/memory_budget.py)串联共享传输、实际原生程序、录制与 Python 所有权检查。它验证检测器配置、最低用例数、零跳过、真实原生库身份和执行前后源码/二进制指纹。命令超时仅终止自己创建的进程会话；初始源码清单和已验证二进制清单随执行逐步保存，失败仍保留原始证据。Python 环境使用本次构建的绑定与核心，现有 wheel 仅提供依赖。

<!-- 2026-09-13：保留正式 a 之前的进度描述。
<!-- 2026-09-13 正式 c 终态取代以下进度记录。
`memory_budget` 的执行配置已登记，最低 1388 次完整范围执行；`ready=true` 表示检查实现已接通，不代表验收通过。当前正式运行从前置框架、架构和性能检查按依赖顺序推进，再执行容量检查。此前正式证据因源码变化已需要刷新，没有手工修改通过记录或复用过期指纹。
-->

`memory_budget` 的执行配置已登记，最低 1390 次完整范围执行：360 次 C++ 单元用例、98 个原生/协议场景和 932 次 Python 用例执行。`ready=true` 表示检查已接通，不代表验收通过。正式 b 已在性能比较处终止；独立[容量执行 c](../optimization/benchmarks/native-memory-budget-20260913-c/evidence/commands.json)使用同样的图形和断言环境，不自动提升正式状态；源代码或验收入口变化会使旧指纹失效，没有手工提升状态。

下一步根据正式结果修复失败或完成本任务，再推进 task-21.1.2.2 的稳定数值采样入口、长期 RSS 和性能验收。原始长局失败、独立采样对照和性能基线保持原样；手感、协议互通、GPU 总字节、AI 与发布阶段继续按里程碑推进。

2026-09-13 最新终态：容量 c 独立检查通过 1390 项执行、零跳过，原始结果与指纹核验已归档；正式 b 的 CPU 收益条件仍失败，不提升任务状态。见[当前性能与容量证据](optimization-performance-evidence-review-2026-09-13.md)。

-->
正式 c 已完成当前版本的全部容量验收。接下来推进 task-21.1.2.2 的独立稳定采样入口、长期 RSS 和性能验收；原始长局失败、采样对照及原始性能基线保留。手感、网络互通、渲染、AI 和发布阶段继续按里程碑执行，整个优化阶段仍未完成。
