# 正式 PBR/IBL 管线质量门禁

归属 ms-12.3、ms-24.1 → plan-24.1.1 → task-24.1.1.1。正式源码已经采纳渲染实现，本阶段把隔离验证的四个 C++ 探针固定到 `.project/checks/native_pbr_pipeline/`，并新增 `.project/checks/pbr_pipeline.py`。质量配置把 `pbr_pipeline` 设为可运行，断言下限为 3,828。

门禁在独立阶段 `pbr-pipeline-1790570687602806018` 内对正式引擎各做一次全新 Release 和完整 Debug 构建；Debug 检查保留 `-g`、ASan/UBSan、禁止恢复和帧指针。两配置各执行 11 个真实 GameEnv 软件 EGL 案例：Legacy/PBR 基线、资源读回、采样器绑定、五组受控材质、两组同上下文资源重建。22 个案例合计 3,828 项断言全部通过、跳过 0 项。门禁还比较两配置每例完整 RGB 和模拟状态，并检查 PBR 开关、IBL 浮点纹理数值与 4/5/6 号采样槽、M/R/AO G-buffer、同纹理异材质、纹理析构、变光重建与旧纹理释放。

质量执行记录位于 `.project/optimization/evidence/pbr_pipeline.json`，当前源码指纹为 `3c4923d46166a04d2eca2c31610d7fad5efcc7bbd91cb5bcb731d6c8a8cc94ee`，状态为 `verified`。独立终态核验重新计算 318 份固定输入、829 份源码哈希和 34 份命令日志，核对进程已终止、父命名空间未变、阶段退出 0，并写入 `native-pbr-pipeline-progress-20260928-a/terminal-verification.json`。完整执行产物保留在本地忽略的 benchmark 阶段；版本库保留可复跑脚本、探针、质量配置和简短质量证据。

**验收边界：** 当前门禁证明软件 EGL 路径下的正式 PBR/IBL 管线行为；程序化环境仍需外部 HDR 资产或明确产品决策。实际窗口及 1080p 硬件帧时间、完整后处理、`render_regression`，以及 ms-23.1 等依赖尚未通过。软件路径结果不能替代整个产品验收；八个优化里程碑仍由质量工具判为 `stale`。
