# 1080p 渲染呈现瓶颈（2026-10-06）

`render_regression` 仍未通过产品门禁，`ms-24.1` 保持失败。该检查在真实窗口交换和 `glFinish` 完成后测量 1920×1080、PBR + Bloom + FXAA + 自动曝光，每个种子热身 30 帧、测量 120 帧，预算为 p95 ≤ 16.67 ms。不能用跳过窗口交换或软件渲染的结果替代产品验收。

在 Intel Arc 140T、Mesa 26.2.2 D3D12 私有驱动、Wayland/WSLg 下，正式门禁的种子 42/43 p95 分别为 **17.923/18.682 ms**，交换间隔为 0，`glFinish` p95 分别为 0.058/0.063 ms。完整样本、设备身份、驱动和二进制 SHA-256 见 [正式 GPU 报告](evidence/render_gpu_wayland_20261006.json)。这次失败比默认 llvmpipe 运行的 169/148 ms 更接近目标，但仍不能标记通过。原始正式报告 SHA-256 为 `855fd376e154041b8082334d9f49cc80632bc77f063fa8c3ae87d0da9f110a33`。

独立 `SDL_GL_SwapWindow` 计时在一个种子 43 诊断运行中记录了 151 次交换，交换调用自身 p95 为 **16.557 ms**，同次完整帧 p95 为 **18.631 ms**；见 [交换计时](evidence/render_swap_profile_20261006.json)。两种 p95 不应直接相减，但样本显示窗口呈现占用主要时长。该诊断不改变正式门禁。

尝试把 SDL 窗口 `SDL_GL_ALPHA_SIZE` 从 8 改为 0，在独立 worktree 编译并以两个种子、两轮交替运行。四组原配置 p95 为 20.449、19.719、20.276、20.799 ms；相邻的无 alpha 配置为 21.216、21.671、22.858、20.737 ms，见 [A/B 原始帧样本](evidence/render_alpha0_ab_20261006.json)。该改动没有稳定收益，未合入主线。

复现这台 WSL 设备上的正式检查：

```sh
SDL_VIDEODRIVER=wayland python3 .project/checks/render_regression.py \
  --gpu-driver-root /root/.cache/football-mesa-build-20260913-a/install-wayland
```

私有驱动路径仅用于本机 D3D12 适配；其他 Linux GPU 应使用其实际驱动并保留相同的分辨率、画质、窗口交换和 16.67 ms 门禁。后续工作需要在产品目标显示路径上继续定位交换调用的等待来源和长尾，任何新方案都必须同时通过图像功能检查与两个种子的完整帧时间门禁。
