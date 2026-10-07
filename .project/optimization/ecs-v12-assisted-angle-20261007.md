# ECS v12：辅助移动后的同玩法性能基线（2026-10-07）

对应 `task-21.1.1.2`。手感修复将新手动输入与动画目标方向的对齐阈值从 0.5 调整为 0.45；旧的 v11 ECS 基线因此不再代表当前比赛轨迹。正式质量链在 `ecs_performance` 的 `final_hash` 等价检查处停止，失败日志为 `evidence/ecs_performance-1791302005451222363.log`（SHA-256：`dae5f3ae6fbabf3d3bd8798568de2b3f936d22f9a003658bbc3cc535136f465b`）。v11 的种子 42/43 最终哈希为 `75efd961f0df2a5c` / `81a116c628c1a390`；当前玩法对应 `0629d4c5adfb830c` / `913bb9eb2193252c`。不能把这个失败当成性能回退，也不能绕过轨迹等价断言。

新建的 [v12 清单](baselines/ecs_v12.json)固定源提交 `0dcb71f`、完整 Release 编译契约、未优化二进制、[只回退 ECS 优化的补丁](baselines/ecs_v12_perf_rollback.patch)、v11 父清单 SHA-256，以及两次独立重放和分配剖面。旧版 v11 文件保持不变。种子 42、43 的未优化重放与当前优化版在输入、热身、最终状态、状态检查点和活动标志上逐项一致；生成记录见 [原始基线](evidence/ecs_assisted_angle_preperf_reference_20261007.json.gz)与[预检](evidence/ecs_v12_preflight_20261007.json.gz)。

在同一 CPU 上，Release 二进制按两种子各 15 对进程交替比较，共 60 次未插桩测量。逐次结果、编译命令、二进制哈希、Sanitized 查询合同和独立分配剖面保存在 [配对证据](evidence/ecs_v12_paired_20261007.json)及其压缩原始记录中。结果如下；比值均为优化版／未优化版，低于 1 表示改善。

| 种子 | CPU 几何均值比 | CPU 95% bootstrap 上界 | 墙钟几何均值比 | p99 中位配对比 |
| --- | ---: | ---: | ---: | ---: |
| 42 | 0.8421 | 0.8641 | 0.8420 | 0.7164 |
| 43 | 0.8135 | 0.8435 | 0.8134 | 0.7556 |

配对检查报告 `passed=true`、1,590,027 项断言、零失败；7 项 ECS 单元测试和 v12 封存基线预检也通过。正式质量编排已从头运行，`ecs_performance` 在当前源码上通过，见 [正式检查记录](evidence/ecs_performance.json)及其日志。最终里程碑状态仍由完整依赖链判定。

复现基线需从清单记录的提交创建隔离工作树，应用 v12 回退补丁并构建 Release `engine_match_benchmark`；执行 `python3 .project/optimization/diagnostics/ecs_reference_refresh_v12.py --worktree <worktree> --build <reference-build> --candidate-build <current-build>`。执行正式对照使用 `python3 .project/checks/ecs_performance.py`；它验证封存链、编译器、轨迹、配对性能和分配约束。
