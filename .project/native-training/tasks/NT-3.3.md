# NT-3.3 — 有界 native 进程采样及 episode 协议

2026-10-15。实现 `gfootball.training_workers.NativeWorkerPool`，每个 spawn
子进程在其主线程创建并拥有一个 native C++ FootballEnv。父进程没有传递
引擎对象，也不复用 fork 后的引擎；Python 负责场景和 IPC 编排，采样动作、
观测、奖励及终止仍由已有 C++ 内核实现。纯 C++ 训练入口属于 S4。

## 合约与资源边界

- 每 pool 1..4 个 worker，每轮对选中 worker 各一个在途请求/响应；没有
  后台队列、自动 reset、自动重试或失败后继续使用部分成功状态。
- reset 显式传入 worker -> 全局 episode ID，step 显式传入 worker -> action。
  可选择非空子集；结果按 worker 排序。支持单/多人、左右队、两种 115 布局、
  stacking、checkpoint rewards 和 default/v2 离散动作。
- seed v1 使用 SHA256(tag + base_seed uint64 + episode_id uint63)，得到 uint64
  Gym seed，经既有 PCG64 选择引擎 seed；不依赖 worker ID、数量或完成次序。
  episode ID 的唯一性/分配由调用者拥有，重复 ID 明确重放同一 episode。
- 环境 JSON 配置最多 8 KiB；每条 frame 最多 32 KiB，其中 JSON metadata
  最多 8 KiB，观测/agent rewards 为 little-endian float32。最大 11×460
  观测已经验证。运行期不发送 Python 对象或 pickle；multiprocessing spawn
  本身使用其内部启动序列化。这些为 per-pool 限制，不承诺 RSS 配额。
- 父进程 nonblocking socket + selector 同时写/读有界 frames，一个全局
  deadline 覆盖本轮全部 worker。完整 header 后只有部分 body 的卡死仍超时。
  请求 ID、operation、protocol version、shape、buffer 长度和有限值均校验。
- 所有行动/episode 参数先在父进程整轮验证再发送。终态必须显式 reset。
  创建 process/thread 拥有 pool；错误使用不改变正常 pool。
- 远端错误、通道异常、worker 退出、超限/错误帧、deadline 统一关闭整组。
  正常 close 等待 native cleanup acknowledgement；失败 terminate，再 kill
  并 join，释放 Process handles。记录 PID/exit codes；close 可重复调用。
- 默认 startup 60s、round 30s，均可配置为 (0,300]；清理额外最多约5s。
  fork 仅用于所有权拒绝测试，生产 worker 固定 spawn。
- `digests()` 在 worker 对 canonical kernel state bytes 计算 SHA256，父进程
  只接收 32-byte hash。不是 snapshot，也不是完整 learner checkpoint。

## 验证与任务自审

12 项专项真实进程测试通过：单人 simple115 和右队多人 simple115v2/stack/
checkpoints 对 scalar 的逐值、奖励/终止及 final hash 对照；局部 reset 不改变
其他 worker；返回数组互不共享；最大矩阵；非法整轮保留所有状态；startup
异常/超时；未 reset 远端异常；SIGKILL；超大 header；半消息超时；process/
thread ownership；真实 match-clock 终态。正常 close 的两 worker exit codes
均为0；故障后 active_children 无残留。

测试发现原 native get_state_digest 是待校验的 canonical 字节，而非短 hash，
已改为进程内 SHA256，未通过放宽消息容量绕过。稀疏 academy 场景没有两个
右队可控制玩家，右队对照使用真实 11_vs_11_easy_stochastic。

完整隔离构建/集成证据：
`evidence/nt-3.3-integration-20261015-b/report.json`。验证入口加入 worker tests；
最终 passed、实际数量及 source fingerprint 以该报告/日志为准。

B 轮 passed=true：59 项 Python 测试、四个 C++ 合约及 native linkage 检查
通过，源码/资源前后指纹一致。任务完成；阶段 review 仍待 NT-3.4 结束。

A 轮完整集成通过 59 项 Python 测试和四个 C++ 合约。提交前自审补充联合
NumPy action 的形状检查必须先于 list 转换，以保证不为错误的大数组分配
无界列表；测试用 100-million 项 zero-copy broadcast 输入验证提前拒绝且
所有 worker state hashes 不变。B 轮验收包含该补充，并保留 A 轮原始证据。

任务自审核对 public owner checks、全量 prevalidation、单在途 framing、所有
异常清理路径和 normal close 生命周期。未改动引擎、渲染、网络、旧 Python
默认后端或 snapshot 格式；本轮不是 S3 全局 review。图 Verify tier 使用
project root-work_space-football，coverage generation 2026-10-14T20:42:12Z
现有接口无记录缺口；新文件 freshness changed/missing 后直接读取完整源码。
索引的 gfootball/env 是 excluded subtree，未据此作穷尽依赖声明。

后续 NT-3.4 实现反馈策略循环、跨 1/2/4 worker 的 episode 分配/重放及资源/
吞吐压力测量；不将本任务短测试作为加速证据。Windows/macOS 交付留待 S5。
