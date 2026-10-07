# 1080p 渲染呈现瓶颈（2026-10-06）

`render_regression` 仍未通过产品门禁，`ms-24.1` 当前为 `stale`，不能视为完成。该检查在真实窗口交换和 `glFinish` 完成后测量 1920×1080、PBR + Bloom + FXAA + 自动曝光，每个种子热身 30 帧、测量 120 帧，预算为 p95 ≤ 16.67 ms。不能用跳过窗口交换或软件渲染的结果替代产品验收。

着色器候选筛查工具的失败留证已加固：候选 GLSL 编译失败时仍写出最终失败报告与原始归档，已完成的画面预检标为未完成、`image_equal` 为未知；画面全部通过但 GPU 构建缺失时，保留 12 次画面捕获一致的结论，同时标记完整诊断失败且 GPU 运行数为 0。相同脚本版本的正常画面预检完成 12 次捕获；三种路径的报告及归档清单均已校验，见[失败留证审查](evidence/render_shader_ab_failure_preservation_20261006.json)和[原始归档](evidence/render_shader_ab_failure_preservation_20261006.tar.gz)。该工具改进不构成 1080p 产品帧预算通过。

新增[通用着色器候选 A/B 工具](diagnostics/render_shader_ab.py)：先在六种固定画质模式中捕获基线与候选并逐帧核对参考 RGB／模拟状态，再以两个种子交错运行完整 1080p 真实窗口基准；画面不一致时停止性能测量。工具会记录资源清单、二进制／驱动哈希、逐帧样本、日志和可校验原始归档。当前版本的完整试运行完成 12 次画面捕获与 4 次真实窗口测量；故意改变 Bloom 输出的负例在第 6 次捕获发现像素差异，GPU 运行数为 0。它是候选筛查工具，`budget_met` 不等于正式 `render_regression` 验收。[工具与两项候选的审查摘要](evidence/render_shader_experiments_20261006.json)及[原始归档](evidence/render_shader_experiments_20261006.tar.gz)保留了补丁、捕获、原始帧时和哈希。

色调映射的天空像素提前返回候选在五种 PBR 模式、各五帧的固定捕获中逐字节一致，但基线画面没有接近天空填充色的像素，不能证明该路径被覆盖；未进行性能主张或合入。Bloom 暗像素提前返回候选在 `bloom` 与 `auto_combined` 各五帧中逐字节一致；相同正式基准／引擎／D3D12 驱动哈希下，两种子两轮交错真实窗口 A/B 的基线／候选 p95 分别为种子 42 **18.348/23.218、26.266/24.800 ms**，种子 43 **49.564/33.440、32.061/19.660 ms**。跨种子没有稳定收益，四次候选都超过 16.67 ms，未合入；门禁继续失败。完整原始证据见上述归档。

在 AI 检查器的资源完整性改动和前五个里程碑重新验证后，当前源码以显式 Wayland 和同一私有 D3D12 驱动重新运行正式检查。实际设备为 Intel Arc 140T，交换间隔 0；种子 42/43 的完整 1080p 帧 p95 为 **26.618/25.863 ms**，503 项断言、零跳过，失败项仅为两个种子超出 16.67 ms。120 个逐帧样本、构建与设备身份、五份命令日志及 SHA-256 见[当前正式失败报告](evidence/render_gpu_after_ai_refresh_20261006.json)和[原始归档清单](evidence/render_gpu_after_ai_refresh_20261006_manifest.json)。这次复测未形成产品修复，`task-24.1.2.2` 和 `ms-24.1` 仍未完成。

FXAA 的零方向提前返回候选在隔离资源副本中完成画质预检：`fxaa` 和 `auto_combined` 各五帧的 RGB 与模拟状态均与原着色器逐字节一致。随后使用与上述正式检查**相同哈希**的基准、引擎和 D3D12 驱动，在真实 Wayland 窗口以两个种子、两轮交错运行完整 1080p 画质。种子 42 的基线／候选 p95 为 **21.776/18.664、38.423/21.477 ms**；种子 43 为 **43.862/58.482、25.895/65.174 ms**。候选在种子 43 两轮均变慢，所有候选仍超出 16.67 ms，因此不合入。逐帧原始样本、四次画面捕获、补丁、日志及哈希见[候选审查摘要](evidence/fxaa_zero_dir_20261006.json)和[可复现原始归档](evidence/fxaa_zero_dir_20261006.tar.gz)；此诊断不改变产品门禁。

