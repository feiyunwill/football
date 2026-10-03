# 渲染分段诊断与训练可靠性预检

归属 ms-24.1 → plan-24.1.2 → task-24.1.2.2，以及 ms-25.1 → plan-25.1.2 → task-25.1.2.1。2026-10-03 当前正式 1080p PBR 渲染门禁仍失败：Intel Arc 140T／私有 D3D12 驱动下双种子 p95 为 32.619/31.921ms，高于 16.67ms，详见[正式失败报告](optimization-smoothing-network-render-2026-10-03.md)。

在独立引擎副本中，对种子 42 的完整 PBR 渲染逐段调用 `glFinish()`。每阶段 150 个样本，以下统计取最后 120 个；强制同步使该诊断的整帧 p95 升至 50.933ms，因此各阶段数字只用于寻找热点，不能替代未插桩产品帧时间。

| 阶段 | 均值 | p95 |
| --- | ---: | ---: |
| G-Buffer 几何 | 5.131ms | 7.983ms |
| IBL 合成 | 4.408ms | 7.355ms |
| 直接光照 | 5.121ms | 8.712ms |
| Bloom | 3.183ms | 5.814ms |
| FXAA | 3.241ms | 6.010ms |

曝光、色调映射与 IBL 准备也保存在机器报告中。诊断副本通过动态链接检查确认加载独立引擎库；正式引擎源码未改变。

针对直接光照九次阴影采样，隔离素材候选让背向光源的像素提前返回零。种子 42 的基线/候选 p95 首轮为 24.858/31.423ms，反向顺序复轮为 32.557/34.201ms；种子 43 候选/基线为 33.136/32.890ms。没有稳定收益，候选未采纳，也未用缩减采样或降低内部清晰度替代画质。独立 Wayland 请求在当前 SDL 构建返回“wayland not available”；其 socket 存在并不证明后端可用。

独立执行当前源码 `training_reliability` 检查通过 51 条断言、零跳过：38 项原子文件测试，212 项 PPO 归档成员，真实训练检查点从步骤 1 跨进程恢复到步骤 2；截断、摘要损坏、维度错误、无封印旧格式、零保存周期、不可写目标六类情况均被拒绝。单环境保护和 Debug 编译标志也经检查；训练二进制 SHA-256 为 `706b3e3f5f0518607b9580a82b86d494174803f7bb2807bc3c269d275d3b877a`。[回执](../optimization/evidence/training_reliability.json)及[日志](../optimization/evidence/training_reliability-1791005345184142827.log)保留结果。此检查是绕开未满足的里程碑前置条件进行的独立预检；`task-25.1.2.1` 和 ms-25.1 仍未通过，固定种子 AI 对照门禁 `ai_regression` 仍未实现。

[机器报告](../optimization/evidence/render_ai_diagnostic_20261003.json)、[逐文件清单](../optimization/evidence/render_ai_diagnostic_20261003_manifest.json)与[23 份原始诊断文件归档](../optimization/evidence/render_ai_diagnostic_20261003.tar.gz)保留源码副本、候选着色器与原始测量。机器报告 SHA-256 为 `a23de5bee965c3b4229fbc0eb642048ea2563d0033a65bfcd0636ae5ed0980ca`，归档 SHA-256 为 `85a92fd2af1238a5a978fffbe849b36dae26af370a1dd90e0806447f9d0d039c`。下一步需解决真实窗口的 GPU 与呈现开销，并建立固定种子 AI 结果统计及退化检查；两项任务目前均不可标记完成。
