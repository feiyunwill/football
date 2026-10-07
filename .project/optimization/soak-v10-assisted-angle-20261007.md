# 长赛 v10：辅助移动后的同玩法参考（2026-10-07）

对应 `performance_regression`。手感逻辑修复后，旧 v9 参考与当前 36,000 帧比赛轨迹不再一致；正式链在种子 42 的 `warm_hash` 比较处停止，失败日志为 `evidence/performance_regression-1791306604019968799.log`（SHA-256：`caa295657e82ff99cd6d72153dba3b63867bf4e5ad42d9a5a426b714d9b7328c`）。v9 的种子 42/43 热身哈希为 `23f3096aaf6a74f8` / `87570badd45daa27`；当前玩法为 `f0dba7f0d5543b86` / `48ff16c6a793a676`。该失配不能当作速度或内存退化，也不能删除轨迹比较。

[v10 清单](baselines/soak_v10.json)沿用固定的 v2 长赛可执行文件，加载 [ECS v12](baselines/ecs_v12.json) 所封存的未优化、当前玩法引擎；清单固定 v9 父参考、源码提交、二进制、生成器、测量合同及原始证据哈希。旧版 v9 保持不变。两种子各运行 1,000 热身帧与 36,000 测量帧，未优化参考和当前引擎的输入、热身、最终状态、检查点及活动标志逐项相同。原始结果与动态链接记录保存在[验证归档](evidence/soak_v10_validation_20261007.tar.gz)。

当前引擎在两种子的测量帧 p99 分别为 **6.739 ms** 和 **6.723 ms**，低于 50 ms；六个 6,000 帧窗口的 p99 均达标。热身至结束的 RSS 增量分别为 **72 KiB** 和 **144 KiB**，低于 4 MiB，季度漂移与后期平台期断言也通过。两次 `soak_analysis.assess` 各报告 106 项断言、零跳过、零失败。这里的 3,600 秒是模拟比赛时间，不是连续运行一小时的墙钟证据。

生成器为 `python3 .project/optimization/diagnostics/soak_reference_refresh_v10.py --baseline-dir <archived-engine-dir> --candidate-42 <seed-42.log> --candidate-43 <seed-43.log>`；它在封存前重新验证引擎和长赛程序的压缩及解压哈希、动态链接、轨迹和资源预算。更新后的 `performance_regression.reference_runs()` 已验证 v10、v9 和 v8 的历史链，以及声明的源码输入范围。正式质量编排已从头运行，`performance_regression` 在当前源码上通过，见 [正式检查记录](evidence/performance_regression.json)及其日志。最终里程碑状态仍由完整依赖链判定。