在 Intel Arc 140T、Mesa 26.2.2 D3D12 私有驱动、Wayland/WSLg 下，正式门禁的种子 42/43 p95 分别为 **17.923/18.682 ms**，交换间隔为 0，`glFinish` p95 分别为 0.058/0.063 ms。完整样本、设备身份、驱动和二进制 SHA-256 见 [正式 GPU 报告](evidence/render_gpu_wayland_20261006.json)。这次失败比默认 llvmpipe 运行的 169/148 ms 更接近目标，但仍不能标记通过。原始正式报告 SHA-256 为 `855fd376e154041b8082334d9f49cc80632bc77f063fa8c3ae87d0da9f110a33`。

刷新前五个里程碑后，以相同哈希的基准、引擎和 D3D12 驱动再次运行正式 `render_regression`：种子 42/43 的完整帧 p95 为 **25.457/26.792 ms**，交换间隔仍为 0，`glFinish` p95 为 0.047/0.057 ms；503 项断言、零跳过，失败项仅是两个种子超出 16.67 ms 预算。见 [重测原始报告与命令日志](evidence/render_gpu_repeat_20261006/report.json)，报告 SHA-256 为 `6f33272719da9bfd88623b32c0b8213e4167ca1581d7c126bfe5ab034f34bb25`。重复测量较早一次更慢，说明当前 WSLg 呈现路径存在运行间波动；不能用其中较快的一次代替稳定达标证据。

独立 `SDL_GL_SwapWindow` 计时在一个种子 43 诊断运行中记录了 151 次交换，交换调用自身 p95 为 **16.557 ms**，同次完整帧 p95 为 **18.631 ms**；见 [交换计时](evidence/render_swap_profile_20261006.json)。两种 p95 不应直接相减，但样本显示窗口呈现占用主要时长。该诊断不改变正式门禁。

原始数组还允许逐帧配对：151 次交换包含首帧 1 次、热身 30 次和测量 120 次，因此将测量帧 `render.samples_ms[i]` 与 `swap.samples_ms[i + 31]` 对齐。120 个差值全部为正，中位数 **2.285 ms**、p95 **2.847 ms**（范围 2.009–3.772 ms）。这只是在交换调用之外观察到的墙钟时间，**不能代表 GPU 绘制成本**：交换调用也可能等待之前提交的 GPU 命令。仍须以包含真实交换的完整帧 p95 判定产品门禁。

