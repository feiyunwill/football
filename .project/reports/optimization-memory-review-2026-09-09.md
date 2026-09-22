# task-21.1.2.1 — 容量任务的前置代码审查

2026-09-09。当前任务 21.1.1.2 正在正式验收。下表记录后续容量任务的实际入口和已有约束；这些发现尚未代表容量任务通过，复现、修复与过载测试将在该任务中执行。

| 入口 | 已有边界 | 需要验证或补齐的边界 |
|---|---|---|
| [FrameSimulation](../../engine/src/frame_sync/frame_simulation.hpp) | 权威帧窗口 1024；预测历史至多 8 帧；确认哈希最多 1024 项 | slots 只检查非零；快照数量受限但没有字节预算；超预算时须在推进模拟前停止预测，并保留可恢复状态 |
| [ClientState](../../engine/src/frame_sync/client_state.hpp) | 通过 max_buffered 限制快照个数；抖动样本 100 项 | 构造参数没有上下界检查；负值会使淘汰循环继续访问空 deque；快照字节没有上界；重复帧和异常保存回调需要覆盖 |
| [ReliableUDPChannel](../../engine/src/frame_sync/reliable_udp.hpp) | 最大重传次数 5；RTT 样本 32 项 | Send 没有检查 pending_ 包数/字节预算；len 转 uint16_t 前未限制，需覆盖超长发送、无 ACK、发送失败与队列恢复 |
| [TCP 客户端](../../engine/src/frame_sync/integrated_client.cpp)与 [UDP 客户端](../../engine/src/frame_sync/integrated_client_udp.cpp) | 权威输入队列和待比对哈希有 1024 项限制；TCP 到达时间样本也有 1024 项限制 | 接收缓冲区增量追加需要独立字节上限；解析返回 0 的无效消息不能永久阻塞在缓冲区前端；队列满时不能静默丢失权威数据后继续错误模拟 |
| [大厅连接](../../engine/src/frame_sync/lobby_server.hpp) | 每连接发送队列 128 KiB；断开连接后从 clients_ 清理 | 总连接数、接收缓冲区、慢客户端及在途异步写的清理需要实际套接字测试 |
| [ReplayRecorder / ReplayPlayer](../../engine/src/frame_sync/replay_system.hpp) | 目前 frames_ 持续追加；序列化数据记录帧数与槽位数 | 记录帧数、输入槽位、场景字符串和序列化总字节需受预算约束；反序列化需先验证长度，再提交完整结果；到达上限时给出可检查状态 |
| [NetworkDiagnostics](../../engine/src/frame_sync/network_diagnostics.hpp) | RTT 样本已有固定个数限制 | 检查数值输入边界及统计溢出；不应重新实现已有环形样本上限 |
| [MessageQueue](../../engine/src/types/messagequeue.hpp) | 消费时移除消息，销毁前已有 Clear | 需要先追踪实际生产者、消费者与线程关系，再定义容量和满载处理；不能直接丢弃具有资源释放或渲染含义的命令 |

验收应覆盖“填满—拒绝/背压—继续消费—恢复”，同时检查消息顺序和资源释放。数量限制与字节限制应分别记录，避免少数超大快照绕过帧数限制。入口非法参数、慢读端、无 ACK、重复/极远帧号和解析失败都应进入可复现用例。

项目验收日志和性能原始证据属于保留的开发产物，不应为满足游戏运行时日志预算而删除。游戏日志的实际入口、保留策略及长时间增长需要继续追踪；未找到入口不能视为已完成。

## 继续核对的实际行为

- base/log.cpp 的 Log 当前同步写标准输出，没有保存历史日志容器。ctime 使用共享静态缓冲区；FatalError 分支还会故意访问非法地址触发崩溃。这是实际的并发诊断/错误处理缺陷，需要独立回归，不能靠删除日志隐藏问题。当前只读搜索 base/frame_sync/systems，不能据此宣称整个工程没有文件日志。
- integrated_client.cpp 的 fopen 入口用于把 ReplayRecorder 序列化到 replay_<seed>.bin，并非日志队列；其内存边界应归回放预算。
- FrameSimulation 的预测在 save_state 之后、step_frame 之前建立快照。预算拒绝应发生在推进之前；错误预测的重演会替换每个历史快照，必须同时处理重演期间的快照膨胀，不能只限制首次预测。
- 输入向量和快照字节的 retained capacity 也占内存；仅检查 size 会漏过小内容、大 capacity 的容器。检查接收参数前先分配构造历史同样不能算有效入口限制。
- 优先给每个预算定义填满、拒绝、消耗、恢复和可观察的原因；不静默丢弃权威帧后继续错误模拟。只读确认后，再在 task-21.1.2.1 实施与测量。

## 后续实现顺序与约束（设计，尚未实现）

1. 先补 FrameSimulation / ClientState 的数量与字节约束，基于当前实际约 86–89 KB 的快照记录默认值及余量。预测预算不足时在 step_frame 之前停止预测，继续消费权威帧；重演中快照增长也必须受限，并能回到已确认状态。重复快照应替换而非叠加，构造参数须在容器分配前验证。
2. ReplayRecorder 限制帧数、槽数、场景文本与保留字节；ReplayPlayer 先检查声明长度和实际余量，再分配临时数据并一次提交，失败保留原播放状态。Stop/Start 必须重置 total_frames/final_hash，录制到限后客户端仍能保存已完成部分（现有 save_replay 仅在 IsRecording 为真时保存，需一起调整）。
3. ReliableUDPChannel 的 Send 在序号增长和分配之前验证最大载荷、包数及字节；ACK/重传耗尽/发送失败分别正确释放占用。确认 integrated_client_udp.cpp、asio_server_engine.cpp、asio_server_udp.cpp 的真实调用路径，不把图索引未显示调用者当作无调用。
4. 大厅已有 128 KiB 发送字节上限，RoomManager 已有 256 房间限制；补连接数、发送消息数、接收缓冲区与非法声明长度边界。持有 mu_ 的解析函数不能直接重入同样加锁的断开函数；取消写时不能释放仍被异步操作引用的缓冲区。
5. TCP integrated_server.cpp 和旧 asio_server.cpp 仍使用同步 asio::write；发送背压需要有界异步队列，真实慢读端测试证明其他连接继续前进。设计共享的发送队列时，必须保持在途数据直到回调完成，析构后回调不访问销毁的 socket/会话；字节预算应包含在途消息。客户端同样核对，不只修大厅。

以上不是通过证据。新预算的默认数量和字节仍须通过实际输入、最慢读端、回滚、失败恢复及资源检测验收后定稿。
