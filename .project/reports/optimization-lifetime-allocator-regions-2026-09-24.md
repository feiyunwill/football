# 重启 RSS：分配区与内核映射对照诊断

归属 ms-20.1 → plan-20.1.2 → task-20.1.2.2。状态为串行排队，尚未执行本轮采集；原正式 16MiB RSS 失败仍未关闭。

前一轮 smaps 采集把波动定位到匿名可写映射，但没有证明这些映射由哪个分配器持有。本机 GCC 16 的 sanitizer/asan_interface.h 声明 __asan_print_accumulated_stats；实际 libasan.so.8.0.0 的统计格式包含每个大小类别的 region 地址、mapped、rss、releases、inuse 等字段。

新诊断只修改私有测试副本。在第 3 和第 11 次重启的原 RSS 采样及 smaps 捕获之后输出运行库统计；保持原 12 次重启、cycle3 warm、16MiB 阈值、167 个断言及完整 Debug Sanitizer 配置。计划运行 1 次原测试和 3 次诊断副本。分析器只在 region 起始地址与 mapped 大小同内核映射精确匹配时归属数据页；未匹配部分保留为未知。分配器 inuse 不是活跃用户分配数，不能把其变化直接称为泄漏。

native-lifetime-allocator-regions-20260924-a 因前置端口采纳只写入一个文件、出现未列入计划的源码状态而在预检退出，未执行任何编译或测试。输入保持不可变。新阶段 B 排在 native-automatic-port-adoption-20260924-b 结束后，允许的源码状态已分别固定为预期的部分采纳或完整采纳哈希；检测库、头文件、编译链接配方和候选源均固定。

本诊断无正式源码修改，无清理分配器缓存或调整门限，不替代完整架构验收。保留 architecture_accepted=false 和 product_acceptance=false。独立的失败数值遥测候选仍仅准备，未编译或采纳。

## 2026-09-24 提交时验证快照

自动端口 adoption B 已结束（exit 1）：7 项正式检查中 6 项通过，input_contract 失败。已通过 quality_selftest、native_session_ports、native_boundary、tactical_integration、framework_regression、ai_decisions；7 份正式日志的 SHA-256 已核对。输入失败来自 actual-input-windows 内的 windows 子命令，尚未确定根因；此前版本通过的输入验收不能代替当前版本结果。失败日志：.project/optimization/evidence/input_contract-1790218989295654624.log。

自动端口专项仍为通过：Release/full Debug Sanitizer 下 6 对服务端、12 个真实客户端、1924 项断言。整体产品质量尚未验收通过。

allocator-regions B 已从排队进入 instrumented-0 阶段；提交时仍在运行，结果待后续记录。该诊断不改正式源码；原始架构 RSS 失败仍未关闭。用户已授权本次提交及推送；以下旧条目保留为历史记录，其运行状态以本快照为准。
