# task-24.1.1.1 — PBR 与资源生命周期

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 环境开关正确；有效材质与 IBL 数据；着色器链接/FBO 完整；资源可重建

依赖：ms-23.1

执行顺序：无

验收检查：pbr_pipeline

执行：`python3 .project/quality.py run task-24.1.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-13 待执行审查项：[原生展示入口审查](../reports/optimization-native-presentation-review-2026-09-13.md)记录三个旧主循环的插值覆盖、重复窗口交换、本地插值时基及文字/surface 异常所有权。当前为源码发现，实际程序复现与修复验收尚未执行；容量正式链运行期间未修改这些源文件。


2026-09-13 硬件渲染调查：实际 Intel Arc／D3D12 已完成 1080p 引擎帧和状态／图像对照，但重复初始化暴露可独立复现的 Mesa slab 自身死锁。隔离源码修复正在构建验证；成功样本 p95 仍为 18.948–24.990ms，不能提升产品质量状态。见[硬件渲染与驱动定位](../reports/optimization-native-hardware-rendering-2026-09-13.md)。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。
