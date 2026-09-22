# 2026-09-14：TCP 恢复正式接入与分段回放验证

链路：ms-23.1 → plan-23.1.1 → task-23.1.1.2。该任务和整个优化阶段仍在进行，未提升 network_reconnect、产品延迟或硬件验收状态。此前的[传输候选报告](optimization-native-recovery-transport-2026-09-14.md)保留为接入前的历史记录。

## 已进入正式源码的实现

本轮正式采用 8 个文件变更：现有 EngineTCPServer 的 FNRC 分支、凭证/报文/快照传输三个头文件、独立摘要实现、生命周期测试、CMake 及 sources.cmake 登记。旧协议分支保留。SHA-256 实现移入传输专用静态库，OpenSSL 头文件只在实现文件中使用，AI 与核心引擎不再因公开头文件承担该依赖；核心 engine 动态库哈希未变化。

两种构建的全部 7 个原生产品入口与本轮相关合同测试均已重建，对象依赖检查无过期项、无候选目录依赖。Python bindings 仍关闭，本轮没有重建 Python 扩展。变更前的源码、产物、对象及构建元数据均先归档，原始证据可通过原路径和哈希精确解析。

证据：[8 项变更](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-a/changes.json)、[原件归档](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-a/original-archives.json)、[Release 依赖检查](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-a/release-freshness.json)、[ASan 依赖检查](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-a/sanitized-freshness.json)。

## 正式入口验证与保留的失败

正式服务端在 Release/ASan 中分别通过 7 次实际协议恢复，各捕获 429 个权威帧及 7 份快照；协议端为独立 Python 实现，尚不是具有自动恢复功能的原生客户端。两份捕获分别交给两种构建的独立 GameEnv 复验，4 次运行合计 22520 条断言，快照恢复后的每帧状态均与从比赛起点重放得到的状态一致。两种构建也均通过旧 FNAT 握手和现有 TCP/UDP 实际客户端兼容基线；这些客户端在自身连接断开后仍退出。

首次正式 ASan engine_tcp_client_contract 在约 31.33 秒后报“actual TCP reconciliation/hash verification stopped”。原检查按失败停止，未更改超时阈值或断言。随后接入前服务端、接入后带诊断版本、未修改的正式测试各重复 3 次，全部通过，但未复现原始失败，根因仍未确定。后续通过不覆盖原失败，也不能视为稳定性问题已修复。

诊断夹具另有两次构建失败：一次修改误匹配保留的注释代码，一次输出文件名与包含目录冲突；均保留日志，独立后继阶段修正夹具。这些错误与产品运行失败分别记录。剩余 ASan 报文、实际 FNRC、旧产品兼容与四次交叉回放在后继阶段完整运行并通过，原阶段 EXIT1 保持不变。

证据：[原始失败](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-a/execution/sanitized-engine_tcp_client_contract.log)、[接入后诊断三次结果](../optimization/benchmarks/native-recovery-tcp-diagnosis-20260914-b/results.json)、[接入前及正式产物对照](../optimization/benchmarks/native-recovery-tcp-diagnosis-20260914-c/report.json)、[剩余正式入口检查](../optimization/benchmarks/native-recovery-tcp-adoption-20260914-b/report.json)。

## 已验证、尚未接入客户端的分段回放

候选 NativeRecoveryJournal 只记录实际确认输入。断线造成的帧缺口由包含绝对帧边界、引擎状态哈希、SHA-256 与快照内容的检查点表示；不补写不存在的输入。记录帧数与绝对 next_frame 分开。没有检查点时保持原 FNRPLY1 字节格式，有检查点时使用 FNRPLY2；旧播放器明确拒绝新版本，新播放器兼容旧版本。

检查点最多 32 个，保留快照总量最多 8MiB、每份最多 1MiB；原帧记录预算最多 32MiB/100000 帧。额度耗尽保留可读取的前缀。新播放器拒绝损坏摘要、截断、尾部多余数据、未标记的帧缺口、边界回退和不一致的同边界哈希；加载失败不改变此前成功加载的回放。快照单独构成可保存内容，帧计数仍为零。凭证和连接代次不写入持久回放。

| 验证范围 | 结果 |
|---|---|
| 独立 Python 字节预期、旧格式、损坏/截断、预算、快照单独保存及原子替换 | Release/ASan 各 5 项、1574 条断言 |
| 未修改的原回放文件与目录测试，针对新头文件重新编译 | 两种配置各 10 + 16 项，全数运行 |
| 正式 TCP 捕获 → 分段记录 → 原子保存 → 重新加载 → 独立 GameEnv 恢复 | 两种构建 × 两组捕获，4 次运行各 3416 条断言 |

真实回放每次使用完整 429 帧权威流作为参照，持久保存 7 份真实快照及 64 个实际记录帧；365 个缺失帧由明确的快照跳转覆盖。每条保存输入均与捕获的权威输入比对，每次恢复边界、每个保存帧及终态哈希均与独立连续运行的引擎一致。该结果证明候选回放持久化与恢复路径，不证明实际客户端已经自动重连。

首轮 Python 预期夹具因循环变量覆盖了全局合成状态而失败；后继阶段只修正变量名，保留原失败证据。

证据：[候选回放实现](../optimization/benchmarks/native-recovery-replay-20260914-b/overlay/frame_sync/native_recovery_replay.hpp)、[组件与文件验证](../optimization/benchmarks/native-recovery-replay-20260914-b/report.json)、[真实分段回放及旧存储回归](../optimization/benchmarks/native-recovery-replay-20260914-c/report.json)。

## 下一步任务

1. 在现有原生 TCP 客户端接入自动重试、连接代次校验及恢复状态机；恢复期间继续处理窗口事件，禁用旧连接的输入发布。
2. 在引擎所属线程执行快照恢复和哈希校验，再重置预测、输入历史与发布时钟；使用上述分段回放保存真实恢复过程。
3. 推进 UDP 可靠分片与实际客户端恢复，验证双方槽位、多次断网、丢包/乱序/延迟、慢接收、过期凭证、AI 交还及资源清理。
4. 继续定位本次未复现的 ASan legacy 客户端失败，以及已有 UDP 严格窗口缺口、50ms p95、硬件渲染和比赛/训练质量条件。

系统熵目前使用 Linux getrandom；摘要和明文凭证不提供传输加密或服务端身份认证。既有保护基线和验收阈值保持原值。