[SDL 的交换间隔文档](https://wiki.libsdl.org/SDL2/SDL_GL_SetSwapInterval)将 0 定义为立即更新，1 为垂直同步，-1 为自适应同步；本机正式运行已报告 0。因此仅将间隔改为 0 不是剩余问题的修复。[WSLg 官方说明](https://github.com/microsoft/wslg/wiki/Controlling-WSLg-frame-rate)指出其呈现要经过 Linux 的 Weston 与 Windows 的 DWM 两级合成，默认向 Windows 最多提交 60 fps。结合本项目逐帧配对数据，合成/传输路径是待验证的原因之一；这些资料本身不能证明本机每次等待的具体来源，也不能代替目标设备上的完整帧测试。

本机 `/mnt/wslg/weston.log` 当前启动记录报告 `rdp_monitor_refresh_rate: 60000`。通过 Windows [`EnumDisplaySettingsW` 的当前模式查询](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaysettingsw)，两台显示器分别为 `2880×1800 @ 120 Hz` 与 `1920×1080 @ 60 Hz`；这解释了只读 GPU 属性虽报告 120 Hz，WSLg 仍以双屏中较慢的 60 Hz 提交。按照 [WSLg 的官方说明](https://github.com/microsoft/wslg/wiki/Controlling-WSLg-frame-rate)，把提交率设高于实际 60 Hz 屏幕可消耗的速率会丢弃额外帧并浪费资源。因此仅提高 WSLg 提交率不能作为本机双屏配置的产品修复；仍需在目标显示路径上隔离测量完整帧与可见帧。

尝试把 SDL 窗口 `SDL_GL_ALPHA_SIZE` 从 8 改为 0，在独立 worktree 编译并以两个种子、两轮交替运行。四组原配置 p95 为 20.449、19.719、20.276、20.799 ms；相邻的无 alpha 配置为 21.216、21.671、22.858、20.737 ms，见 [A/B 原始帧样本](evidence/render_alpha0_ab_20261006.json)。该改动没有稳定收益，未合入主线。

正式长时测试结束后，使用与上述正式 GPU 报告**相同哈希的基准、引擎和 D3D12 驱动**，在独占的图形测量窗口中交替运行 SDL 交换间隔 0、-1、1。`LD_PRELOAD` 诊断探针逐次确认驱动接受并报告了请求的间隔；每次都保持 1920×1080、完整 PBR 画质、真实窗口交换、120 个测量帧和 `glFinish`。两种种子、两轮的完整帧 p95 如下（ms）：

| 种子 | 间隔 0 | 间隔 -1 | 间隔 1 |
| --- | --- | --- | --- |
| 42 | 16.906 / 27.048 | 18.777 / 25.866 | 19.884 / 24.627 |
| 43 | 24.251 / 21.579 | 26.552 / 30.986 | 22.958 / 37.398 |

12 次均未达到 16.67 ms 预算，且各模式随运行轮次有明显波动。`glFinish` 阶段 p95 仅约 0.05–0.07 ms，长尾仍在提交与交换阶段。见 [A/B 原始报告及逐次日志](diagnostics/render-swap-interval-ab-1791229412562625558/report.json)。该实验仅用于定位，不替代 `render_regression` 的正式产品门禁；没有修改引擎的交换策略。

再用相同哈希的基准、引擎和 D3D12 驱动，在独占测量窗口中交替比较 Wayland 和 XWayland/EGL。两个种子各重复两轮，均为 1920×1080、完整 PBR 画质、交换间隔 0、真实窗口交换及 120 个测量帧。完整帧 p95（ms）如下：

| 种子 | Wayland | XWayland/EGL |
| --- | --- | --- |
| 42 | 26.410 / 30.503 | 58.862 / 54.272 |
| 43 | 28.268 / 34.403 | 32.790 / 46.218 |

8 次都超过 16.67 ms，XWayland/EGL 在本机也没有改善。报告与 8 份逐次日志的哈希、设备身份和 120 帧原始数组已经核验，见 [后端 A/B 证据](diagnostics/render-backend-ab-1791236832261019412/report.json)（报告 SHA-256：`25cbe54f61d35457bb99b0ccedc5f5db49ed95add99aee51ace974a3da36cb70`）。该结果只用于排除本机的一个呈现路径候选，不改变正式门禁失败的结论。

为进一步拆分成本，在同一 D3D12 设备和 Wayland 路径上交替运行：最小化 SDL 清屏并交换、完整 PBR 绘制后跳过交换但执行 `glFinish`、以及完整 PBR 绘制加真实交换。两种子、两轮的完整帧 p95（ms）为：

| 种子 | 最小化清屏+交换 | 完整 PBR、无交换+`glFinish` | 完整 PBR+交换 |
| --- | --- | --- | --- |
| 42 | 10.449 / 9.376 | 22.934 / 18.316 | 24.957 / 22.736 |
| 43 | 9.191 / 11.558 | 14.798 / 15.849 | 24.328 / 26.670 |

[原始报告与 12 份逐次日志](diagnostics/render-present-floor-ab-1791237301794458504/report.json)的哈希和 120 帧数组均已核验（报告 SHA-256：`d6f0340bce205981ed46aefc763fc7b2dcd152bb85cfa3c525ca32cf25903cf6`）。最小窗口帧低于预算，完整绘制即使不交换也曾超过预算；因此此前把交换调用的整个等待都归因于 WSLg 合成是不成立的。各组 p95 来自不同运行，不能直接相减或相加来量化各阶段成本。

隔离工作树中的[阶段计时补丁](diagnostics/render_phase_profile.patch)在几何、光照、后处理后分别等待 GPU 完成。无交换诊断中，种子 42/43 的几何阶段 p95 为 **4.646/4.813 ms**，光照为 **3.874/3.334 ms**，后处理为 **3.722/2.776 ms**；见 [四次阶段测量](diagnostics/render-gpu-phase-1791237700005545755/report.json)（报告 SHA-256：`79008cb07a37e12b50753af6ca67b5cac70c2f70bf932759be3a0881de55347f`）。每阶段插入 `glFinish` 会改变流水线调度，这些数字用于排序瓶颈，不是正式帧预算。

又在隔离工作树尝试两种带真实交换的改动。只让 PBR 光照写入实际读取的 HDR 目标时，[八次交替对照](diagnostics/render-single-target-ab-1791237780682837942/report.json)没有稳定收益。进一步把该目标从 RGBA16F 改为 R11G11B10F 时，[八次交替对照](diagnostics/render-compact-hdr-ab-1791238088396097149/report.json)中的候选版本四次均快于相邻基线，但候选 p95 仍为 **24.916、25.276、28.152、27.323 ms**，全部超预算。

对紧凑 HDR 候选再用固定的 llvmpipe 参考图捕获 6 种渲染模式、每种 5 帧。旧渲染模式的 5 帧逐字节一致；5 种 PBR 模式的各帧约 **5.1 万–5.7 万**个像素改变，最大通道差达到 **39**，不满足现有精确图像回归。见[逐帧差异报告](diagnostics/render-compact-hdr-image-1791238277828019302/report.json)和[带 SHA-256 清单的原始图归档](evidence/render_compact_hdr_image_20261006.zip)（归档 SHA-256：`3200c673b1211e98ba0196094d8f0cce6f576128b1a501de7ddce8b579d5c4a5`）。两项改动只保留为诊断补丁，没有合入主线；不能以牺牲画质或刷新参考图的方式掩盖未达标的完整帧。

为避免逐阶段 `glFinish` 改变流水线，又在隔离构建中使用[GPU 时间戳补丁](diagnostics/render_gpu_timer.patch)，于几何、光照和后处理边界记录查询，在 150 帧结束后才读取 120 个测量帧的结果。[Khronos 时间查询说明](https://wikis.khronos.org/opengl/Timer_Query)指出过早读取未完成的查询会使异步测量变为同步等待。四次完整画质、真实交换的诊断中，完整帧墙钟 p95 为 **24.501、30.839、28.902、28.682 ms**，对应 GPU 三阶段总时长 p95 为 **10.224、15.466、13.238、12.190 ms**；几何阶段 p95 为 **1.966–3.015 ms**，光照为 **5.112–5.898 ms**，后处理为 **5.636–7.602 ms**。见[12 次交替运行、原始 GPU 时间戳和日志](diagnostics/render-gpu-timer-1791238871585667465/report.json)（报告 SHA-256：`ce7f26fee7bccb07029543637a53cad637c715c750c027e7fd2264bcb98797e9`）。同帧墙钟减去 GPU 总时长的中位数为 **12.93–14.54 ms**，其中包含 CPU、驱动和呈现等待，不能当作单独的合成器耗时；各阶段的 p95 也不能直接相加。

关闭单个后处理效果的[十次探索](diagnostics/render-effect-sweep-1791239035644434997/report.json)出现所有 GPU 阶段同时大幅变慢的运行，不能从这些数据推出某个效果的稳定收益。随后仅作上限诊断，把方向光阴影从九次采样改为一次：[两种子两轮交替测量](diagnostics/render-shadow-sample-ab-1791239269849915751/report.json)中，光照阶段 p95 在各相邻组下降 **0.393–1.049 ms**，但完整帧 p95 仍为 **27.905、28.306、32.009、30.566 ms**，且阴影画质被刻意改变。该补丁只用于定位，没有合入主线。GPU 时间戳与阴影对照都指向光照和后处理成本，而不是一个可以单独消除的交换间隔问题。

在隔离构建中又比较了基准每帧选择 GL 上下文与跨帧持有 `ContextHolder`。使用相同的引擎和 D3D12 驱动，种子 42/43 各重复两轮：原方案 p95 分别为 **24.388/26.184 ms**、**23.556/50.879 ms**，持有方案分别为 **25.168/29.861 ms**、**29.106/25.186 ms**。见[补丁](diagnostics/render_persistent_context.patch)及[八次 A/B 原始记录](diagnostics/render-persistent-context-ab-1791239709383686518/report.json)（报告 SHA-256：`8352cd6a99be8b580a9a970a4aff3c6f15c985f77709ce7e34c1c075971764b6`）。只有最后一组因原方案出现长尾而看似改善，整体没有稳定收益；该补丁没有进入产品代码。

随后用[独立 SDL 上下文计时探针](diagnostics/sdl_context_timing.c)测量 `SDL_GL_MakeCurrent`，保持完整 PBR、真实交换、两个种子和两轮重复。每次运行约 635 次绑定及 635 次解绑；绑定调用 p95 为 **0.0138–0.0142 ms**，解绑调用 p95 为 **0.0274–0.0309 ms**，而同次完整帧 p95 为 **17.672–32.121 ms**。原始调用数组、四份日志和二进制哈希见[计时报告](diagnostics/render-context-timing-1791239817920225704/report.json)（报告 SHA-256：`8ecc90aeb062d4ae13b14b5768053ffa5d49ffe373867df7d2a05e656cfc484e`）。少数解绑调用有 17–33 ms 长尾，因此不能排除个别帧受上下文切换影响；常态切换成本不足以解释前述约 13–15 ms 的墙钟与 GPU 时间差。两组诊断报告和日志的 SHA-256、120 帧原始数组及设备配置已重新核验，不是产品验收结果。

再在隔离构建中尝试把单盏全屏方向光的 PBR 直接光照与 IBL 环境光合并为一次 G-buffer 读取和 HDR 写入；零盏、多盏及非方向光仍走原通道。[候选补丁](diagnostics/render_fused_ibl_with_timer.patch)包含本次 GPU 时间戳仪表，能在当前主线直接应用，仅供复现。相同基准、两个种子、两轮交替且保持完整 1080p PBR 与真实窗口交换时，种子 42 的基线/候选 p95 为 **22.914/20.520**、**23.206/20.823 ms**；种子 43 为 **21.858/31.373**、**24.366/26.962 ms**。八次均超 16.67 ms，候选没有跨种子的稳定收益。[性能报告与逐次日志](diagnostics/render-fused-ibl-ab-20261006/report.json)的哈希、GPU 时间戳及每次 120 帧数组已核验（报告 SHA-256：`32dbd38522359017225c0579ff0fb845d10e6e10524548c55debdd58c33dd48f`）。

相同候选在 llvmpipe 的五帧固定场景中保持模拟状态逐字节一致，但每帧有 **6,050–6,689** 个像素与基线不同，最大通道差 **2–3**，不符合当前精确图像回归。[逐帧差异与哈希](diagnostics/render-fused-ibl-image-20261006/report.json)和[原始图像归档](evidence/render_fused_ibl_image_20261006.zip)已核验（归档 SHA-256：`42ba164e5724fc95350af1c13ab4a7e50f13ed0caa8ad29ef03d7eb843f8fd6f`）。该候选未合入产品代码，也未调整画质基线或门禁；`ms-24.1` 继续未通过。

在恢复原 PBR 着色器后，用[九点 GPU 时间戳补丁](diagnostics/render_post_gpu_timer.patch)进一步拆分几何、光照、Bloom 提取／横向模糊／纵向模糊、自动曝光、色调映射及 FXAA；全部查询仍在 150 帧完成后读取。Intel Arc 140T/D3D12、完整 1080p PBR、真实交换的四次运行中，整帧墙钟 p95 为 **25.431、25.223、25.595、28.673 ms**。Bloom 提取的 GPU p95 为 **2.097–2.884 ms**，FXAA 为 **1.311–3.670 ms**；两次模糊各约 **0.262 ms**，自动曝光约 **0.262 ms**。这些分位数不能相加，时间戳也有约 0.131 ms 的量化阶梯。见[四次运行的原始时间戳与日志](diagnostics/render-post-gpu-profile-20261006/report.json)（报告 SHA-256：`380e1bc009116f510e350684e7c841b2f4f460fed6ecfad4d704ca9bbecc08f8`）。本机下一轮优先检验 Bloom 提取与 FXAA 的等画质优化；当前测量没有改变产品验收结论。

针对 Bloom 中间纹理，在隔离构建中将两张半分辨率 RGBA16F 改为 R11G11B10F，不改最终 HDR 缓冲。[候选补丁](diagnostics/render_compact_bloom_with_post_timer.patch)包含九点时间戳仪表，仅供复现。两种子两轮、交替八次的基线／候选完整帧 p95 分别为种子 42 的 **23.403/23.614、38.704/36.636 ms**，以及种子 43 的 **32.565/26.714、31.657/50.362 ms**；Bloom 提取 GPU p95 也没有跨轮稳定下降。八次全部超预算，运行间漂移明显。[逐次样本与阶段时间](diagnostics/render-compact-bloom-ab-20261006/report.json)已按日志重新核验（报告 SHA-256：`058216471eb6fea3181dfecdaf11c6ffff75d0c72f674596bebfb96157680f4b`）。五帧固定画面的状态逐字节一致，改变的像素依次为 **0、0、57、65、151**，最大通道差 **2**；见[图像差异](diagnostics/render-compact-bloom-image-20261006/report.json)及[原始图像归档](evidence/render_compact_bloom_image_20261006.zip)（归档 SHA-256：`50485b697e3026aa32435df3dbaf8941edfbe2484f699e54acf6b362e528f964`）。候选没有稳定性能收益，也不满足精确图像回归，未合入。

为区分像素负载与固定开销，又在原 Bloom 格式和同一 D3D12 驱动上，用[诊断分辨率补丁](diagnostics/render_resolution_profile.patch)交替测量 960×540、1280×720、1920×1080。每种分辨率两个种子、两轮，共 12 次，全部保留完整 PBR 效果、真实交换和每次 120 帧；仅 **1080p** 属于产品门禁。三种分辨率的完整帧 p95 区间分别为 **17.468–24.114、19.156–25.582、26.683–40.500 ms**，对应 GPU 总时长 p95 区间为 **4.981–9.093、7.193–9.077、11.059–18.776 ms**。逐帧墙钟减 GPU 时间的中位数在 540p 为 **10.688–12.428 ms**，在 1080p 为 **14.689–16.810 ms**；它同时包含 CPU、驱动和呈现等待，不能归因于某一个子系统。GPU 成本和这部分额外时间总体上随分辨率增大，说明只缩小 Bloom 中间纹理不足以达到 1080p 预算。见[12 次原始数组、设备身份与日志](diagnostics/render-resolution-sweep-20261006/report.json)（报告 SHA-256：`88ee60cbad24c86814c8daaff4c4793218e6e3e96b4fbd37d0f91244811eb9e4`）。

源码中的 OpenGL 状态缓存默认关闭，当前引擎没有调用其启用入口。隔离实验在紧凑 Bloom 候选保持不变的条件下直接启用现有缓存：[五帧固定场景](diagnostics/render-cache-naive-image-20261006/report.json)的 RGB 和状态逐字节相同，[原始图像归档](evidence/render_cache_naive_image_20261006.zip) SHA-256 为 `65a6b4c89dd0cbb891b701dc44853619b13dea1478fa87c61a955fa2b3db5251`。但两个种子、两轮交替的完整 1080p 帧 p95 中，种子 42 的基线／启用缓存为 **23.918/27.756、32.869/36.751 ms**，种子 43 为 **32.353/28.013、30.553/31.799 ms**，无稳定收益；见[八次原始样本](diagnostics/render-cache-naive-ab-20261006/report.json)（报告 SHA-256：`04568298e5227ac0c8337a9bab8eff2ec7aee629c40fef809c5bddfd3417f481`）。[隔离补丁](diagnostics/render_cache_naive_with_compact_bloom.patch)只供复现；固定场景也未验证外部 GL 状态改变后的缓存失效，不能据此在产品代码中启用。

用[已有 SDL 交换计时探针](diagnostics/sdl_swap_timing.c)对 540p 与 1080p 各做两种子两轮逐帧配对。首个种子 42 的相邻运行中，540p 完整帧／交换调用 p95 为 **15.643/10.303 ms**，1080p 为 **24.306/18.208 ms**；各帧墙钟减交换调用的中位数为 **4.981/5.579 ms**。随后同一序列出现完整帧 p95 **66–143 ms** 的异常慢运行，GPU 和交换时间也同时升高；额外一次不带探针的 1080p 运行 p95 为 **24.346 ms**，带探针的下一次为 **29.965 ms**。见[八次运行、两次复核及完整原始数组](diagnostics/render-swap-resolution-20261006/report.json)（报告 SHA-256：`fa149ad35bb919f8e7a746fc8736cc04aa3dd7435539acc8de15019f512f2045`）。这些数据说明交换调用可占据大量墙钟时间，但其中包含排队 GPU 工作；严重运行间漂移和探针运行差异使它不能量化合成器成本，也不能替代正式门禁。

又在隔离工作树试验 FXAA 的固定邻域采样：`texelFetch` 加边界钳制，以及保留原有纹理过滤的 `textureOffset`。两种候选均通过同一个 321×181、PBR＋Bloom＋FXAA＋自动曝光的五帧捕获合同，模拟状态与基线逐字节一致，但 RGB 未达到精确图像门禁。`texelFetch` 每帧改变 1,678–2,407 个像素，最大通道差 51；`textureOffset` 每帧改变 4–42 个像素，最大通道差 21。见[两份补丁、逐帧 SHA-256 与原始捕获](diagnostics/fxaa-sampling-20261006/report.json)。这些差异发生在性能测试前，两个候选均未合入，也不刷新参考图。

同一台机器的 Windows 原生 OpenGL 驱动提供了独立的平台对照。用 MSYS2 UCRT64 GCC 16.2 构建当前代码的 `engine_render_budget_benchmark`，Intel Arc 140T 驱动 `32.0.101.8860` 报告 OpenGL 4.6，交换间隔为 1。保持 1920×1080、完整 PBR＋Bloom＋FXAA＋自动曝光、真实窗口交换、30 帧预热和 120 帧测量，对两个种子各运行两次：

| 种子 | 首次 p95 | 复测 p95 |
| --- | ---: | ---: |
| 42 | 13.1122 ms | 12.0382 ms |
| 43 | 11.4446 ms | 11.3119 ms |

四次均低于 16.67 ms，且每次都记录了有效比赛帧、GPU 身份、完整逐帧数组及可执行文件哈希，见[原生 Windows 诊断清单](evidence/render_native_windows_20261006/manifest.json)。另外临时移走噪声纹理后，基准以明确的资源错误和退出码 1 结束，资源已恢复，错误日志也在清单中。该对照表明本机 Windows 原生路径可以达到预算，而现有 Linux/WSLg 路径仍超预算；两个路径使用不同驱动和窗口系统，不能把差值全归因于 WSLg，也不能将 Windows 结果替代 `program.json` 指定的 Linux x86_64 产品门禁。`ms-24.1` 和相关阻断问题保持未通过。

原生对照的复现方式是在 MSYS2 UCRT64 Shell 中安装 GCC、CMake、Ninja、Boost、SDL2 及 SDL2_image/ttf/gfx；将仓库当前源码放入短的 Windows 路径，并确保字体符号链接在 Windows 上可读取，然后执行：

```sh
cmake -S C:/football-native-src/engine -B C:/football-native-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON_BINDINGS=OFF \
  -DFOOTBALL_USE_MINGW=ON \
  -DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY=C:/football-native-build/bin
cmake --build C:/football-native-build --target engine_render_budget_benchmark --parallel 4
PATH=/c/football-native-build:/ucrt64/bin:$PATH \
GFOOTBALL_DATA_DIR=C:/football-native-src/engine/data \
GFOOTBALL_USE_PBR=1 GFOOTBALL_PBR_BLOOM=1 GFOOTBALL_PBR_FXAA=1 \
GFOOTBALL_PBR_AUTO_EXPOSURE=1 SDL_VIDEODRIVER=windows SDL_AUDIODRIVER=dummy \
/c/football-native-build/bin/engine_render_budget_benchmark.exe 42
```

对种子 43 及重复轮次执行相同命令。该路径只验证原生性能。变更后的 Linux `render_images.py` 已在全新 Release 与 ASan/UBSan 构建中通过六种模式、两种配置共 12 个实际 GameEnv 捕获，**2088 项断言、零跳过**，两种配置的状态与 RGB 逐帧一致；[完整报告、命令、输入与源码哈希](evidence/render_native_windows_20261006/manifest.json)已归档。此图像检查不测量 1080p 帧预算，Linux 性能门禁仍需独立通过。

在提交 `d49e896` 后，以同一 Mesa 26.2.2 D3D12 私有驱动和 WSLg Wayland 路径刷新正式 Linux `render_regression`。两个固定种子均保留 1920×1080、完整画质、真实窗口交换和 120 个测量帧；种子 42/43 的完整帧 p95 分别为 **22.018/23.247 ms**，交换间隔为 0，503 项断言、零跳过，失败项仅为两个种子超出 16.67 ms。见[当前源码正式报告、逐次日志和哈希清单](evidence/render_gpu_current_20261006/manifest.json)。相比此前 25.457/26.792 ms 的一轮虽更快，但仍不能以运行间波动代替稳定通过；Linux 产品门禁和 `ms-24.1` 继续失败。

复现这台 WSL 设备上的正式检查：

```sh
python3 .project/checks/render_regression.py \
  --gpu-driver-root /root/.cache/football-mesa-build-20260913-a/install-wayland \
  --sdl-video-driver wayland
```

私有驱动路径仅用于本机 D3D12 适配；其他 Linux GPU 应使用其实际驱动并保留相同的分辨率、画质、窗口交换和 16.67 ms 门禁。后续工作需要在产品目标显示路径上继续定位交换调用的等待来源和长尾，任何新方案都必须同时通过图像功能检查与两个种子的完整帧时间门禁。

## 2026-10-07：当前源码完整质量链复测

ECS v12 与长赛 v10 参考刷新后，从 `quality_selftest` 开始完整运行 `task-24.1.2.2`。框架、架构、性能、手感、网络、PBR、HDR 后处理和图像回归均在当前源码上通过；最后的 `render_regression` 未通过。显式 Wayland、同一私有 Mesa 26.2.2 D3D12 驱动、Intel Arc 140T、1920×1080、PBR + Bloom + FXAA + 自动曝光、真实窗口交换、每种子 30 帧热身与 120 帧测量下，种子 42/43 的完整帧 p95 为 **23.885/24.814 ms**，均超过 **16.67 ms**。交换间隔为 0，`glFinish` p95 为 0.061/0.061 ms；503 项断言、零跳过，失败仅为两种子的帧时预算。此结果未达到产品门槛，`task-24.1.2.2` 与 `ms-24.1` 仍不得标记完成。

[本轮正式报告](evidence/render_gpu_after_baseline_refresh_20261007.json)、[原始报告与四份日志归档](evidence/render_gpu_after_baseline_refresh_20261007.tar.gz)、[SHA-256 清单](evidence/render_gpu_after_baseline_refresh_20261007_manifest.json)和[质量编排失败记录](evidence/render_regression.json)保留了逐帧样本、设备与二进制身份、构建命令及门禁结果。
