# 原生硬件渲染、1080p 实测与驱动死锁定位（2026-09-13）

本轮属于 ms-24.1 → plan-24.1.1／plan-24.1.2 → 渲染管线、图像与帧预算任务。硬件能力已由实际上下文验证，但产品验收仍未通过：重复初始化存在 Mesa D3D12 死锁；成功运行的 1080p p95 仍超过 16.67ms。驱动修复候选正在隔离构建和验证，不能宣称完成或提升质量状态。

## 实际能力与帧耗时

Windows 只读查询为 Intel Arc 140T GPU，驱动 32.0.101.8860。原生 /dev/dxg 存在。默认 EGL 与隐藏 X11 SDL 窗口均加载 llvmpipe；只指定 MESA_LOADER_DRIVER_OVERRIDE=d3d12 也仍是 llvmpipe。子进程中指定 GALLIUM_DRIVER=d3d12 后，EGL 与隐藏 X11 SDL 上下文实际报告 Microsoft Corporation／D3D12 (Intel(R) Arc(TM) 140T GPU (16GB))／OpenGL 4.6 Compatibility Mesa 26.2.2-arch1.1。设备扩展字符串仍包含 EGL_MESA_device_software，不能用这个字符串单独判定实际 GL 是否使用 GPU。

[上下文默认对照](../optimization/benchmarks/native-hardware-context-20260913-a/report.json)、[子进程配置对照](../optimization/benchmarks/native-hardware-context-20260913-b/report.json)、[实际 Windows 查询](../optimization/benchmarks/native-hardware-engine-1080-20260913-a/host-gpu.json)、[实际加载库及 SHA](../optimization/benchmarks/native-hardware-render-audit-20260913-a/hardware-libraries.json)保留全部身份信息。Wayland 试验返回 SDL “wayland not available”；独立添加 WSL 库目录并非 EGL／X11 成功的必要条件。

当前未修改的 Release GameEnv 与原始素材／着色器，在 1920×1080、seed=42、FNAT1 单人场景上运行 161 个逻辑帧（62 个 in-play）。在 0／40／80／120／160 五个状态各渲染 12 次，前四次预热，合计 40 个计时样本。计时覆盖 ContextHolder、完整 env.render、glFinish 和错误检查；它包含当前引擎的同步 RGB 回读，表示 GPU 完成的离屏帧，并非物理显示延迟。

| 完成的运行 | 平均 ms | p95 ms | 最大 ms |
|---|---:|---:|---:|
| 软件渲染 A | 102.835 | 120.198 | 143.976 |
| 硬件 A | 16.648 | 21.050 | 28.405 |
| 硬件诊断 A | 17.870 | 24.990 | 37.901 |
| 硬件重复 B-1 | 15.890 | 18.948 | 23.239 |

[全部计时、身份和范围](../optimization/benchmarks/native-hardware-render-audit-20260913-a/completed-preflights.json)列出原始纳秒样本。p95 取排序数组 floor(0.95×(n−1)) 位置。这里只汇总已完成运行，下面的启动失败也属于本轮结果；这些样本不能替代连续比赛、长时间运行或 50ms 设备响应验收。

## 状态和图像证据

每次渲染前后的完整逻辑状态均相同；五个状态在软件与三个成功硬件进程之间逐字节相同。三个硬件进程输出的五张 RGB 图像也逐字节相同。软件与硬件的图像存在差异：每通道平均绝对差约 0.241–0.310／255，99% 通道差不超过 1–2，局部最大差 45–92。没有为这组数据临时设立或放宽图像验收阈值。

[像素分布与原始图像 SHA](../optimization/benchmarks/native-hardware-pixel-20260913-a/report.json)、[显示方向说明](../optimization/benchmarks/native-hardware-pixel-20260913-a/preview-orientation.json)、[第 160 帧对照](../optimization/benchmarks/native-hardware-pixel-20260913-a/frame-160-upright-pair.png)可复核。预览左侧软件、右侧硬件；仅为显示将 OpenGL 底部起始行反向排列并二倍采样，原始 RGB 比较不变。实际预览中球员和草地整体偏暗，后续曝光／可读性仍需专门验收，不能以两个后端相似代替画质通过。

## 可独立复现的驱动缺陷

第一次 ABBA 的 hardware-b 在 start_game 尚未返回时停住，测试器 300 秒后终止并回收；第二个带阶段标记的重复批次也在第二次初始化超时。GALLIUM_THREAD=0 对照仍卡住，其互斥锁 owner 与当前主线程 TID 相同，排除了“关闭工作线程即可修复”的假设。

真实引擎回溯为 Gui2Caption／Player 创建 → UpdateTexture 或 ResizeTexture → Mesa 纹理上传 → pipebuffer slab 分配。使用与实际库 Build ID 完全相同的官方调试符号，将地址解析到以下链路：

