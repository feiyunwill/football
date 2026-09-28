# task-24.1.1.2 — HDR 与后处理

2026-09-28 自动曝光与正式门禁增量：PBR 路径使用两张 1×1 RGBA16F 历史纹理完成 GPU 测光与平滑曝光，并按快照模拟时间更新，保持同一状态重复呈现的像素不变。新 `postprocessing` 门禁在全新 Release/完整 Debug ASan/UBSan 的 26 个实际 GameEnv 案例中通过 4,524 断言、跳过 0 项；跨配置完整 RGB/状态一致。两配置各验证 15 轮组合后处理与 5 次自动曝光更新/15 次色调映射，视图删除后资源释放。独立终态复核 346 输入、829 源码及 36 日志，检查状态 `verified`；`pbr_pipeline` 也针对当前源码重跑 22 例、3,828 断言并保持 `verified`。硬件窗口帧预算、`render_regression`、外部 HDR 与 ms-23.1 仍待验收。参见 [自动曝光与正式门禁](../reports/optimization-native-auto-exposure-2026-09-28.md)。


2026-09-28 后处理实现增量：PBR 路径加入按需分配的半分辨率 HDR Bloom 亮部提取与横/纵模糊、色调映射曝光控制及 FXAA 末级采样；环境开关为 `GFOOTBALL_PBR_BLOOM=1`、`GFOOTBALL_PBR_FXAA=1`，曝光 `GFOOTBALL_PBR_EXPOSURE` 限 0.1–8.0。资源在视图删除时释放。关闭效果与前一正式 PBR 基线五帧 RGB/状态逐字节一致；重新运行正式 `pbr_pipeline`，22 例 3,828 断言通过。新效果的 Release/完整 Debug 各 7 例、合计 2,436 断言通过，14 例跨配置 RGB/状态逐字节一致；两种配置各观测 15 轮实际提取→横/纵模糊→色调映射→FXAA，纹理/FBO 在视图删除后均不存活。另两例 Legacy 开关隔离对照共 348 断言通过。该阶段 `postprocessing` 尚未就绪：自动曝光和完整正式门禁当时未完成，硬件帧预算也未通过；里程碑仍为 `stale`。参见 [后处理实现与实测](../reports/optimization-native-postprocessing-2026-09-28.md)。


类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 曝光、Bloom、抗锯齿等启用效果有真实纹理输入、正确顺序与可关闭对照

依赖：task-24.1.1.1

执行顺序：无

验收检查：postprocessing

执行：`python3 .project/quality.py run task-24.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
