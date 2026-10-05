# 1080p 渲染呈现瓶颈（2026-10-06）

`render_regression` 仍未通过产品门禁，`ms-24.1` 保持失败。该检查在真实窗口交换和 `glFinish` 完成后测量 1920×1080、PBR + Bloom + FXAA + 自动曝光，每个种子热身 30 帧、测量 120 帧，预算为 p95 ≤ 16.67 ms。不能用跳过窗口交换或软件渲染的结果替代产品验收。

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

复现这台 WSL 设备上的正式检查：

```sh
SDL_VIDEODRIVER=wayland python3 .project/checks/render_regression.py \
  --gpu-driver-root /root/.cache/football-mesa-build-20260913-a/install-wayland
```

私有驱动路径仅用于本机 D3D12 适配；其他 Linux GPU 应使用其实际驱动并保留相同的分辨率、画质、窗口交换和 16.67 ms 门禁。后续工作需要在产品目标显示路径上继续定位交换调用的等待来源和长尾，任何新方案都必须同时通过图像功能检查与两个种子的完整帧时间门禁。
