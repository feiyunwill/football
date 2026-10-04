# Wayland 呈现路径对照（2026-10-05）

渲染管线和图像回归已由当前源码的正式门禁验证通过，真实窗口呈现的 1080p 帧预算仍未通过。X11 下 `SDL_GL_SwapWindow` 是主要耗时；Wayland 对照改善了诊断帧时间，但尚未达到产品要求的 p95 ≤ 16.67 ms。

## 相同画质与硬件的结果

全部测试使用 Intel Arc 140T、Mesa D3D12 26.2.2、1920×1080、PBR + Bloom + FXAA + 自动曝光、30 帧预热和 120 帧测量。交换间隔报告为 0；除注明跳过交换的诊断外，均执行真实窗口交换。

| 路径 | 种子 42 p95 | 种子 43 p95 | 判定 |
| --- | ---: | ---: | --- |
| X11 配对诊断 | 27.592 ms | 25.257 ms | 诊断，超预算 |
| Wayland 配对诊断 | 19.328 ms | 19.605 ms | 诊断，超预算 |
| Wayland 正式门禁 | 25.650 ms | 18.634 ms | **失败**，503 项断言、零跳过 |
| Wayland 跳过交换 | 12.256 ms | 13.204 ms | 只用于定位，不满足产品契约 |
| Wayland 插桩运行的交换调用 | 17.971 ms | 16.279 ms | 只统计最后 120 次交换调用 |

Wayland 优于这组 X11 诊断样本，但正式运行的种子 42 上升到 25.650 ms，说明现有改善不稳定。`mesa_glthread=true`、`vblank_mode=0` 及其组合也没有让两个种子稳定通过。不能调高预算、跳过交换或降低画质来代替正式验收。

## 复现环境与证据

原私有 Mesa 构建只启用 X11。为避免改变原驱动，另用同一 Mesa 26.2.2 源码构建独立变体，配置 `platforms=x11,wayland`、`gallium-drivers=d3d12,softpipe`、`egl=enabled`、`glx=dri`，安装在 `/root/.cache/football-mesa-build-20260913-a/install-wayland`。SDL2 2.32.72 的 Wayland 后端需要本机的 `libxkbcommon` 与键盘配置；独立构建还需要 `wayland-protocols`。源归档、驱动、EGL 库、GLVND 配置和基准二进制的 SHA-256，以及全部逐帧原始测量与正式失败报告，保存在 `.project/optimization/evidence/render_wayland_comparison_20261005.json`。

在同一环境复跑正式门禁时，设置 `SDL_VIDEODRIVER=wayland`，将 `__EGL_VENDOR_LIBRARY_FILENAMES` 指向独立变体的 `share/glvnd/egl_vendor.d/50_mesa.json`，并执行：

```sh
python3 .project/checks/render_regression.py \
  --gpu-driver-root /root/.cache/football-mesa-build-20260913-a/install-wayland
```

下一步需要在保留真实交换的前提下继续定位 Wayland EGL/D3D12 呈现等待与渲染 pass 成本，并以相同配置重新运行正式门禁。渲染性能任务及渲染里程碑保持未通过。
