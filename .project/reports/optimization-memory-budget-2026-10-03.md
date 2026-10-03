# 网络与回滚容量边界复验

归属 ms-21.1 → plan-21.1.2 → task-21.1.2.1。2026-10-03 在当前源码上执行 `python3 .project/quality.py run task-21.1.2.1`，`memory_budget` 正式通过：1,400 条断言、零跳过，覆盖 29 组容量场景、60 项构建／执行命令。检查包含普通与完整 Debug ASan/UBSan 的网络容量合同，以及实际回放文件、Python 帧同步和录制边界；状态由质量系统判为 `verified`。

完整[机器可读报告和 406 份原始产物](../optimization/evidence/memory_budget_20261003.tar.gz)已归档。归档前逐文件核对了报告记录的字节数与 SHA-256；合计 48,585,869 字节压缩为 3,268,888 字节，归档 SHA-256 为 `9a6c1eb8b399b28568a0ff3e5ff9c5f73bdb6dc279ebf62e8b2c96493797129e`。报告原始 SHA-256 为 `b3e3a0baca6e8daa90159db8431e11fc5eb8d660c8136135907d4b857970ff0e`，[正式回执](../optimization/evidence/memory_budget.json)与[日志](../optimization/evidence/memory_budget-1790999968264429613.log)保留运行结果及日志哈希。

该门禁证明输入、历史、日志和连接发送队列的上界及可复现的过载／恢复行为。报告明确排除整个进程 RSS、GPU 内存、广域网、身份验证、跨实现互通与产品输入手感；这些不能由本次通过推断完成，仍由后续任务验收。
