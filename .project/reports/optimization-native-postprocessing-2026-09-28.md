# PBR 后处理实现与实测

归属 ms-24.1 → plan-24.1.1 → task-24.1.1.2。此前 PBR 路径仅把 HDR 累积纹理送入色调映射，Bloom 槽绑定空纹理，FXAA 着色器未运行。本次实现按需创建半分辨率 RGBA16F Bloom 双缓冲和 RGBA8 色调映射缓冲。开启时先在 HDR 空间提取亮部、横纵模糊，再以真实 Bloom 纹理进行色调映射，最后将输出纹理送入 FXAA；关闭时维持原有直通色调映射路径。曝光可通过 `GFOOTBALL_PBR_EXPOSURE` 在 0.1–8.0 内设置，Bloom 与 FXAA 分别由 `GFOOTBALL_PBR_BLOOM=1`、`GFOOTBALL_PBR_FXAA=1` 启用。视图删除时显式释放新增纹理与 FBO。

第一轮 `native-postprocess-validation-20260928-a` 全新 Release 构建通过，关闭效果与此前正式 PBR 的五帧 RGB/状态完全相同；效果开启的捕获发现 Bloom/Blur/FXAA 全屏顶点着色器缺少渲染器会设置的矩阵 uniform，Bloom 阈值在场景中响应很弱。失败诊断保留在该阶段的日志及 `review.json`。随后补齐矩阵接口、将亮部阈值设为 0.5，并在新阶段继续验证，没有改写前一次结果。

修正后正式 `pbr_pipeline` 在 `pbr-pipeline-1790572658206411519` 重新完成全新 Release/完整 Debug ASan/UBSan 构建和 22 个真实 GameEnv 软件 EGL 案例，共 3,828 断言、跳过 0 项。独立终态核验 318 份固定输入、829 份源码哈希及 34 份日志；质量系统当前将该单项判为 `verified`。

`native-postprocess-effects-validation-20260928-a` 使用这组冻结构建串行执行两种配置各七例：关闭、Bloom、FXAA、组合、高/低曝光和组合探针。14 例合计 2,436 项真实 GameEnv 断言通过、跳过 0 项，完整 RGB/模拟状态在 Release/Debug 间逐字节一致。关闭效果与正式 PBR 基线逐字节相同；Bloom 的五帧像素差分别为 0、0、582、1,484、2,081，符合该场景后段才出现高于阈值的亮部；FXAA 五帧均改变 15,952–19,122 像素；高/低曝光各帧改变约 58,000 像素，亮度均值按低→默认→高递增。所有效果对照的模拟状态不变。

GL 绑定探针在两种配置各记录 15 轮真实提取→横向模糊→纵向模糊→色调映射→FXAA：HDR 输入 321×181，Bloom 目标 160×90，色调映射输入包含真实 Bloom/深度纹理，FXAA 读取 321×181 的色调映射纹理。生命周期探针记录三张新增纹理和三个 FBO 在视图删除前均存活、删除后均不可用。独立终态核验 186 份固定输入和 18 份命令日志；进程已结束。另在 `native-postprocess-legacy-validation-20260928-a` 验证两种构建的 Legacy 路径各 174 断言：即使开启新开关，五帧 RGB/状态仍与原 Legacy 基线逐字节一致。

**当前边界：** 自动曝光着色器尚未接入运行路径；`postprocessing` 尚无正式可复跑质量门禁，仍为 `ready:false`。软件 EGL 捕获不证明实际窗口画质或 1080p 硬件 p95≤16.67ms；`render_regression`、ms-23.1 等依赖也未通过。八个优化里程碑继续为 `stale`，本增量不构成产品验收。
