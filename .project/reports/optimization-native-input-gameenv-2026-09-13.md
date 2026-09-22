# 原生输入与真实 GameEnv 集成验证

2026-09-13。归属 ms-22.1 → plan-22.1.1 → task-22.1.1.1／task-22.1.1.2。独立阶段 B 已成功终止；Release 和全核心 ASan／UBSan 各通过 3901 条断言、零跳过。两个种子各自验证完整控制器输入、松键／失焦／手柄断开释放、暂停恢复的中性输入屏障、实际受控球员方向响应，以及快照重演的一致性。

每种构建共执行 778 次显式 GameEnv 步进，另通过真实帧同步回调完成 82 个权威帧确认和 74 次纠正回滚，逐帧哈希精确一致。等待时重复申请同一帧不重新消费输入；追帧后的新输入绑定实际下一帧。Release 测试耗时 4.843 秒，ASan／UBSan 耗时 140.831 秒。

[实际报告](../optimization/benchmarks/native-input-gameenv-20260913-b/evidence/report.json) SHA256 为 8a70613d971ff67d7bd4154cffe6947d30234a5983bead2ba8228b7535630d5e。[独立收据](../optimization/benchmarks/native-input-gameenv-20260913-b/verification.json)核验 1059 个文件，SHA256 为 7f8e11207dbaf323d18f39c06ff2f11b3b2cf1e54e4a1adf69ee81dcf1b4ec51，覆盖本轮源码、实际核心、日志和失败阶段 A。

[阶段 A](../optimization/benchmarks/native-input-gameenv-20260913-a/evidence/release-compile.log)实际因测试入口 main() 与项目 main(int, char**) 的 C 链接声明冲突而编译失败，退出 1。B 只修正测试入口签名，未改变输入实现、测试断言或执行时限；失败源码和日志均保留。

本轮使用合成的 SDL 采样数据和真实 GameEnv，不包含套接字、物理设备或输入到画面的延迟。共享输入缓冲和输入历史仍位于独立目录，三个产品主循环尚未接入，因此不提升整个输入任务状态。下一环节通过真实 TCP／UDP 客户端验证发送帧、短按保留、多槽位和断线，再接入实际窗口程序。
