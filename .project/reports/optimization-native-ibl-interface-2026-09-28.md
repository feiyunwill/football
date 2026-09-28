# IBL 延迟合成接口修正与实际验收边界

归属 ms-12.3 与 ms-24.1 → plan-24.1.1 → task-24.1.1.1。正式源码尚未采纳此隔离候选；IBL 和产品验收均未通过。

上一直接光照候选中，`ibl_composition` 仍以物体表面着色器的矩阵、法线和 UV 接口在全屏四边形上执行。原采样器将环境图映射到 G-buffer 的纹理槽，且将深度纹理当作 BRDF LUT。实际运行曾逐案例报告 7 项 IBL uniform 缺失。

本次在 `native-ibl-interface-validation-20260928-a` 的独立工作区修改 `opengl_renderer3d.cpp`、`ibl_composition.vert` 和 `ibl_composition.frag`：全屏顶点接口匹配 `RenderOverlay2D`，从深度和逆投影视图矩阵重建世界坐标，读取现有 G-buffer 的线性 albedo、世界法线和 metallic/roughness/AO；将四个 G-buffer 采样槽设为 0–3，为辐照度立方体、预滤波立方体与 BRDF LUT 保留 4–6。合成输出保持线性 HDR，由最终色调映射处理显示变换。

在真实 EGL 场景中分别重编译 Release 和完整 Debug 的渲染器翻译单元，重新链接私有核心，并运行 legacy/PBR 共四个捕获案例。每案例 174 项断言，合计 696 项，包含 161 模拟帧、5 份 RGB/状态、捕获开关、重复呈现、恢复、奇数宽度和无窗口策略。四案例均退出 0，uniform 缺失均为 0；相对上一直接光照候选，四案例全部五帧完整 RGB 均逐字节相同，模拟状态也逐字节相同。完整 Debug 保留 `-g`、ASan/UBSan、禁止恢复和帧指针。

终态独立核验：5648 份固定输入、12 份命令日志、1138 份正式源码与父命名空间观察值全部匹配，执行进程已终态。证据位于 `native-ibl-interface-progress-20260928-a/terminal-verification.json`，源码差异位于执行阶段的 `change.diff`。

**限制：** 零 uniform 错误只证明接口和程序加载正确。PBR 完整 RGB 没有变化，不能声称环境光已经生效。候选仍未创建环境立方体、卷积辐照度、GGX 预滤波和 BRDF LUT，也未验证非退化材质响应、资源重建/释放或整帧性能。后续必须实测这些资源和光照输出，再运行原产品门禁；不能以兼容性结果替代 IBL 完成验收。
