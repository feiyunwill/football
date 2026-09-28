# 优化阶段当前检查点（2026-09-28）

目标 ACTIVE。本轮 PROGRESS：新增可复跑的固定 OpenGL 图像门禁 `render_images`，版本化 30 帧 RGB/状态哈希与两张审阅样例，覆盖 Legacy、PBR、Bloom、FXAA、自动曝光及组合模式。全新 Release/完整 Debug ASan/UBSan 的 12 个真实 GameEnv 软件 EGL 案例共 2,088 断言通过、跳过 0 项；两构建的图像和状态逐字节一致。独立终态复核 160 输入、827 源码、16 命令日志，质量状态 `verified`。报告：[固定图像门禁](../reports/optimization-native-render-images-2026-09-28.md)。

先前的正式 `pbr_pipeline` 与 `postprocessing` 检查保持 `verified`；本轮没有修改引擎渲染源码。`render_images` 基线限定 llvmpipe LLVM 22.1.8 和 321×181 捕获。实际窗口、1080p 硬件 p95≤16.67ms、`render_regression`、外部 HDR 产品资源、依赖 ms-23.1，以及网络/状态/输入、AI、发布门禁仍待验收。八个优化里程碑保持 `stale`，不能标为完成。

约束继续有效：构建、测试和测量串行；执行阶段输入冻结，修正另建阶段；不放宽原窗口、退出、状态、回放与 RSS 阈值；不安装依赖、不重置服务/WSL、不更改主机挂载。后续推进实际硬件渲染性能与其他产品门禁。