1. pb_slab_manager_create_buffer 在 pb_bufmgr_slab.c:393 获取 mgr->mutex。
2. 分配新 slab，进入 d3d12_bo_new。
3. d3d12_bufmgr.cpp:147 调用 d3d12_screen_reclaim_completed。
4. 回收已完成资源，经 d3d12_bo_unreference、pb_reference 回到 pb_slab_buffer_destroy。
5. pb_bufmgr_slab.c:197 再次获取同一把不可递归互斥锁，形成自身死锁。

[实际引擎回溯](../optimization/benchmarks/native-hardware-engine-init-20260913-b/diagnostics-deep/main-stack.log)、[关闭线程对照](../optimization/benchmarks/native-hardware-engine-init-20260913-c/diagnostics-deep/main-stack.log)、[源码与官方下载记录](../optimization/benchmarks/native-hardware-driver-source-20260913-a/fetch-3.json)、[调试符号身份](../optimization/benchmarks/native-hardware-driver-symbols-20260913-a/download.json)均保留。一次地址换算错误也被保留并明确否决，正确解析使用实际进程 maps 计算 ELF 加载基址，见[解析处置](../optimization/benchmarks/native-hardware-render-audit-20260913-a/symbol-resolution-disposition.json)。

独立程序仅依赖 EGL／SDL，不链接足球引擎。它创建 128 个循环复用纹理，执行 TexImage2D、TexSubImage2D、GenerateMipmap、Flush／Finish；同样在 D3D12 中死锁。[独立复现源码](../optimization/benchmarks/native-hardware-texture-repro-20260913-a/fixture.cpp)、[精确解析后的调用栈](../optimization/benchmarks/native-hardware-texture-repro-20260913-a/resolved-stack.txt)和[软件对照](../optimization/benchmarks/native-software-texture-control-20260913-a/report.json)表明：软件对照完成全部 5,000 次操作且 GL 无错误，D3D12 的失败不依赖比赛、输入采样或网络代码。

## 修复候选与后续验收

[两文件驱动补丁](../optimization/benchmarks/native-mesa-reclaim-patch-20260913-a/mesa-26.2.2-d3d12-reclaim.patch)将已完成资源回收和分配失败后的回收重试移到 init_buffer 中，在进入或退出 create_buffer 之后执行，避免正常路径和内存不足重试路径持有分配器锁时回收。旧代码以日期注释保留。它尚未作为产品依赖采用。

隔离构建使用官方 Mesa 26.2.2 归档，与调试定位时下载的文件逐字节核对；构建工具、DirectX Headers 和缺失的 X11 依赖均位于本项目专用缓存。配置包含 D3D12、EGL、GLX、C++23、Release，ninja -j 1。初次配置缺少 xrandr 的错误保留，补齐私有依赖后继续构建。没有修改系统 Mesa、全局环境、显示服务或原始产品核心。

验证顺序已经落实为[可执行驱动验证程序](../optimization/benchmarks/native-mesa-patch-validation-20260913-b/driver.py)：未修改的同配置构建复现 → 应用源码补丁 → 单线程构建／私有安装 → 三次独立 5,000 次纹理操作 → 六次真实引擎初始化与 1080p 图像／状态核验。必须核对实际加载的私有库，不能仅依据配置变量判定补丁生效。

配置修正记录：第一次私有 D3D12-only 构建完整通过 1,052 步，但[实际设备探测失败](../optimization/benchmarks/native-mesa-patch-validation-20260913-a/report.json)：EGL 返回零设备，程序按契约退出，驱动补丁没有应用。官方源码 egldevice.c 的 HAVE_SWRAST 分支控制软件设备入口枚举；此 WSL 主机没有 DRM 节点，D3D12 正是通过该入口建立实际硬件上下文。因此增加 softpipe 构建选项以保留入口，实际测试仍必须核对 D3D12 身份和私有库路径。[修正后的未修改驱动构建](../optimization/benchmarks/native-mesa-build-original-20260913-c/process.json)正在同一私有构建目录单线程执行，安装到独立 install-original-sw；前一次安装保留。后续修复验证程序已准备，尚未启动。

后续继续连续比赛帧预算、同步回读成本、设备到角色／呈现延迟、画面曝光、完整弱网和 AI／最终稳定性质量链。当前整体目标保持进行中。

## 外部依据

Mesa 的 [D3D12 驱动说明](https://docs.mesa3d.org/drivers/d3d12.html)、[EGL 说明](https://docs.mesa3d.org/egl.html)、[环境变量说明](https://docs.mesa3d.org/envvars.html)和[隔离 Meson 安装说明](https://docs.mesa3d.org/meson.html)用于选择实验方式；硬件身份、成功与失败均以本轮实际执行结果为准。[Microsoft WSL 图形说明](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)支持对 vGPU 路径的调查。
