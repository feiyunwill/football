2026-09-24 完整阶段结果：native-control-fragment-adoption-20260924-a 已全部通过 quality_selftest、tactical_integration、input_contract、framework_regression、ai_decisions、native_boundary；日志及私有 X11 回收已核对。输入为 42 项结果、3098318 个断言、两种构建各 1031 帧独立回放，战术为 32 项结果、163494 个断言及 24 次回放。之后自动端口采纳改变源码，新版相关门禁另行执行；此记录只覆盖分片采纳的 1135 项清单。

# 框架验收计数修复与完整重验

对应 ms-19.1 → plan-19.1.2 → task-19.1.2.2。本次为进展，不代表全部优化里程碑完成。

正式输入连续性修复增加了四个 RTT 用例，框架要求从 767 增至 771。验收器自测仍将完整报告的结果与旧值 767 比较，导致两项自测失败。保留原 8 项验收输入测试；预期总数改为 560 个基础用例加必测套件数量之和。缺失套件、重复名称、失败、错误及跳过的拒绝检查均保留，正式框架最低数量仍为 771，RTT 必测数量仍为 12。

执行记录：

- native-framework-checker-count-20260924-a：原失败复现成功；驱动错误地对尚未配置 sources 的 planned 门禁计算指纹，退出，未修改正式文件。
- native-framework-checker-count-20260924-b：采纳计数修复后发现受影响指纹包括 quality_selftest 和 framework_regression。驱动原先只预期后者，因此退出。正式测试文件已修改，未回滚。
- native-framework-checker-count-20260924-c：验证两个受影响门禁，重建旧文件指纹时未改写工作区。完整 21 项专项自测、正式 quality_selftest、正式 framework_regression 均通过。

完整框架验收包含 771 项 C++、783 项 Python 及 305 个子测试，结构化报告 2171 个断言；检查 172 个 Debug 编译单元，两组 seed=42/43、各 1000 帧、各两次独立进程确定性与快照回放。私有 X11 已回收。日志及 CTest XML 已独立校验；输入文件哈希保持一致。

正式日志：.project/optimization/evidence/framework_regression-1790217249375197698.log，SHA-256 3f7a30356d51faf1085e80da8f5febd093be9c0b908187cb25d5522ec960d217。
完整证据：.project/optimization/benchmarks/native-framework-checker-count-20260924-c/verification.json。

本次修改 .project/tests/acceptance_inputs_test.py，不改变运行时 1135 项源码清单。后续战术夹具采纳会改变检查器源码，已另排完整重验，不能把此处通过套用于后续源码。
