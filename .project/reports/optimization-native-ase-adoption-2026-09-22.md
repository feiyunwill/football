# ASE 修复正式接入与完整框架验收（2026-09-22）

里程碑 21.1 → 计划 21.1.1 → 任务 21.1.1.2。正式源码已接入验证过的 ASE 解析修复，新增永久回归，并通过原完整框架门禁。整个优化阶段仍未完成。

## 正式实现

本轮修改 5 个文件，源码清单由 1088 增为 1089 项：

- base/utils.cpp 采用此前逐资源、模型输出及真实比赛验证过的候选，源码完全一致；保留旧代码及日期说明。
- 新增 engine_ase_parser_contract.cpp，直接调用正式引擎的 10 项语义、边界、游标及嵌套资源回归。
- CMakeLists.txt 与 sources.cmake 登记原生测试目标，产品构建不增加 GTest 依赖。
- framework_regression.py 把这 10 项测试纳入永久门禁，并纳入断言统计；原测试、期限和门槛保持不变。

[接入清单](../optimization/benchmarks/native-ase-parser-adoption-20260922-a/changes-applied.json)和[源码身份](../optimization/benchmarks/native-ase-parser-adoption-20260922-a/sources-after.json)可复核。旧源码与受影响的旧构建产物均已归档；历史证据引用的旧核心应从门禁阶段 archives.json 对应的原件读取，不能把当前 /tmp 核心当作旧版本。

## 完整验证

Release 与 Debug ASan/UBSan 的正式产品重新构建；永久解析测试各 10 项、554 条断言通过，无跳过，保留 Debug 符号及泄漏检查。

原完整框架门禁通过：

- 560 项 C++ 测试。
- 781 项 Python 测试及 305 个子测试，包括真实图形窗口测试。
- 新增正式原生解析测试 10 项、554 条断言。
- 两个种子分别完成两个独立进程的 1000 帧与快照回放验证。
- Debug 配置覆盖 168 个编译单元；门禁结构化断言统计 1898 条。

确定性摘要仍为 606593fad9c78ea9 / a8c11d6b25d70198。正式指纹 c4e8af5a17b6729c67384fea668c07c97c65628273125e2b51d40c41f469e7b0，门禁耗时 590.613 秒。[完整门禁结果](../optimization/benchmarks/native-ase-parser-gates-20260922-a/report.json)、[固定副本与摘要](../optimization/benchmarks/native-ase-adoption-evidence-20260922-a/validated-summary.json)保留原始日志、XML 和源码校验。

## 后续工作

UDP 合并候选 C 已在该门禁通过后自动开始串行编译。将验证 8 个产品入口、20 项实际客户端取消、双构建各 6 项真实 UDP 收尾契约，以及 TCP/UDP 双客户端比赛与独立回放。当前尚无该候选的完整通过结论；[进程观察快照](../optimization/benchmarks/native-ase-adoption-evidence-20260922-a/udp-c-observation.json)仅表示当时状态。

原统计性能门槛、弱网自动恢复、GUI 完整退出时延、50ms p95、目标硬件、训练与其余渲染/AI 验收继续保持未完成。解析 CPU 的此前单次改善不代替这些门禁；框架通过也不等于整个产品通过。
