# 重复重启 RSS 遥测复核

归属 ms-20.1 → plan-20.1.2 → task-20.1.2.2。2026-10-02 的正式 `architecture_regression` 在完整 Debug ASan/UBSan 下进入 `engine_lifetime_contract`，因“Repeated restart retained match-sized allocations”失败。此前日志只写出错误文本，未给出触发失败的 RSS 数值。现在保留原 12 次重启、cycle 3 基线、16MiB 限制和 167 条断言，并记录每次销毁后的 RSS；失败时先打印完整轨迹。没有更改通过条件或引擎资源释放代码。

以正式门禁的 Sanitizer 选项重新构建合同后，连续运行三次，均通过原断言。第 3 次重启后到最后一次的 RSS 差值分别为 958,464、3,096,576、2,662,400 字节。三轮中单轮最大与最小 RSS 差分别为 27,295,744、14,204,928、21,434,368 字节；第一轮中间一次从 336,052,224 降至 318,779,392 字节，下一次回升至 339,173,376 字节。说明 RSS 轨迹会波动，单次基线可能敏感，但三次通过不足以解释正式失败，更不能证明不存在泄漏。原失败回执保持失败，不调整阈值。

[逐轮完整报告](../optimization/evidence/lifetime_rss_telemetry_20261002.json)及[报告与原始日志](../optimization/evidence/lifetime_rss_telemetry_20261002.tar.gz)保留源码／二进制 SHA-256、环境参数、耗时、返回码及 12 点轨迹。报告 SHA-256 为 `4bea34a7d8f065fd30826a866b60e3d42a5256f7e2e4033cfde7869d6fec3f32`，归档 SHA-256 为 `0416e63869b487ff6cb357fcf9110b6085d2bf5e6d80891b66e8e0daa6ea1511`。

随后 `python3 .project/quality.py run task-20.1.2.2` 的完整依赖链通过。正式架构检查在 173 个完整 Debug ASan/UBSan 编译单元上完成 1,632,097 条断言、零跳过，耗时 644.035 秒；其中重复重启合同的预热／结束 RSS 为 336,089,088／334,577,664 字节。[正式回执](../optimization/evidence/architecture_regression.json)和[正式日志](../optimization/evidence/architecture_regression-1790937065386020769.log)已记录，当前任务状态由质量系统判为 `verified`。此前的失败仍保存在旧日志，表明运行间差异未消除；本次通过不能证明偶发问题已修复。下次失败时，新增遥测可以区分持续上涨与瞬时低基线，16MiB 门禁继续执行。
