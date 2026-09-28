2026-09-28 实测更新：PBR 绑定探针 B 在 Release/完整 Debug 各取得 90 次实际调用快照，证实旧 PBR/IBL 矩阵全零、IBL 立方体未绑定及采样槽错配。独立直接光照候选已通过两种配置的 legacy/PBR 共 4 案例、696 断言：球场恢复可见，legacy 完整 RGB 不变，状态与捕获/恢复语义不变。5010 份输入、12 份日志核验一致；剩余 7 项 uniform 错误均在 IBL。候选仅在隔离阶段，材质响应、IBL、生命周期、性能和完整产品门禁仍未通过。详见 optimization-native-pbr-direct-2026-09-28.md。

# plan-24.1.1 — 渲染管线

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-24.1.1.1、task-24.1.1.2

验收检查：pbr_pipeline、postprocessing

执行：`python3 .project/quality.py run plan-24.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。


2026-09-13 硬件渲染调查：实际 Intel Arc／D3D12 已完成 1080p 引擎帧和状态／图像对照，但重复初始化暴露可独立复现的 Mesa slab 自身死锁。隔离源码修复正在构建验证；成功样本 p95 仍为 18.948–24.990ms，不能提升产品质量状态。见[硬件渲染与驱动定位](../reports/optimization-native-hardware-rendering-2026-09-13.md)。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。
