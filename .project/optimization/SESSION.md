# 优化阶段当前检查点（2026-09-28）

目标 ACTIVE。本轮 PROGRESS：隔离 PBR/IBL 候选已经过真实 EGL 的资源生成/绑定/释放、受控 M/R/AO 与同纹理异材质响应，以及同一上下文中的 IBL 变光重建验证。正式源码未采纳，产品验收仍未通过。报告：[资源](../reports/optimization-native-ibl-resources-2026-09-28.md)、[材质](../reports/optimization-native-pbr-material-2026-09-28.md)、[重建](../reports/optimization-native-ibl-rebuild-2026-09-28.md)。

最新 `native-ibl-rebuild-validation-20260928-a` 已终态退出 0：Release/完整 Debug 各两例真实 GameEnv 捕获，共 696 断言。恒定光重复使用纹理；只改变 IBL 预处理方向光后，第 4 次生成销毁旧三张纹理并重新生成，辐照度值变化，后续四帧各约 57,370–57,726 像素变化。两构建五帧完整 RGB/状态逐字节一致，捕获语义不变。终态核验 6,480 输入、6 日志、1,138 正式源码、父命名空间和进程状态，见 `native-ibl-rebuild-progress-20260928-a/terminal-verification.json`。OpenGL 复用了数字纹理 ID，重建结论依据销毁前后存在状态及纹理内容变化，不依据 ID 变化。

`native-pbr-material-validation-20260928-a/b` 的驱动环境变量和 Debug 探针链接失败均保留，`-c` 已终态退出 0：两配置各五组、共 1,740 项真实场景断言，材质 G-buffer 的 M/R/AO 单项响应及同纹理异材质批次已实测。此前 IBL 资源首次 Debug ASan 探针加载顺序失败与成功延续阶段也均保留；对应两配置四个 legacy/PBR 捕获共 696 断言，资源读回、采样器绑定及析构删除通过。最早 IBL 接口和直接光照阶段的报告继续保留。当前没有运行中的构建或测试。

ms-12.3 与 ms-24.1 → plan-24.1.1 → task-24.1.1.1 尚需外部 HDR 环境贴图、实际场景变光端到端、实际窗口与硬件整帧 p95，以及原网络/状态/输入、AI 和发布门禁。依赖 ms-23.1 尚未通过；八个优化里程碑继续按 `python3 .project/quality.py status` 判定，不得把隔离结果标为完成。

约束继续有效：构建、测试和测量串行；执行阶段输入冻结，修正另建阶段；完整 Debug 保留 `-g`、ASan/UBSan、禁止恢复、帧指针和泄漏检测；不放宽原窗口、退出、状态、回放与 RSS 阈值；不安装依赖、不重置服务/WSL、不更改主机挂载。所有候选和探针位于忽略的 benchmark 工作区；正式源码及原产品门禁尚未调整。
