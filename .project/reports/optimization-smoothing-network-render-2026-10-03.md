# 手感、网络复验与 1080p 渲染瓶颈

归属 ms-22.1、ms-23.1、ms-24.1；当前源码，2026-10-03。正式 `quality.py verify ms-22.1` 与 `quality.py verify ms-23.1` 均通过。手感和网络的任务状态由质量系统判定；渲染性能任务 `task-24.1.2.2` 仍未通过。

`presentation_smoothing` 通过 543 条断言、零跳过，覆盖真实 GameEnv 回滚、重定向、附件中间姿态、暂停画面及当前产品窗口输入；报告确认实际像素和 GameEnv 均执行。已有当前源码 `feel_regression` 通过 449 条断言：15 个独立本地窗口、每窗口 4 次 XTEST 按键，60 次按键全部采纳并产生球员速度响应；速度响应 p95 为 40.194ms，可见响应 p95 为 44.212ms，目标均为 50ms。仍有 3 次单独超预算事件，归因为命令采样滞后、呈现延迟和触球待处理各一次，后续发布验收须继续观察长尾。

网络 `network_input_window`、`network_reconnect`、`network_regression` 已有当前源码通过回执，分别为 552,114、163、242 条断言；本轮刷新 `native_session_ports`，通过 1,947 条断言、零跳过，含 6 对 Release/Debug 服务与 12 个实际 loopback 客户端会话。端口门禁的范围是自动分配和真实本机客户端，菜单及恢复由其他门禁覆盖，不能仅凭端口结果推论全部网络行为。

正式 `render_regression` 在 1920×1080、PBR+Bloom+FXAA+自动曝光、每种子预热 30 帧并测 120 帧的条件下连续两次失败。未选择私有驱动时实际落到 llvmpipe，种子 42/43 的 p95 为 258.225/220.760ms。显式选择私有修复版 D3D12 驱动后，实际 renderer 为 Intel Arc 140T，实际加载 Gallium 库的 SHA-256 为 `46e392bcd6aafc9abeeb1aed1874fa47cb60e1b30665d5da818c14fc5e35f998`，两种子的 p95 为 32.619/31.921ms，仍超出 16.67ms 预算；`product_acceptance=false`。私有驱动还没有作为产品依赖打包。硬件复现命令：`FOOTBALL_RENDER_GPU_DRIVER_ROOT=/root/.cache/football-mesa-build-20260913-a/install-candidate python3 .project/quality.py run task-24.1.2.2`。

独立诊断副本保留同一 PBR 画质，在种子 42 拆分计时：实际 `GameEnv.render()` 的 p95 约 25.688ms，外层上下文进入约 0.115ms，`glFinish()` 约 0.021ms。进一步在副本中直接调用场景准备和图形任务，场景准备 p95 约 1.998ms、图形任务约 31.140ms；将该副本唯一的 `Render(true)` 改为 `Render(false)` 后，图形任务约 0.672ms，`glFinish()` 约 9.305ms。对照支持交换/呈现路径包含主要等待，但运行间负载会波动，不能直接把 p95 差值当成精确成本；跳过交换也不满足产品窗口验收。下一步需在相同实际窗口内分离 GPU 工作完成与交换/合成等待，再针对确证瓶颈优化并重跑正式双种子门禁。

交换入口的动态探针补充了同一设备的 120 个测量帧：正常路径中 `SDL_GL_SwapWindow` p95 为 22.902ms、交换间隔为 0；在交换前显式 `glFinish()` 后，预等待 p95 为 15.069ms，交换调用仍为 11.744ms。探针有计时开销且两次运行并非完全相同负载，因此只说明 GPU 工作与窗口呈现均有显著等待。请求 `SDL_VIDEO_X11_FORCE_EGL=1` 的独立双种子对照仍加载同一 D3D12 驱动，p95 为 33.990/32.908ms，未显示可采用的收益；测试收到 X server DRI3 警告，不将其归因于引擎实现。

[归档](../optimization/evidence/stage_22_24_20261003.tar.gz)保存 64 份平滑、网络、渲染和隔离诊断的报告、原始图像、源码副本与命令日志；[清单](../optimization/evidence/stage_22_24_20261003_manifest.json)列出各文件字节数及 SHA-256。归档 SHA-256 为 `4d8e118fed9bb161e92748929058c9abf3e77b576b64178fcdb735c7b4879296`。手感原始大归档留在本地忽略目录，SHA-256 为 `3e12eb13a1244899b1e7114d249bf44ff3b3d6bf7ddb6f38780ee49211d228a6`；本次归档保存其摘要报告。正式回执与本次执行日志另列于证据目录。渲染失败和驱动打包缺口未关闭，ms-24.1 与整个产品优化目标保持未完成。
