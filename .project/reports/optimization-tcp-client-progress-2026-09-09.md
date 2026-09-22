# TCP 客户端与自动重连：实施进度

归属：ms-21.1 性能与容量 → plan-21.1.2 容量与预算 → task-21.1.2.1 网络与回滚内存预算。

本轮完成共享 C++ TCP 传输、整帧客户端和重连封装的实现与局部验收。`memory_budget.ready=false`：Python 客户端、观察记录输出、最大长度回放持久化和正式容量检查仍未完成。网络里程碑还需要会话凭据下发、连接建立期限、输入窗口和网络故障矩阵；没有将这些环节标为产品级完成。

## 实现

新增 `tcp_client_transport.hpp`，将接收、发送、握手、槽位验证和快照解析集中到单一传输类。它由单一调用线程使用，内部 IO 每次 Poll 至多处理 64 个回调，并在回调之间检查 2 ms 时间预算。普通接收缓存上限 8192 字节；权威帧最多 1024 项、输入实际保留容量最多 512 KiB；哈希最多 1024 项；发送默认最多 256 项、2 MiB，包含未派发及正在发送的负载。超限关闭并释放缓存，不丢弃权威帧后继续模拟。

握手验证双方人数各不超过 11、总数 1–22、槽位数量及唯一性。部分握手有绝对期限；Ready 在实际引擎准备完毕后发送。心跳、托管和归还通知完整消费各自负载，非法帧头、NaN、未知类型和相互矛盾的哈希会终止连接。流式传输默认 3 秒无接收字节超时。DNS 和 TCP 建立仍同步；该期限不包含操作系统解析/建立连接，也不能用零星字节刷新来证明完整消息取得进展。

恢复仅接收一个默认最多 1 MiB 的快照，在接收正文前验证声明长度。恢复过程中允许快照后合并到达的权威帧和哈希，解析完成立即缩小临时大接收缓存。重新连接前完成旧连接的取消回调，防止旧包进入新会话或反复连接积累 Asio 负载。

新增 `TCPFrameClient`，实际调用 FrameSimulation 的整帧预测、回滚和确认哈希校验。初始化需要真实引擎工厂及完整回调。恢复沿用原有引擎，将服务端快照的“下一执行帧”作为 FrameSimulation 起点，先恢复状态再发送 Ready；不重新创建引擎、不从第 0 帧重放。FrameSimulation 新增经过范围验证的起始帧参数，默认仍为 0。

`asio_client.cpp` 的可执行入口继续承担无引擎的协议诊断：它现在实际推进 IO，使用服务端分配的槽位，验证连续权威帧，支持 SIGINT/SIGTERM 退出并严格验证参数。输出明确区分 `frames_received` 与实际引擎确认；这里接收到哈希不代表验证过游戏状态。真实 GameEnv 的验证使用下面独立的原生合同。

`reconnecting_client.hpp` 移除无界收发、独立线程回调和未执行的预测字段，改为封装 TCPFrameClient。Poll/Tick 自动推进恢复；退避期间没有 sleep，最多 32 次尝试（默认 10 次），延迟采用饱和加法（默认 100 ms 到 5 s），消除旧位移溢出。一次到期尝试仍使用同步 Connect/Resume。断网、空闲超时及握手超时可以重试；非法协议、容量溢出、引擎失败和哈希不一致终止恢复。回调允许 Close，拒绝嵌套连接/推进；回调异常关闭会话。初始化失败、恢复失败及主动关闭都会推进已排队的关闭操作，使对端及时看到断开。

旧重连构造函数没有引擎回调，无法兑现快照恢复，仓库结构搜索和源码搜索均未发现实际调用者，已更换为需要真实引擎工厂及会话 token 的构造函数。token 必须由宿主的会话管理方提供；封装不会从公开槽位和种子猜测凭据。现有服务端仍采用旧的可预测 token，协议没有安全下发它，本轮测试只为已知的首个会话提供旧 token。这是明确的网络阶段待办，不能据此宣称身份认证已经完成。

## 验证

[最终 C++ 检测结果](../optimization/benchmarks/tcp-reconnect-preflight-20260909-c/report.json)：26 项全部通过，其中传输容量 13 项、整帧预测 3 项、重连 10 项；Debug ASan、UBSan、LSan 开启，无抑制或跳过。

- 覆盖填满、拒绝、消费释放、再次填充；22 槽位完整收发；96 KiB 分片快照和合并权威帧；非法大长度、哈希冲突、半包期限；20 轮带未完成收发的销毁。
- 真 TCP 对端关闭触发自动恢复；快照恢复到帧 50 后确认帧 50 的状态哈希。第一次恢复半包超时，第二次保持同一会话身份并成功恢复；宿主拒绝快照时不发送 Ready。
- 验证 32 次重试上限和饱和退避、终止后不继续模拟、回调取消及异常、引擎准备期间关闭、初始化异常清理。策略时钟可注入，实际握手及收发仍使用真实 TCP。
- FrameSimulation 另有 6 项、内存预算另有 21 项检测回归在本轮早期通过，见 [初始回归记录](../optimization/benchmarks/tcp-client-preflight-20260909-a/report.json)。没有将同一测试多次执行相加为新增覆盖。

