# 真实窗口的重复输入延迟基线

归属 `ms-22.1 → plan-22.1.2 → task-22.1.2.2`。新增 [`feel_latency_window.py`](../optimization/diagnostics/feel_latency_window.py) 作为诊断工具。它在隔离的 Xvfb 中启动当前 `standalone_game` 产品入口，以 XTEST 向实际 SDL 窗口交替发送 30 次左右方向按键；原有原生跟踪库记录 `GameEnv::StepWithInput` 后的受控球员位置与方向速度，以及产品画面交换。每次动作、原始跟踪、分析报告和日志均保存在可提交的证据包中。该工具不会把诊断结果注册成正式验收。

本次运行的 30 次动作中，27 次在同一受控球员上找到对应的引擎步进；其中 4 次检测到按键方向上的速度变化达到预设 0.1 阈值。另 3 次在按键时没有受控球员；余下 23 次虽有输入步进，却没有满足速度变化判据。因此球员**实际响应 p95 尚不能成立**，`feel_regression` 保持未就绪，`task-22.1.2.2` 与 `ms-22.1` 继续为 `planned`。

仅对 27 次输入进入步进计算，p95 为 **123.435 ms**，后续首次产品画面交换 p95 为 **249.641 ms**。后者只是输入步进后的画面交换，并非已证明球员动作出现在像素中的时间；不能据此声称输入到球员像素响应达标。观察到的 4 次速度变化不足 20 个样本，诊断报告将响应 p95 留为 `null`。这组结果直接否定当前软件渲染环境下已达到“本机动作生效 p95 ≤50 ms”的说法，并指出下一步要先建立足够多的有效受控球员样本，再处理渲染占用与步进取样延迟。

证据包 [`feel_latency_diagnostic_20261001.tar.gz`](../optimization/evidence/feel_latency_diagnostic_20261001.tar.gz) 的 SHA-256 为 `c47de1e683f0ffd3a1b1421e6eb6b89e1eb005e4b3dd609e30f8da302abd78ff`，包含完整 30 次动作、原始 `events.jsonl`、分析报告和进程日志。报告 SHA-256 为 `553d58aa54bd13b93ef461c4d33fae0663ab44545b5889dc44e76b4a067c9fc7`；报告内还记录工具、键盘驱动源码、原生跟踪源码、产品可执行文件及跟踪库的哈希。重跑：`python3 .project/optimization/diagnostics/feel_latency_window.py --cycles 30`。

代码路径显示 [`NativeWindowInput`](../../engine/src/frame_sync/native_loop.hpp) 在 UI 线程轮询 SDL 并把事件交给共享时间线，工作线程在 [`standalone_game.cpp`](../../engine/src/frame_sync/standalone_game.cpp) 中完成固定步进和渲染；渲染期间工作线程不能推进球员状态。本次 201 次渲染的 p50 / p95 为 96.463 / 121.289 ms。27 次输入进入步进的等待区间中，有 26 次与工作线程渲染相交；交集时长 p95 为 **110.360 ms**。这证明渲染占用覆盖了绝大多数输入等待时间，但还不能把全部延迟都归因于渲染，也不能从这组数据推断真实硬件 GPU 的结果。
