# 原生窗口帧捕获优化验收（2026-09-13）

已完成帧捕获策略、无头边界、固定检查器接入及 Python 默认取帧回归。实际 GPU 三模式共 1,194 次渲染确认没有产品 RGB 回读。软件窗口 UDP 的恢复再次按键检查失败，渲染 p95 与 GPU Sanitizer 仍未通过，因此不提升整体产品验收状态。

任务归属：ms-24.1 → plan-24.1.2 → task-24.1.2.1 / task-24.1.2.2；同步回归 ms-22.1 输入与表现、ms-23.1 权威帧一致性。实验动机见 [GPU 回读 ABBA](optimization-native-gpu-runtime-2026-09-13.md)。本轮未改协议、服务器补默认输入规则、比赛逻辑、冻结基线或产品阈值。

## 实现

十个产品/测试文件发生修改，前后版本与二进制保存在验收阶段。GameConfig.capture_frames 默认 true；该显示策略与 render 一样不进入逻辑快照。单机显示入口关闭捕获，TCP/UDP 仅在 native_product 模式关闭，原有 Python 和旧客户端默认行为保持。

捕获开启时继续在 SDL 交换前回读，保留调用方 GL_PACK_ALIGNMENT；关闭时清空缓存，继续呈现和渲染服务轮询。GameEnv 对禁用捕获的取帧统一抛出异常，包括无头环境。真实渲染器重新启用后需先渲染新帧，避免返回旧缓存；无头默认取帧仍返回空字符串。[实际 C++ 契约](../../engine/tests/engine_frame_capture_contract.cpp)与 [固定 input_contract](../../.project/checks/input_contract.py)已接入相同源码。

## 捕获与 API 回归

| 运行 | 断言 | 实际图像 | 结果 |
|---|---:|---:|---|
| Release 软件 EGL | 174 | 5 | 通过 |
| Release Intel Arc 140T / D3D12 | 174 | 5 | 通过 |
| ASan/UBSan/LeakSanitizer 软件 EGL | 174 | 5 | 通过 |
| Python Release 软件 EGL | 23 | 5 | 通过 |
| Python Release D3D12 | 23 | 5 | 通过 |

[原生结果](../optimization/benchmarks/native-frame-capture-20260913-b/report.json)覆盖 321×181 奇数宽度、161 次单步，其中 62 帧实际在比赛中。检查包括独立读取真实后缓冲与缓存逐字节一致、关闭捕获不改变显示和完整序列化、恢复快照保留显示策略、重新启用后的正确图像、16 次预期取帧拒绝、无头默认行为及三原色检测。Release 与 Sanitizer 的五组软件 RGB 和完整逻辑状态逐字节一致。原有骨骼/裁判卡片渲染测试在两个构建中各通过 439 条断言、八种案例、六张图像。

[Python 绑定](../optimization/benchmarks/native-frame-capture-python-20260913-b/report.json)已重新编译，原生核心哈希未改变；验证配置 setter、真实 bytes 图像、重复取帧、161 次单步及快照恢复。该独立 API 检查保留完整输入验收的失败，不视为手感环节通过。

## 实际窗口与输入故障

完整固定输入验收结束并失败：此前执行的 28 个契约及双构建设备采样共 2,079,235 条断言通过，但软件窗口 UDP 未通过恢复再次按键检查。单机和 TCP 本轮通过。UDP 权威帧 442–447 在固定 200–350ms 区间内仍为中性，第 448 帧才响应，即再次按键后约 342.668ms；客户端首次非零输入在约 332.290ms。[权威与最终回放字节交叉证据](../optimization/benchmarks/native-frame-capture-window-review-20260913-a/udp-resume-failure.json)和 [客户端观察](../optimization/benchmarks/native-frame-capture-window-review-20260913-a/udp-local-resume-observation.json)保留。下一步关联实际 SDL 采样、发布帧号、收包与服务器消费时刻；尚不能归因于回读改动或先前孤立的持续输入空帧。

独立 [GPU 窗口](../optimization/benchmarks/native-frame-capture-gpu-windows-20260913-a/report.json)的单机/TCP/UDP 聚焦、松键、暂停恢复、重新按键、保存与状态检查全部通过。原始 GL 计时记录证明 445 + 302 + 447 = 1,194 次渲染中产品 glReadPixels 调用均为零，见 [统计](../optimization/benchmarks/native-frame-capture-window-review-20260913-a/gpu-readback-results.json)。观察器额外截图不计入产品回读。

| GPU 模式 | 单次输入完成 ms | 渲染 p95 ms |
|---|---:|---:|
| 单机 | 28.919 | 27.338 |
| TCP | 33.398 | 71.865 |
| UDP | 37.684 | 40.479 |

本轮使用 1280×720 私有 X11；单次响应不构成物理显示或延迟分位数保证，帧时间仍不满足 16.67ms。GPU 成功轮次不覆盖软件 UDP 的失败。

## 真实回放

[交叉回放](../optimization/benchmarks/native-frame-capture-replays-20260913-a/report.json)已全部通过：

| 保存轮次 | 每构建回放帧 | 每构建断言 | 构建 |
|---|---:|---:|---|
| 软件窗口失败轮次 | 1,018 | 452,509 | Release、ASan/UBSan/LeakSanitizer |
| GPU 窗口成功轮次 | 1,032 | 452,560 | Release、ASan/UBSan/LeakSanitizer |

两轮合计 2,050 个实际权威帧在每个构建中逐帧执行，各报告 40,000 时钟事件、零跳过，无检测器诊断。回放状态一致不能消除已经记录的输入延迟。

## 尚未通过的 GPU 内存检测

[首次原生验证](../optimization/benchmarks/native-frame-capture-20260913-a/report.json)保留失败：GPU Sanitizer 在 EGL 初始化退出，尚未进入取帧检查。继任阶段验证了软件 Sanitizer 和 Release GPU，明确保留 hardware_sanitizer_acceptance=false。

[不链接足球引擎的诊断](../optimization/benchmarks/native-frame-capture-asan-gpu-20260913-a/conclusion.json)显示，普通和 UBSan-only EGL 探针成功，ASan-only EGL 失败。ASan 下 DXCore 枚举与七项显卡属性成功，但 D3D12CreateDevice 返回 0x887a0004，Release 返回成功。该值为 [Microsoft 定义的 DXGI_ERROR_UNSUPPORTED](https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-10)。日志确认 libd3d12core.so 已加载，显式补充 WSL 库目录仍失败。直接 COM 接口的 UBSan vptr 探针另有崩溃，不能混作原始不透明 EGL 调用的故障原因。[历史 WSLg 报告](https://github.com/microsoft/wslg/issues/1341)仅提供相似现象，不证明相同根因或可用修复。

后续工作是 UDP 恢复延迟定位与受控复现、持续 GPU 长帧定位、D3D12/ASan 兼容性、私有 Mesa 的可交付运行时接入，以及完整 1080p/50ms/AI/最终质量链。所有本轮进程已结束，失败证据保留，无人工状态提升或系统驱动修改。
