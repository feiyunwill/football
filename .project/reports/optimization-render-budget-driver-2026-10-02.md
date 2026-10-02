# 1080p 渲染预算：驱动身份与连续比赛复核

归属 ms-24.1 → plan-24.1.2 → task-24.1.2.2。本轮让正式 `render_regression` 可显式选择项目私有的 D3D12 驱动，并让基准从 `/proc/self/maps` 报告实际加载的 Gallium 库。检查会核对路径、D3D12 渲染器和驱动 SHA-256；16.67ms 产品预算和 1920×1080 PBR＋Bloom＋FXAA＋自动曝光配置均未变。

不指定驱动时，2026-10-02 的正式检查落到 llvmpipe：种子 42／43 的 p95 为 269.513／243.255ms，均不合格。直接设置系统 `GALLIUM_DRIVER=d3d12` 的种子 43 在首帧姓名牌纹理上传处超时；这与[已定位的 Mesa D3D12 分配器自死锁](optimization-native-hardware-rendering-2026-09-13.md)吻合。将同尺寸的 `glTexSubImage2D` 暂时改为 `glTexImage2D` 仍超时，实验改动已恢复，不能据此归因于引擎的上传 API。

用私有修复驱动运行当前源码的正式双种子基准，实际 `GL_RENDERER` 均为 `D3D12 (Intel(R) Arc(TM) 140T GPU (16GB))`，加载路径均为 `/root/.cache/football-mesa-build-20260913-a/install-candidate/lib/libgallium-26.2.2.so`，驱动 SHA-256 为 `46e392bcd6aafc9abeeb1aed1874fa47cb60e1b30665d5da818c14fc5e35f998`。引擎核心 SHA-256 为 `5b631591073199825d431212bc829c695f8838a5edf7c179df92bf23c5b83850`。每种子先预热 30 帧，再计时 120 个比赛中帧；每次计时包含 `GameEnv.render()` 与 `glFinish()`。

| 种子 | p50 | p95 | p99 | 16.67ms 预算 |
| --- | ---: | ---: | ---: | --- |
| 42 | 34.337ms | 139.290ms | 204.456ms | 未通过 |
| 43 | 29.921ms | 41.285ms | 45.680ms | 未通过 |

可读[完整报告](../optimization/evidence/render_gpu_driver_20261002.json)及[报告和四项命令日志归档](../optimization/evidence/render_gpu_driver_20261002.tar.gz)。报告 SHA-256 为 `036fc84769495b2a9c78830c3e1e5bc06e13f82f7771d12dfc37904c376634e6`，归档 SHA-256 为 `ffdd7b5bb9033d90812a3f3189123eae7cc1fb73e160403c7d576b9e0822077f`。复现命令：`python3 .project/checks/render_regression.py --build <Release 构建目录> --gpu-driver-root /root/.cache/football-mesa-build-20260913-a/install-candidate`。私有驱动尚未作为产品依赖打包；本轮是硬件定位和预算复核，不构成产品级通过。种子 42 的长尾明显高于种子 43，需在受控 GPU 占用下继续定位，不据此判定某一着色器为瓶颈。

随后以 `FOOTBALL_RENDER_GPU_DRIVER_ROOT` 运行 `python3 .project/quality.py run task-24.1.2.2`，前六项检查通过，`architecture_regression` 在 Sanitizer 的 `engine_lifetime_contract` 报“Repeated restart retained match-sized allocations”并阻断后续检查。这是独立于渲染预算失败的前置门禁失败，不能把该次质量链标为通过。同一 Sanitizer 二进制、相同环境下单独重跑该合同两次均通过，167 条断言，耗时 80.84／82.11 秒，预热／结束 RSS 分别为 334684160／337154048 和 323567616／328204288 字节。说明这次失败存在运行间差异；原因未定位，保留[正式失败日志](../optimization/evidence/architecture_regression-1790935256973929987.log)，不降低门禁。
