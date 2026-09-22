# 运行时队列和日志：实施与验证进度

归属：ms-21.1 性能与容量 → plan-21.1.2 容量与预算 → task-21.1.2.1 网络与回滚内存预算。

本轮接续 [GameEnv 集成 TCP](optimization-integrated-tcp-progress-2026-09-09.md)，完成 C++ 渲染命令队列与基础日志的局部实现和实际引擎验证。旧 TCP 客户端、重连封装和 Python 缓存/输出路径仍需处理，因此 `memory_budget.ready=false`，任务、里程碑和整体目标均未宣告完成。

## 具体改动

`MessageQueue` 从逐项分配、无界增长的 list 改为固定 `vector<optional<T>>` 环形存储。默认 4096 项，实际槽位存储不能超过 1 MiB；构造参数在分配前验证，数量范围 1–65536、存储预算至多 16 MiB。没有每次入队的容器节点分配，满载明确抛出 length_error，已排队项仍保持顺序。Clear 和析构释放全部命令持有的资源引用，已消费项通过非抛出 move 转移所有权；空队列返回值也已初始化。

实际生产者是 GraphicsOverlay2D_Image2DInterpreter::OnPoke，消费者是 GraphicsTask::Render。渲染入口现在创建清理守卫：生成 HUD、准备相机、创建临时向量或渲染过程中抛异常，都会释放剩余当帧引用。临时向量按实际队列长度预留，消费时移动纹理引用。GameEnv::render 同时用作用域守卫恢复 Tracker 的禁用嵌套计数，避免一次渲染异常永久禁用后续跟踪。

队列 API 由调用者串行使用；实际 GameEnv 操作受该环境 ContextHolder 的递归互斥锁保护。这不是通用多生产者并发队列。预算约束命令对象与引用，不等于被引用的全部纹理、GPU 或进程 RSS 上限。

基础 Log 改用 const string 引用参数，避免函数入口复制巨大诊断文本；ctime_r/ctime_s 消除共享静态时间缓冲。每条正常日志最多 4096 字节，其中类名/方法名各最多 128、消息最多 3500，超限带截断标记，消息换行规范为单行，一次 fwrite 提交整条记录。FatalError 在输出诊断/调用栈并刷新流后执行 abort，代替旧版故意解引用非法地址的未定义行为。该模块不保留日志历史；外部重定向文件、调用者已构造的字符串和其他日志入口不在此单条记录预算内。

## 实际验证

[Release 原始结果](../optimization/benchmarks/runtime-capacity-native-20260909-a/report.json)与[完整检测构建结果](../optimization/benchmarks/runtime-capacity-sanitized-20260909-a/report.json)各 4/4 场景通过，均无跳过。

- 容量合同：非法构造参数、空队列、1000 轮填满/拒绝/部分消费/环形复用、move-only 所有权、Clear 和析构释放引用。队列部分 12,010 次断言；渲染模式重复同一队列部分，再增加 39 次实际图形检查，不将两次运行相加为独立覆盖。
- 真实图形恢复：启动 320×180 的 GameEnv，从实际 HUD 取得带纹理的命令；连续 4 轮填满 4096 项，再让实际 HUD 生成流程触发溢出。每轮核对纹理实际引用计数回落、队列清空、存储不增长、Tracker 嵌套恢复、逻辑状态摘要不变；下一次正常渲染成功，无 GL 错误，图像有可见内容。
- 并发日志：8 个线程各输出 64 条，512 条独立编号全部出现且无拆行；另输出一个 8 MiB 文本和一个含换行文本，最终恰为 514 条，最大 3813 字节、一次明确截断。
- 致命错误：独立进程收到预期 SIGABRT（退出码 -6），诊断存在，无 ASan/UBSan 错误报告。关闭了测试进程的 core dump 文件生成；abort 有意不执行正常析构，不能用该场景声明泄漏检测通过。正常队列/图形/日志退出路径开启了 ASan、UBSan 和泄漏检测，无抑制规则。

实际渲染器为 llvmpipe（LLVM 22.1.8），这些是资源生命周期和恢复证据，不是目标显卡吞吐量验收。当前覆盖的主动图形故障是 HUD 队列溢出，不代表枚举测试过所有驱动故障。

