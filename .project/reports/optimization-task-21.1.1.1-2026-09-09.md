# task-21.1.1.1 — 真实比赛性能基准验收

2026-09-09：正式执行并验证 task-21.1.1.1，通过。下一任务为 task-21.1.1.2（查询与分配热点优化）。ms-21.1 性能里程碑及整个产品级优化目标仍未完成。

## 实现

- 新增正式引擎测量程序 [engine_match_benchmark.cpp](../../engine/tests/engine_match_benchmark.cpp)，通过 CMake 独立目标构建，11v11、种子 42/43、四个外部输入槽位。
- 新增 [自动测量与证据校验](../checks/match_benchmark.py)：每种种子五个独立进程，各预热 200 帧、测量 2000 帧；保存原始耗时、CPU 时间、RSS、完整状态检查点与运行环境。
- 每次测量后从预热快照重演，最终哈希必须一致；五次进程间的输入、途中状态与比赛进行标记也必须一致。
- 八项负向测试拒绝缺失样本、篡改分位数、无效时间推进、静止轨迹、缺少独立进程及重演失败；全部 37 项验收框架测试通过。
- [测量契约](../optimization/performance-benchmark.md)明确 startup、预热、稳态与诊断边界。未在本任务中更改模拟算法或声称获得优化收益。

## 正式结果

环境：Intel Core Ultra 9 285H，WSL2 Linux 6.18.33.2，固定 CPU 0，GCC 16.2.1 20260810，Release/C++23/-O3 -DNDEBUG。实际编译数据库包含 127 条命令；性能二进制无 ASan/UBSan/Python 运行时依赖。

每个逻辑帧推进 100 ms 模拟时间（十个 10 ms 物理 tick）。下表耗时单位为 ms，RSS 单位为 MiB；分位数根据每种种子的 10000 个原始稳态样本合并计算。

| 种子 | 启动 p50 | 稳态 p50 | p95 | p99 | 最大帧耗时 | 稳态 RSS 最大采样值 |
|---|---:|---:|---:|---:|---:|---:|
| 42 | 162.297 | 2.587 | 3.913 | 5.066 | 27.464 | 83.836 |
| 43 | 167.907 | 2.898 | 4.578 | 5.765 | 9.703 | 83.801 |

20,000 个正式稳态样本中，19,970 个属于比赛进行中，30 个属于停球阶段。两种种子的各进程稳态 RSS 增量最大均为 40 KiB。563 项基准断言通过，零跳过。

固定输入哈希：b7f3bcf2014e649e；最终状态：种子 42 为 177cf7205a3272f3，种子 43 为 39ceb7b90729ca35。

预检的同源码 p99 为 5.292 / 5.746 ms，正式结果为 5.066 / 5.765 ms；各独立进程分位数与最大帧耗时均保留。这种波动必须在优化前后交错复测中处理，不能单独对比两批摘要就宣称收益。

## 前置回归

- 原生七程序与 Python 适配层边界、重定位打包通过。
- 421 项 C++、165 项 Python 回归通过；两种种子、各两个独立进程的 1000 帧回放一致。
- 状态归属 8190、多实例生命周期 390、快照与渲染契约 3568 项断言通过。
- 完整原生引擎 ASan/UBSan 架构回归 4473 项断言通过，无跳过或 sanitizer/泄漏错误。审计 127 条配置的编译命令，实际执行构建的核心库与四个测试宿主；不将未构建的可选目标计为已执行测试。
- 正式命令 python3 .project/quality.py run task-21.1.1.1 与 verify task-21.1.1.1 均返回 0。

## 可复现证据

- [正式原始数据](../optimization/benchmarks/match-1788934778888605920.json)，SHA-256：739da497c8128772726fe87bf321c7541e5804d84f02323292564ed679e42fb5。
- 源码身份：d5098f8bc112958cfed2c848263e9eb8f852065cb24691c81495e08e2ed0b32d；记录 881 个源码/资源文件的 SHA-256，测量前后检查未变化。
- [基线定位信息](../optimization/benchmarks/baseline.json)记录二进制 SHA-256、源码身份、正式数据路径和保留位置。
- 优化前可执行文件与引擎库保存在 /tmp/football-optimization-baselines/d5098f8bc112958cfed2c848263e9eb8f852065cb24691c81495e08e2ed0b32d。指定该目录为 LD_LIBRARY_PATH，可独立于下一次构建使用。另一次重定位运行通过 60 项检查，种子 42 的完整检查点、输入、最终状态与正式运行一致。该额外运行不计入正式 20000 帧性能摘要。

| 门禁 | 耗时（秒） | 证据日志 |
|---|---:|---|
| quality_selftest | 1.369 | [quality_selftest-1788933851432077833.log](../optimization/evidence/quality_selftest-1788933851432077833.log) |
| native_boundary | 3.145 | [native_boundary-1788933852855569618.log](../optimization/evidence/native_boundary-1788933852855569618.log) |
| framework_regression | 27.607 | [framework_regression-1788933856211309741.log](../optimization/evidence/framework_regression-1788933856211309741.log) |
| state_ownership | 1.657 | [state_ownership-1788933883993602054.log](../optimization/evidence/state_ownership-1788933883993602054.log) |
| environment_lifetime | 21.814 | [environment_lifetime-1788933885820008034.log](../optimization/evidence/environment_lifetime-1788933885820008034.log) |
| simulation_contract | 14.207 | [simulation_contract-1788933907796932395.log](../optimization/evidence/simulation_contract-1788933907796932395.log) |
| architecture_regression | 730.684 | [architecture_regression-1788933922174008266.log](../optimization/evidence/architecture_regression-1788933922174008266.log) |
| match_benchmark | 126.054 | [match_benchmark-1788934652938814396.log](../optimization/evidence/match_benchmark-1788934652938814396.log) |

## 范围与下一任务

该基线仅代表记录的 WSL 开发机器。文件系统缓存未清空，主机温度、负载与动态频率未锁定；没有宣称磁盘冷启动、目标 GPU 帧率或跨平台速度。短时 RSS 结果不替代后续长期运行与队列预算验收。CI 的完整新增优化阶段尚未远程执行。

下一任务先针对实际调用路径定位查询与分配成本，再缓存组件池、改善候选实体选择。需要覆盖三种不同组件、空世界只读查询和回调删除实体等边界；保留实体顺序及状态哈希，使用已保存二进制进行交错对照。网络与回滚内存预算、性能总验收、手感、网络、渲染和 AI 等任务继续按依赖顺序推进。
