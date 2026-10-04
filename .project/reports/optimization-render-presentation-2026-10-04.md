# 渲染基准更新与呈现路径诊断（2026-10-04）

## 结论

- 双线性 Bloom 模糊着色器的六张变化帧已用两次独立采集确认；其余图像和全部模拟状态保持原样。新的金图保留旧金图、旧采集归档、变化范围和逐像素差异校验。
- 软件 OpenGL 图像回归通过：Release 与 Debug ASan/UBSan 共 12 个实际场景、2,088 项断言、零跳过。
- **硬件渲染门禁仍失败**。1920×1080、PBR + Bloom + FXAA + 自动曝光、真实窗口交换的两个种子 p95 分别为 29.872 和 34.565 ms，高于 16.67 ms 预算。渲染里程碑不得据此标为完成。

## 证据

新金图为 `.project/checks/golden/render_images_llvmpipe_bilinear_20261004.json`，原始采集为 `.project/optimization/evidence/render_images_bilinear_20261004.tar.gz`。生成与交叉校验逻辑分别在 `.project/optimization/diagnostics/render_image_reference_refresh_20261004.py` 和 `.project/checks/render_images.py`。旧金图与旧采集归档均未修改。

完整门禁报告、同画质跳过/保留交换的配对诊断，以及 `SDL_GL_SwapWindow` 插桩的逐帧数据保存在 `.project/optimization/evidence/render_presentation_diagnostic_20261004.json`。插桩源码为 `.project/optimization/diagnostics/sdl_swap_timing.c`；仅用于定位耗时，正式门禁仍使用未插桩的完整呈现路径。

| 测量 | 种子 42 p95 | 种子 43 p95 |
| --- | ---: | ---: |
| 正式门禁，含窗口交换 | 29.872 ms | 34.565 ms |
| 配对诊断，跳过窗口交换 | 13.334 ms | 13.800 ms |
| 配对诊断，保留窗口交换 | 25.993 ms | 25.510 ms |
| 插桩运行，完整帧 | 29.305 ms | 23.454 ms |
| 插桩运行，实际交换调用 | 26.760 ms | 21.264 ms |

插桩运行各有 151 次交换调用：一帧初始化、30 帧预热、120 帧测量。表中交换调用的 p95 只取最后 120 帧；同帧总耗时减去交换耗时后的残余 p95 为 3.201 和 2.912 ms。交换调用是当前环境下的主要瓶颈，但跨次运行存在波动，不能用跳过交换的数字代替正式验收。下一步应保留真实呈现，定位 WSLg/Mesa D3D12 的交换等待与资源复制，并在相同画质、分辨率和门禁条件下复测。
