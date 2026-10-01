# 当前玩法长赛程参考更新（2026-10-01）

归属 `ms-21.1 → plan-21.1.2 → task-21.1.2.2`，并阻断 `task-22.1.2.2` 的依赖链。`quality.py run task-22.1.2.2` 在 `performance_regression` 停止：旧 `soak_v2` 参考的种子 42 输入哈希相同，但预热哈希与当前引擎不同，说明它已不能作为当前玩法的轨迹参考。此次失败发生在预算断言前，不能解释为长赛程性能退化。

参考更新使用已经通过 ECS 正式比较的 `ecs_v5` 归档引擎 `a02e1db4cff483d7edd2f52dba8749e4cefddadc701c50066ccfad8947779597`，并保留旧 `soak_v2` 的同一长赛程入口二进制 `39fd6ad932508c0dd795651588838a2adf674a43991ad752d9ea012f4ae5f5e7`。`ldd` 确认入口加载归档引擎。分别运行种子 42、43 的完整 1000 预热帧与 36000 测量帧后，两种子均与当前引擎的输入哈希、预热哈希、终态哈希、全部状态检查点及活动帧标记逐项相同；每个种子的稳态与六窗口 p99、RSS 增长、季度漂移和后期平台五项预算也均通过。新基线只更新比较对象，不放宽预算、删改长尾样本或改变工作负载。

生成器 [`soak_reference_refresh.py`](../optimization/diagnostics/soak_reference_refresh.py) 校验引擎与入口的压缩件及原始二进制哈希、实际动态链接、两个种子的原始结果和当前引擎的预算与轨迹，然后生成 [`soak_v3.json`](../optimization/baselines/soak_v3.json)、[压缩原始参考](../optimization/baselines/soak_v3_reference.json.gz)及[四份基线／候选原始日志](../optimization/evidence/soak_v3_validation_20261001.tar.gz)。清单 SHA-256 为 `c9ac77f9dff6a0797cfc2a72fae01bf64158104339713dc7df0d46b77d3496a4`；压缩参考为 `9ac9a61fc8511eb01a8919856702384aa654a382386fa7e9e53bbeca9fb5e4b9`；验证归档为 `58ca49dd77ad4d30493f65744f170682fe34da06f2e381f9eca2d191ea50e2ad`。旧 `soak_v2` 和原历史失败报告保持可追溯。

正式 `python3 .project/quality.py run task-22.1.2.2` 随后完整执行了 15 项检查：前 14 项通过，最后的手感检查失败。新的 `performance_regression` 在本轮通过 42、43 两个完整长赛程，共 212 项断言；种子 42／43 的稳态 p99 分别为 12.850／4.044 ms，五项窗口与 RSS 预算均通过，全部轨迹字段与 v3 参考一致。正式结果见 `.project/optimization/benchmarks/performance-regression-1790838245384713718/report.json`；质量会话日志为 `.project/optimization/benchmarks/quality-soak-v3-feel-20261001.log`。权威状态查询显示 `task-21.1.2.2`、`ms-21.1` 为 `verified`，`task-22.1.2.2`、`ms-22.1` 仍为 `failed`。手感失败涉及 60 次按键中仅 50 次产生实际速度响应，速度 p95 为 224.690 ms，不能用长赛程通过替代手感结论。
