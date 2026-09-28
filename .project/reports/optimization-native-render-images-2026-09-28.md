# 固定 OpenGL 图像回归门禁

归属 ms-24.1 → plan-24.1.2 → task-24.1.2.1。新增可复跑的 `render_images` 检查，将上一轮正式 `postprocessing-1790575700200788263` 的已验证 Release 捕获冻结为版本化 RGB/状态 SHA-256 基线。参考提交为 `95f2c910e565b353b902a64037b1e1aff5d7c85d`；参考环境为 `llvmpipe (LLVM 22.1.8, 256 bits)`，321×181 RGB，模拟帧 0、40、80、120、160。六组开关为 Legacy、PBR 默认、Bloom、FXAA、自动曝光和自动曝光+Bloom+FXAA。两个第 160 帧图像样例：[PBR 默认](assets/render-images-baseline-frame160.png)、[自动曝光组合](assets/render-images-auto_combined-frame160.png)。

门禁对正式引擎各做一次全新 Release 与完整 Debug ASan/UBSan 构建，再运行两种配置各六个真实 GameEnv 软件 EGL 案例。原有捕获契约逐帧比较缓存 RGB 与独立 OpenGL 后缓冲读回，检查重复捕获、状态恢复、奇数宽度 RGB 打包、空帧拒绝以及同状态重复呈现。新增图像层逐帧对比固定 RGB/状态哈希、GL renderer 身份、尺寸、非黑像素、颜色种类、平均亮度与绿色球场色彩，并检查画面中央和边界梯度、四边非黑覆盖。FXAA 的强边缘数须下降，自动曝光须提高场景亮度；Legacy/PBR、Bloom、FXAA、自动曝光各开关必须产生相应的像素变化。所有帧还须在 Release 与 Debug 间逐字节一致。

正式阶段 `render-images-1790578124956734397` 退出 0，共 12 例、2,088 项实际 GameEnv 断言，跳过 0 项；质量系统将 `render_images` 判为 `verified`。六种模式的 30 帧在两构建中均匹配固定哈希。非黑像素范围 57,951–58,098，独立颜色 2,263–7,333，中央强边缘 305–928，边界强边缘 458–1,057；四边非黑覆盖均超过 95%。与 PBR 默认相比，FXAA 每帧改变 15,952–19,122 像素，自动曝光每帧改变 57,887–57,960 像素；Bloom 在后段亮帧出现最多 2,081 个像素变化。独立终态复核 160 份固定输入、827 份源码哈希、16 份命令日志、质量日志哈希、60 组跨构建 RGB/状态对照与 60 份固定图像哈希，确认进程结束且父命名空间未变。

此基线针对指定 llvmpipe 环境；更新驱动或有意改变画质时，需要人工审阅新图像再更新基线。它验证软件 OpenGL 捕获，不证明实际窗口、硬件 GPU 的 1080p 画质或帧时间。`render_regression` 仍为 `ready:false`，1080p p95≤16.67ms 未验收；ms-23.1 依赖及其他产品门禁仍未通过，八个优化里程碑保持 `stale`。
