# NT-2.1 — 版本化训练快照格式

完成日期：2026-10-14。范围：格式定义、C++ 编解码器、独立容量/损坏合约。

格式与环境接入义务见 [SNAPSHOT.md](../SNAPSHOT.md)。包含内核快照、
每 agent checkpoint、终止历史、帧历史、训练选项、cadence、场景和构建身份。
帧历史使用规范顺序消除 ring cursor 的实现依赖。

验收入口：`validate_snapshot_format.py --build-root <isolated-dir> --output <new-dir>`。
当前证据：[report.json](../evidence/nt-2.1-format-20261014-a/report.json)。
Release 独立合约及 ASan/UBSan 通过；测试无 Python/engine 链接；源码指纹前后一致。

源码核对 GameEnv get/set state、FSTA envelope、ScenarioConfig/FormationEntry、
Match ProcessState。图 coverage 对 match.cpp 报告 1397 行 partial，该段为
MatchStepFn 类型定义，已直接读取；相关快照函数使用精确源码，不依赖泛化调用边。

本任务不接入 NativeTrainingEnv，也不宣称恢复功能已经可用。
NT-2.2 必须实现并验证身份生成/比较、完整训练状态所有权、内核与训练层的
事务性恢复及正常终态行为；这些仍是独立任务，不能沿用格式测试代替运行回放。
