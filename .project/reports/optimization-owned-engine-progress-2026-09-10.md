# 比赛引擎共享容量与所有权实施记录

归属：ms21 → plan-21.1.2 → task-21.1.2.1（网络与回滚内存预算）。状态：局部实现与 Windows 回归通过；`memory_budget.ready=false`，任务、计划及里程碑未完成。

## 审查结论与实现

此前 Core 使用进程共享池，但 frame_sync 的默认工厂直接创建 GameEnv，比赛权威引擎、玩家副本和独立回放可以绕过该实例容量。现在两个应用工厂 `native_engine`、`native_match_engine` 都通过新增 `create_owned_engine` 预留同一个 ENGINE_POOL 名额；Core 的现有复用入口保持原有默认行为。

EnginePool 增加严格布尔参数 `reuse=False`。比赛不复用缓存状态，必要时在创建前关闭空闲实例；关闭比赛直接释放资源。新增 OwnedEngine 检查线程对象、进程、重入和关闭状态，保留的方法引用也经过调用时检查。关闭中仍计数；工厂、代理创建和关闭失败覆盖容量退款及主异常保留。

原始初始化移入 `_initialize_native_engine`，在已预留名额内构造场景、创建和启动 GameEnv、reset；异常关闭部分构造的实例。带身份工厂的约 91 MB 文件扫描也移入这次预留，避免满额请求继续执行扫描，同时避免嵌套取得两个名额。所有权策略的两个源文件加入存档实现身份；旧实现原生存档可能因身份改变而拒绝。

本轮没有修改 Core、C++ 或原生绑定类。公开原始 GameEnv/C++ 上下文入口仍不受 Python 应用工厂计数约束。实例计数不能证明原生字节、RSS 或 GPU 分配已受控。

## 验证

新增 17 项通用所有权用例：实际并发创建与关闭事件、满额时工厂不执行、复用与新实例共享上限、初始化及包装失败、池关闭竞态、保留方法、跨线程、重入、关闭异常、1000 次生命周期引用释放、渲染名额与参数验证。PID 用例显式改变检查输入，不声称执行了 fork。

新增 5 项比赛集成用例使用生产 Host/Join、本地保存继续和回放入口、真实 TCP/UDP socket 与实际文件，通过显式工厂注入独立 MatchOracle。包括三个引擎占满同一个池、第四次拒绝、逐个关闭退还名额，以及副本创建失败和输入回调异常时保留旧文件并关闭资源。没有伪造 GameEnv 模块或从 Core 提取类体替代运行。

以下三套均在最终代码上重跑，失败、错误、跳过及报告所跟踪的残留所有者线程均为零。录制与比赛探针所跟踪的进程及目录锁描述符也为零；资源探针最终共享池 live/leased/idle 均为零。套件有既有回归覆盖，不能把相加结果称为新增测试数。

| 套件 | 通过数 | 源文件数 | 当前报告 |
| --- | ---: | ---: | --- |
| 资源、录制、环境回放接口 | 146 | 33 | [recording](../optimization/benchmarks/python-owned-engine-recording-windows-20260910-a/report.json) |
| 比赛、存档、TCP/UDP 多人 | 201 | 80 | [match](../optimization/benchmarks/python-owned-engine-match-windows-20260910-a/report.json) |
| 共享 TCP/UDP 与恢复 | 219 | 41 | [network](../optimization/benchmarks/python-owned-engine-network-windows-20260910-a/report.json) |

报告 SHA-256 依次为：

```text
8b82ba141c84e3f317fb951e56b4e75143230bfc58263ebc83ac9f8da643f0ad
b1334b457389612beacb57448b03d3a0349d8a8b7b7ec4667f4acaf6b8ef4784
26c145fcb72dee08375c959667acc97e67f3f7ff5e14d824905d713bcd8ac100
```

[汇总证据](../optimization/benchmarks/python-owned-engine-evidence-20260910.json)记录全部报告、日志和源文件匹配结果，以及未执行的原生检查。旧 recording129、UDP match196、上一轮 network219 和旧资源指纹报告因代码变更已过期，文件保留作历史记录，不能继续引用为当前验证。

## 实际文件与验收边界

[当前实际文件报告](../optimization/benchmarks/python-owned-engine-identity-files-windows-20260910-b/report.json)读取资源 90,974,146 字节，单次读取上限 65,536 字节，耗时 3.173371 秒，tracemalloc 峰值 1,155,505 字节。实现策略读取 369,982 字节，耗时 0.490792 秒，峰值 155,348 字节。18 个报告源文件指纹包含两个新增策略输入文件。报告 SHA-256 为 `a6080cb78e5478696b55408a98c033a26e9f97910e779d227690ff9dda0a6364`。

这是 Windows UNC 上的实际文件读取及 Python 分配测量，不是整个进程 RSS、原生库映射或 Linux 性能结果，也不能由两次缓存状态不同的耗时推断加速。资源树及其他策略输入的后续变化仍需重新计算资源指纹。

新增真实 Core/GameEnv 的 3 项准入测试已接入强制原生组，尚未执行。全部环境/原生/渲染 28 项、比赛原生 4 项，以及其他 C++ 网络、POSIX、最大长度持久化和长期增长检查均保留。当前执行平台为 Windows Python 3.14.6；Python 3.9 检查仅为语法 AST。未尝试绕过 Linux 正式验收保护，也未改动 baseline/optimized 指针。

图谱按 Verify 查询并检查覆盖；`gfootball/env` 被索引排除，相关 Core 来源使用直接读取；C++ 绑定所在范围也直接读取。图谱对闭包的调用归属存在误分类，工厂链结论以实际源代码核对为准，未声称完整 C++ 调用或分配审计。

下一步继续自然比赛结束与输入/渲染集成审查，并推进原生上下文字节预算、长时间 RSS、原生共享准入、C++ v4 互通及 POSIX 验收。之后继续手感、网络、渲染、AI 和发布里程碑；局部 Python 检查通过不改变产品级目标的未完成状态。