## 确定性与回滚回归

[原生状态回归](../optimization/benchmarks/runtime-state-regression-native-20260909-a/report.json)在修改后的核心上，对种子 42、43 各执行 200 帧预热、2000 帧推进和 2000 帧快照重演；与原始基线逐项比较输入/预热/最终哈希、全部 21 个状态检查点、2000 个活动标记及重演结果，全部一致。最终哈希仍为 `177cf7205a3272f3` 与 `39ceb7b90729ca35`。此次与编译并行，原始时间数据仅保留为执行记录，不作为性能比较。

原生回归及[检测构建回滚合同](../optimization/benchmarks/runtime-memory-sanitized-20260909-a/report.json)各通过 1498 次断言，真实 GameEnv 确认 128 帧、进行 64 次回滚校正，最大初始快照 91,416 字节、历史峰值 438,176 字节。检测构建检查了 132 条配置中的编译命令，确认 ASan/UBSan 标志及共享核心中的检测器符号；这不意味着所有 EXCLUDE_FROM_ALL 目标都已构建。

当前核心 SHA256：Release `f2566c7ff0dc6f0171168903074696bbe6089a3943394d0ac4fc3ba7187b4651`；检测构建 `4c6fb21045a16363b27c85862559a8673275efea2fb409b98d4c23530073902f`。原始/优化性能基线指针和归档均未改写。

复现入口：`engine_runtime_contract`、`.project/checks/runtime_capacity_probe.py --build <构建目录> --output <新目录>`。构建仍为 `/tmp/football-optimization-native` 与 `/tmp/football-optimization-sanitized`，单编译任务 `-j 1`。

## 更新核心后的 TCP 复验

重新编译了两类构建的实际服务端、客户端和原生 TCP 合同，避免沿用旧核心的验证结论。[Release 双端复验](../optimization/benchmarks/integrated-tcp-runtime-native-20260909-a/report.json)各确认 31 帧/4 次成功哈希校验，[检测构建双端复验](../optimization/benchmarks/integrated-tcp-runtime-sanitized-20260909-a/report.json)各确认 19 帧/2 次校验；同一构建双端的实际回放前缀一致。固定健康窗口后关闭服务端，退出码仍为预期的 0/1/1。

[Release 原生 TCP 合同](../optimization/benchmarks/engine-tcp-runtime-native-20260909-a/report.json)与[检测构建原生 TCP 合同](../optimization/benchmarks/engine-tcp-runtime-sanitized-20260909-a/report.json)也各通过 40 个连续确认帧、8 次哈希观察、实际托管、87,132 字节边界快照恢复及慢观战端超时检查。该复验使用新的核心 SHA256，旧完整故障矩阵原始记录继续保留。

## 尚待处理

1. C++ `asio_client.cpp` 仍有不推进 IO、旧预测逻辑、无界接收/历史；`reconnecting_client.hpp` 仍有无界收发、退避位移溢出以及未实际发出 Connect/ReconnectRequest 等问题。需要真实连接合同，不能把未接通的自动重连描述为可用功能。
2. Python `frame_sync/client.py` 与 `client_async.py` 的权威 deque、接收缓存和发送调度仍无完整预算；异步版本目前每次发送排入一个新任务，且 SessionStart 单独到达就置就绪事件，握手分片有竞态。需要处理退出后的状态、回调与容量释放。
3. `gfootball/env/observation_processor.py` 已直接读取审查：trace 只有 100 项数量限制，附加帧/调试文本无字节限制，自定义 dump 名称可持续增加配置项，视频/dump 文件无字节配额。写入失败还可能留下被临时删除的观察帧。它属于索引排除目录 gfootball/env，不能从图索引缺失推断源码不存在。后续需要保留已有用户产物并明确拒绝/停止行为；开发质量证据不参与日志清理。
4. 完成剩余入口和最大长度回放文件持久化后，接入正式 memory_budget 检查，再进行长时间增长/稳态性能验收。基础日志的单条上限不能替代整个工程输出预算。
