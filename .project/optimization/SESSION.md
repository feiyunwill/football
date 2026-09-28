# 优化阶段当前检查点（2026-09-28）

目标 ACTIVE。本轮 PROGRESS：已把隔离验证过的 PBR/IBL 渲染实现精确采纳到正式源码，范围为 4 个渲染器文件和 15 个着色器文件。正式工程的 Release/完整 Debug 全新构建及 Legacy/PBR 四例真实 EGL 捕获共 696 项断言通过，五帧完整 RGB/状态与隔离候选逐字节一致，两构建间也一致。随后在独立构建目录编译并运行原仓库六个运行时、姿态和帧捕获契约，共 25,285 项断言通过。报告：[正式源码采纳](../reports/optimization-native-pbr-ibl-canonical-2026-09-28.md)。

`native-pbr-ibl-canonical-validation-20260928-a` 与 `native-pbr-ibl-contracts-validation-20260928-a` 均终态退出 0。独立核验分别覆盖 6,730/6,788 固定输入、977 正式引擎文件、8/8 命令日志及父命名空间；进程已结束。证据分别在 `native-pbr-ibl-canonical-progress-20260928-a/terminal-verification.json` 和 `native-pbr-ibl-contracts-progress-20260928-a/terminal-verification.json`。所有构建/测试串行，完整 Debug 保留 `-g`、ASan/UBSan、禁止恢复、帧指针与泄漏检测。当前没有运行中的构建或测试。

先前隔离阶段的 IBL 资源数值/绑定/析构、受控 M/R/AO 与同纹理异材质、同上下文变光重建均保留原始证据；其探针加载/链接失败也原样保留，不以成功阶段改写历史。正式代码采用的候选和这些验证阶段的引擎文件哈希逐文件一致；没有采纳候选工作区中的网络或构建文件。

ms-12.3 与 ms-24.1 → plan-24.1.1 → task-24.1.1.1 仍需可重复执行的正式 `pbr_pipeline` 门禁、外部 HDR 环境贴图或其产品决策、完整后处理、实际窗口及 1080p 硬件 p95，以及原网络/状态/输入、AI 和发布门禁。质量配置中的 `pbr_pipeline`、`postprocessing`、`render_regression` 尚标为未就绪，八个优化里程碑不得标为完成。依赖 ms-23.1 仍未通过。

约束继续有效：构建、测试和测量串行；执行阶段输入冻结，修正另建阶段；不放宽原窗口、退出、状态、回放与 RSS 阈值；不安装依赖、不重置服务/WSL、不更改主机挂载。后续应将隔离阶段的 PBR 资源/材质/重建探针整理成正式可复跑的验收脚本，再推进产品级门禁。
