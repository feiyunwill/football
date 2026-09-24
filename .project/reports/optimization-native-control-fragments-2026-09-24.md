2026-09-24 完整阶段结果：native-control-fragment-adoption-20260924-a 已全部通过 quality_selftest、tactical_integration、input_contract、framework_regression、ai_decisions、native_boundary；日志及私有 X11 回收已核对。输入为 42 项结果、3098318 个断言、两种构建各 1031 帧独立回放，战术为 32 项结果、163494 个断言及 24 次回放。之后自动端口采纳改变源码，新版相关门禁另行执行；此记录只覆盖分片采纳的 1135 项清单。

# 战术通知分片夹具修复

对应 ms-25.1 → plan-25.1.1 → task-25.1.1.1。修复已采纳，完整正式战术门禁通过；关联输入和框架等门禁仍在串行重验。

原正式失败来自 native-input-contiguous-adoption-20260924-a：Sanitizer 有效分片场景在 buffered=12 时拒绝 type=10。夹具将 14 字节接管/交还通知按 3、7、4 字节拆分，间隔 75ms，同时立即回应客户端的 9 字节心跳。若心跳位于第一段之后，通知的 frame 字段便含入心跳字节，正确的生产解析器会拒绝。该次失败没有逐包线缆记录；上述原因由实际错误日志、发送路径与独立字节反例共同支持，不能声称观察到了该次完整原始流。

夹具现在显式标记分片发送期间，将完整心跳回复暂存到最多 16 条的有界队列，发送完通知后再回复。网络分片、重传及顺序检查保留；原 40 秒 bootstrap、15 秒控制响应预算、非法槽位和非法帧拒绝要求不变。

native-control-fragment-order-20260924-a：
- 原 5 项夹具自测全部保留，新增确定性的心跳交错反例，共 6 项通过。
- Release 和完整 Debug ASan/UBSan 各 5 轮；每轮测试有效分片、非法槽位、非法帧，共 30 个真实客户端场景全部通过。
- 实测最长 bootstrap 3435.8ms，最长控制阶段 528.4ms；不是放宽期限后的通过。
- 11 条命令的输出日志和输入文件哈希已独立校验，verification.json 保存结果。

native-control-fragment-adoption-20260924-a 在前置串行队列结束后采纳四个检查器文件：
native_product_udp_fixture.py、native_product_udp_fixture_test.py、native_tactical_control_probe.py、ai_tactics_contract.py。正式 helper 测试数量从 19 增至 20，生产客户端未因这个夹具修复而放松协议校验。

新的 1135 项源码清单及四文件哈希分别位于该采纳目录 sources-after.json、adopted-files.json。串行执行 quality_selftest → tactical_integration → input_contract → framework_regression → ai_decisions → native_boundary。运行中的输入冻结；如再失败，保留日志并在新阶段修复。


## 正式战术验收结果

正式 tactical_integration 在当前采纳源码上通过，耗时 264.983 秒：32 项结果、163494 个断言，20 项 helper 自测，8 场真实接管对局、4 场真实原生客户端对局、6 个控制边界场景；两种构建完成 16 次服务记录回放和 8 次客户端记录回放。39 条执行命令日志哈希已逐项核对，源码清单与采纳阶段一致。

正式日志 tactical_integration-1790217556936092851.log，SHA-256 e9f01573c2b30a646d1f6ad729cacb40bb2500e817c8cc31d71c9c7234cdf4ff。独立验证记录在 native-control-fragment-adoption-20260924-a/tactical-verification.json。正式验收器自测亦通过。关联门禁队列继续执行，整个产品仍未完成。
