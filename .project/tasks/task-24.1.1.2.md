# task-24.1.1.2 — HDR 与后处理

2026-09-28 后处理实现增量：PBR 路径加入按需分配的半分辨率 HDR Bloom 亮部提取与横/纵模糊、色调映射曝光控制及 FXAA 末级采样；环境开关为 `GFOOTBALL_PBR_BLOOM=1`、`GFOOTBALL_PBR_FXAA=1`，曝光 `GFOOTBALL_PBR_EXPOSURE` 限 0.1–8.0。资源在视图删除时释放。关闭效果与前一正式 PBR 基线五帧 RGB/状态逐字节一致；重新运行正式 `pbr_pipeline`，22 例 3,828 断言通过。新效果的 Release/完整 Debug 各 7 例、合计 2,436 断言通过，14 例跨配置 RGB/状态逐字节一致；两种配置各观测 15 轮实际提取→横/纵模糊→色调映射→FXAA，纹理/FBO 在视图删除后均不存活。另两例 Legacy 开关隔离对照共 348 断言通过。当前 `postprocessing` 仍未就绪：自动曝光未接入，完整正式门禁与硬件帧预算未通过；里程碑仍为 `stale`。参见 [后处理实现与实测](../reports/optimization-native-postprocessing-2026-09-28.md)。


类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 曝光、Bloom、抗锯齿等启用效果有真实纹理输入、正确顺序与可关闭对照

依赖：task-24.1.1.1

执行顺序：无

验收检查：postprocessing

执行：`python3 .project/quality.py run task-24.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