[命令行 Release](../optimization/benchmarks/tcp-client-cli-native-20260909-a/report.json)与[检测构建](../optimization/benchmarks/tcp-client-cli-sanitized-20260909-a/report.json)各 11/11 场景通过：5 项参数拒绝，2 项真实服务端连续收帧与双向关闭，4 项部分握手、非法权威帧头、槽位不符和控制消息分帧。正常信号退出为 0，对端 EOF 或非法输入为 1；强制清理不会计为通过。Release 的干净日志不等于它经过了检测器插桩。

[真实 GameEnv Release](../optimization/benchmarks/engine-tcp-reconnect-native-20260909-a/report.json)与[完整检测构建](../optimization/benchmarks/engine-tcp-reconnect-sanitized-20260909-a/report.json)各运行直接恢复和重连封装两种模式：

| 构建 / 模式 | 初始确认帧数 | 恢复边界 | 恢复后确认帧数 | 恢复后成功哈希校验 |
| --- | ---: | ---: | ---: | ---: |
| Release / 直接恢复 | 12 | 14 | 39 | 2 |
| 检测构建 / 直接恢复 | 12 | 14 | 39 | 2 |
| Release / 自动封装 | 12 | 29 | 54 | 3 |
| 检测构建 / 自动封装 | 12 | 23 | 48 | 2 |

服务端和客户端都是实际 GameEnv，初次断线前已验证真实非零输入生效。断线区间实际触发 AI 托管，恢复后归还控制权；自动封装仅尝试一次，引擎工厂仅调用一次，保留历史及接收缓存未超过预算。自动模式由 ResetForReconnect 发起实际断开，再由 Poll 按退避自动恢复；意外 EOF 自动触发另由真实 TCP 对端测试验证。没有把这两类覆盖描述为一次完整 WAN 故障实验。

该原生合同以 `max_predict=0` 验证权威确认和恢复，不能证明延迟网络下预测输入能被服务端接受。预测与不同槽位回滚由单独的客户端测试验证；现有服务端仍只接收当前帧输入，未来输入缓存和输入延迟需要后续实现。实际确认帧数与轮询断言数也不属于性能验收。

当前共享核心未改变：Release SHA256 `f2566c7ff0dc6f0171168903074696bbe6089a3943394d0ac4fc3ba7187b4651`，检测构建 `4c6fb21045a16363b27c85862559a8673275efea2fb409b98d4c23530073902f`。原始和优化性能基线的指针、归档均未改写。

## 保留的失败与修复

[首次重连测试](../optimization/benchmarks/tcp-reconnect-preflight-20260909-a/report.json)为 21/24 通过。两个失败暴露了真实清理缺陷：初始化失败或宿主回调 Close 后，关闭只被排入 IO 队列，终止状态不再 Poll，对端要等析构才断开。修复后对应检查通过。另一个是测试预设了系统级 connect refusal；本环境的 WSL localhost 转发对空闲端口先完成 connect、再返回连接重置，独立 Python socket 探针也复现该行为，因此允许 ConnectFailed 或即时 IoError，两者都必须遵守同样重试预算。没有放宽成功条件或允许多余重试。

较早的原生合同编译错误来自测试误用了既有 API 名称、main 签名和混合 auto 声明，修正测试后完成实际运行；未将测试编写错误记为产品修复。全部替换源码均保留日期和原因注释。

## 复现与下一步

构建始终单任务 `-j 1`。C++ 测试目录为 `/tmp/football-optimization-memory-tests`，命令行构建为 `/tmp/football-optimization-memory-asio-release` 和 `/tmp/football-optimization-memory-asio`，原生 GameEnv 构建为 `/tmp/football-optimization-native` 与 `/tmp/football-optimization-sanitized`。

入口为 `tcp_client_capacity_test`、`.project/checks/tcp_client_probe.py --client <可执行文件> --server <可执行文件> --output <新目录>`、`.project/checks/engine_tcp_client_probe.py --build <构建目录> --output <新目录>`。原始日志、二进制和相关源码哈希随结果保存。目标和新增引擎文件已登记 CMake/sources；修改范围的索引覆盖已检查，源码及实际编译为最终依据。

接下来继续 Python `frame_sync/client.py`、`client_async.py` 的接收、权威队列、时间戳和异步发送预算，再处理 `env/observation_processor.py` 的 trace/附加帧/dump 输出与异常恢复、最大长度回放文件持久化。完成后接入正式 memory_budget 检查，再推进长时间增长和稳态性能验收。`gfootball/env` 为索引排除目录，继续直接读源码；已有用户产物和开发质量证据不参与运行时清理。
