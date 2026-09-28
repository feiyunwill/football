# 优化阶段当前检查点（2026-09-28）

目标 ACTIVE。本轮 PROGRESS：复核重启后证据，完成 PBR 运行时接口定位，并实现、执行第一部分直接光照修复。正式源码尚未采纳候选，整体产品验收未通过。

当前无运行中的构建/测试。当前 boot_id 为 84391ef3-d980-4c61-b3a5-bc151aac1fed；9 月 25 日阶段的旧 boot_id 为 83c934ba-d634-4fa5-b636-b52276e0095b，不能按旧 PID 判断活跃进程。

- native-pbr-binding-probe-20260925-b：退出 0，原 owner 113127/549958，exec 63961 已终态；Release/完整 Debug 各 90 个实际调用快照，观测前后 RGB 与状态未变。4254 输入、8 日志重启后全部匹配。A 阶段因清理脚本变量覆盖失败，原证据保留在 native-pbr-binding-progress-20260925-a/stage-a-terminal-limitation.json，不回写 A。
- native-pbr-direct-validation-20260928-a：退出 0，owner 27245/56762，exec 55252 已关闭。四个实际 EGL 案例共 696 断言；legacy 像素逐字节不变，PBR 球场恢复可见，所有状态与捕获/恢复语义保持。5010 输入、12 日志及正式 1138 源码匹配；Release/完整 Debug 的新 PBR 5 帧 RGB 和状态也完全一致。
- RG16F 阶段 native-modifier-rg-validation-20260925-a 与捕获矩阵 native-modifier-capture-validation-20260925-a 均已退出 0；各自终态核验位于对应 progress 目录。RG16F 两种配置各 40 帧/1650 断言，尚无性能收益结论。
- native-pbr-visibility-validation-20260925-a 退出 1，原基线及 RG16F 候选的 4 个 PBR 组合黑场缺陷保留，不能用新候选结果覆盖旧失败。

最新候选基于 RG16F 已验证源码，在独立工作区修改 opengl_renderer3d.cpp、pbr.vert/frag、tonemapping.vert，新增 pbr_geometry.vert/frag。它将真实材质 M/R/AO 写入 G-buffer；同纹理但不同材质参数会结束前一个绘制批次；直接光照从深度重建世界位置并读取正确纹理槽；输出线性 HDR，每帧先清零累积缓冲；色调映射与全屏接口对齐。只重新编译发生变化的渲染器翻译单元并重新生成静态库/链接核心，复用对象对应的头文件与源文件保持哈希一致，完整 Debug 标志未放宽。

运行结果：PBR 中央 9417 像素区域由第 80/120/160 帧全黑，变为五帧分别 9413/9404/9413/9378/9355 个非黑像素；已目视确认球场、球员和 HUD。原 18 项 uniform 错误减少至 7 项，全部属于尚未修复的 ibl_composition。这只证明直接光照集成与捕获语义，不证明完整 PBR 或材质响应正确。

后续工作归入 ms-24.1 → plan-24.1.1 → task-24.1.1.1，依赖 ms-23.1 仍未通过，不提升完成状态。下一步需在新阶段验证受控材质变化、同纹理异材质批次、实际 G-buffer 数值与光照响应；接通真正的 IBL 环境图、漫反射辐照、镜面预滤波与 BRDF LUT，验证创建/绑定/重建/释放；消除剩余接口错误后，重跑实际画面、完整 Debug/Release、资源和原产品门槛。不能用固定背景色、legacy 回退或删除日志代替这些要求。

RG16F 整帧测量工具仍在 native-modifier-timing-preparation-20260925-a，未编译执行：真实 11v11、1280×720、300 预热和 1000 完整周期。软件渲染性能、实际窗口、网络暂停/恢复、输入保留窗口、原 RSS 与缺失基准、硬件渲染复核、AI 训练和发布门禁均仍有未完成项。

约束继续有效：所有构建/测试/测量串行；执行阶段输入冻结，修改必须使用新阶段；保留完整 Debug 的 -g、ASan/UBSan、禁止恢复、帧指针与泄漏检测；不得放宽原窗口、退出、状态、回放与 RSS 阈值；不安装依赖、不重置服务/WSL、不更改主机挂载。MCP 图谱现已可访问；benchmarks 仍不在图谱索引中，候选源码及部分着色器需直接核对。

参考：optimization-native-pbr-direct-2026-09-28.md、optimization-native-pbr-visibility-2026-09-25.md、optimization-native-modifier-rg-2026-09-25.md。此前 SESSION 全文已先归档在 native-pbr-direct-progress-20260928-a 的 documents-before-* 目录，旧阶段失败和限制继续有效。
