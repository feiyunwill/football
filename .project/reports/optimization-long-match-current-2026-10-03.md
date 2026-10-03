# 当前源码长局逻辑性能复验

归属 ms-21.1 → plan-21.1.2 → task-21.1.2.2。2026-10-03 执行 `python3 .project/quality.py run task-21.1.2.2`，正式 `performance_regression` 通过 212 条断言、零跳过；`quality.py verify ms-21.1` 也通过。两种子各有 36,000 个实际逻辑帧、3,600 秒模拟比赛时间。模拟时间不等于一小时墙钟，测量范围是无头原生逻辑步进及采样 RSS，不包含渲染、广域网或物理输入设备延迟。

| 种子 | 稳态 p50 / p95 / p99 | 六个窗口中最大 p99 | 预热后 RSS 增长 | 轨迹 |
| --- | ---: | ---: | ---: | --- |
| 42 | 2.023 / 3.106 / 4.000ms | 4.131ms | 73,728 B | 与参考一致 |
| 43 | 2.086 / 3.210 / 4.120ms | 4.217ms | 73,728 B | 与参考一致 |

两种子均满足稳态 p99、每窗口 p99、RSS 增长、四分位漂移和后段平台五项原有要求。种子 42 的单帧最大值仍达到 101.245ms，远高于其 p99；本门禁的 p99 通过不能证明没有偶发可感知卡顿，需由输入手感与产品呈现验收继续覆盖。

[完整机器可读报告与 14 份原始产物](../optimization/evidence/performance_regression_20261003.tar.gz)已逐文件核对字节数及 SHA-256。原始报告 SHA-256 为 `a3f257160b553945afe7476e623373d15c42bd83927498149e2724fba70c622a`，归档 SHA-256 为 `9da05bbcc31761b0bde6470a736e22f7e741286927b9760da7de9660701e3180`。[正式回执](../optimization/evidence/performance_regression.json)与[日志](../optimization/evidence/performance_regression-1791001357548422250.log)保留检查结果。当前性能里程碑由质量系统判定 `verified`；整项产品优化目标继续进行。
