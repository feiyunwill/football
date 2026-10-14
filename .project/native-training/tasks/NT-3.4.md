# NT-3.4 — 闭环采样、1/2/4 worker 重放和资源测量

2026-10-15。实现 `training_sampler.collect_episodes` 与真实引擎 benchmark。
依赖已提交 NT-3.3；本轮不改引擎状态语义或旧 Python 默认后端。

## 实现与合约

- 一个 collection 最多1024个唯一 uint63 全局 episode ID，每 episode 最多
  4096步；只保留最多4个当前状态及有界摘要，不存完整 trajectory。
- FIFO episode 分配给空闲 worker，显式 reset，返回结果按输入 ID 顺序。
  seed 与 worker 数量/调度无关。回放要求固定策略及按 episode/step 隔离的
  确定性状态；不隐式 reset 策略 RNG，也不保证在线更新策略的顺序无关。
- 策略读取 reset 或上一 transition 的真实 observation 和 episode/seed/step
  context。on_transition 流式交付 pre/action/post、per-agent/team reward、
  score、terminated/truncated。readonly 初始副本隔离 callback 对内部状态
  的修改；调用者保留的样本/RNG/learner 状态与 callback 时长由其自行管理。
- max_steps horizon 的最后一步 truncated=true；engine terminal 优先，
  terminated=true/truncated=false。学习器不得把 horizon 当作 match terminal。
- callback 异常或无效策略 action 整组关闭并清理；无 implicit retry。
- 策略可复用 NumPy action 缓冲区：每次决策立即验证并复制为普通整数 action，
  再决策其他 episode；否则下一次 inference 会覆盖上一 worker 的动作。
  该问题在提交前自审发现，新增两 worker 的真实联合动作回调测试覆盖。
- 每 episode 记录逐步观测、action、reward、status 的 trajectory SHA256，
  另记录 final canonical kernel hash；摘要不代替完整 checkpoint。

## 验证

18项 worker+sampler专项测试通过。新增六项 sampler contracts 证明：
1/2/4 worker 与 direct scalar 逐值对照及最新 observation；隔离可修改 callback
副本；可复用 action buffer；非法/无限输入提前拒绝；callback失败清理；
真实 terminal/horizon 区分；三次创建四 worker、每 pool 三轮重复采样后
trajectory/hash相同，parent FD无增长，所有 worker PID消失。

完整集成证据 `evidence/nt-3.4-integration-20261015-a/report.json`，最终状态
与测试数量以日志/报告为准。当前代码测量证据为
`evidence/nt-3.4-workers-20261015-b/report.json`，passed=true，前后源码
指纹一致 `ebb98b1f58e51300c02c7cd06197c34fe8875308c628c02432984a5009880b83`。
A轮为 action buffer 自审补充前的开发测量，保留其真实源码指纹；不冒称
它覆盖最终代码。B保存实际 validator版本，源码版本由 manifest/Git追踪。

最终完整集成 passed=true：65 项 Python 测试、四个 C++ 合约和 native
linkage 检查通过，source fingerprint 与 B 轮测量完全相同。任务完成。

## 测量范围与限制

1/11人×cadence2/10×1/2/4 workers，共12 workload，每组3次，worker执行
顺序轮换。每次重放固定4个episode，每episode128-step horizon；20-step
warmup后开始记录。所有episode轨迹、reward/status和最终kernel hashes
跨worker数量及repeat完全一致；每次正常关闭exit codes全0、无PID/FD残留。

计时包含collection的 reset、IPC、策略/stream复制、资源采样和hashing；
startup/warmup/close分别记录并排除。不是纯engine FPS或PPO inference。
资源按Linux /proc读取parent和worker CPU/RSS/FD；CPU ticks为当前主机
SC_CLK_TCK=100，RSS sum重复计算共享页，HWM sum为各进程生命周期最大值，
不代表同时达到的总峰值。parent RSS单独记录；worker RSS不含parent或
multiprocessing内部持久resource tracker，后者先预热再设置FD基线。
validator若总时限900s到期，会kill整个自建benchmark session，避免只杀
父进程而遗留worker。当前测量没有触发该总超时路径。

中位 end-to-end transitions/s：

| 玩家 | cadence | 1 worker | 2 workers | 4 workers |
|---|---|---|---|---|
| 1 | 2 | 773.7 | 1339.3 | 2433.3 |
| 1 | 10 | 238.3 | 396.9 | 670.0 |
| 11 | 2 | 781.9 | 1256.1 | 1910.3 |
| 11 | 10 | 233.3 | 431.7 | 663.1 |

单worker观察RSS约144MiB，四worker RSS sum约576–577MiB（共享页重复计算）。
所有样本/range、CPU及资源数据保留在workers.json；4 worker的1人/c2范围
1752.3–2616.8，显示WSL主机调度波动。只报告本次配置结果，不承诺线性
扩展、通用加速比或相同策略训练收益。

图 Verify coverage generation 2026-10-14T20:55:14Z，已有worker/profile接口
无记录缺口；新文件以直接完整源码核对补证。S3全局review另起审查轮次，
本任务自审和短基准不代替阶段review，也不代替S4算法正确性。
