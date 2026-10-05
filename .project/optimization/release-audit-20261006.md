# 产品发布门禁审计（2026-10-06）

正式质量编排中，框架、架构、性能、手感和网络五个前置里程碑均为 `verified`。AI 的集成、决策、训练可靠性及 24 种子回归检查也分别为 `verified`；产品旅程、隔离安装包和长时稳定性检查均通过。安装包检查构建 `gfootball 2.10.3` 的 Linux x86_64 wheel，在新环境中验证导入、本地比赛及缺失检查点的明确诊断；wheel SHA-256 为 `6db45ba46e5afb007be5f365ca5d420f3cbbd6c3f6de725188df3c6bf4a1bc87`。可回读的[产品旅程报告与日志](evidence/product_journey_formal_20261006/report.json)和[安装包报告与日志](evidence/product_package_formal_20261006/report.json)的报告 SHA-256 分别为 `4619247fde9f6178133dc03d8cf542bee9a579cca822e901ec2a5f35ec2024aa`、`f0d1c4b44b2d6cc08d2728ee5672ee2b4547833888f38454f7c759b43a0e8229`。wheel 本体保留在本地构建目录，发布前需从届时源码重新构建并验收。

`product_release` 正式审计执行 **283 项断言、零跳过**，验证了当前质量记录、日志、报告子文件哈希和已提交的正式长时归档。[审计报告](evidence/product_release_audit_20261006/report.json) SHA-256 为 `cb39ea164ebb6904db6a844ef46bfd484ec58b6262c35c2fad99a1db47532f38`。七条失败记录均指向同一未解决阻塞及其依赖：`render_regression` 的 1080p 完整帧 p95 高于 16.67 ms，导致渲染、AI 和发布里程碑及相关任务失败；已知问题 `render-1080p-p95-20261006` 继续开放。没有因下游检查单独通过而关闭发布门禁。

修复需在目标显示路径上让种子 42、43 的真实窗口交换完整帧 p95 均达预算，并复验图像质量、手感延迟及五个上游里程碑。通过后重新执行渲染、AI 与发布质量编排，并由发布审计确认所有严重问题已关闭、证据和归档完整，再决定是否发布。
