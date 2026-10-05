# plan-24.1.2 — 画质与帧预算

2026-10-06 状态缓存隔离候选无稳定性能收益；交换调用计时又出现严重运行间漂移，尚不能形成可验收的 1080p 修复。产品代码、图像基线和 16.67ms 门禁未改，计划继续未通过。见[渲染诊断](../optimization/render-presentation-20261006.md)。

2026-10-06 当前源码的渲染性能任务仍未通过：隔离的紧凑 Bloom 候选无稳定收益，12 次完整画质分辨率扫描中 1080p p95 为 26.683–40.500ms。候选未合入、图像基线和 16.67ms 门禁未改，计划状态继续由当前质量证据判定。见[渲染诊断](../optimization/render-presentation-20261006.md)。

2026-09-28 当前源码 1080p GPU 预检：实际 Intel Arc 140T/D3D12 私有修复驱动上，关闭未消费 RGB 回读的离屏 Legacy 两轮 p95 为 14.98/13.85ms、PBR 完整效果为 11.11/10.64ms；相同源码的真实 SDL 窗口分别为 31.88/28.84ms 和 23.76/24.01ms，均未达到 16.67ms。交换入口占带探针整帧平均约 81%–86%，但包含已排队 GPU 工作；GLX/EGL 请求对照没有稳定收益，不采纳。PBR 离屏/窗口五帧 RGB 相同，Legacy 存在明显亮度差异待定位。四阶段原始样本与终态核验已存档，`render_regression` 保持 `ready:false`，任务和里程碑不提升。见 [当前硬件预检报告](../reports/optimization-current-gpu-1080-2026-09-28.md)。


2026-09-28 固定图像验收增量：正式 `render_images` 对 llvmpipe 321×181 的 Legacy/PBR、Bloom、FXAA、自动曝光及组合模式建立 30 帧固定 RGB/状态基线，全新 Release/完整 Debug ASan/UBSan 的 12 个真实 GameEnv 案例共 2,088 断言通过、跳过 0 项。两构建全部图像/状态逐字节一致；同时验证非空、亮度/色彩、中央与边界梯度、四边覆盖和开关响应。独立终态核验 160 输入、827 源码、16 日志，单项检查为 `verified`。实际窗口、硬件 1080p p95、`render_regression` 和 ms-23.1 仍待验收。参见 [固定图像门禁](../reports/optimization-native-render-images-2026-09-28.md)。


类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-24.1.2.1、task-24.1.2.2

验收检查：render_images、render_regression

执行：`python3 .project/quality.py run plan-24.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-13 渲染期间采样：三个原生入口已接入主线程协作采样，当前固定输入门禁2625238条断言、1030个确认帧在Release／ASan逐帧重放通过；新组件TSan及实际画面回归通过。分段实测采样等待缩短，但本地应用约73–76ms，追帧短按、服务器接收空档及单次绘制阻塞仍未解决。详见[渲染采样实现与实测](../reports/optimization-native-render-input-service-2026-09-13.md)。完整前置链仍为过期，状态不提升。


2026-09-13 接收与 GPU 定位：补充实际 recv／GL／GPU 查询，保留 UDP 第 203 帧迟到导致的严格窗口失败；CPU 后处理入口等待与 GPU ambient／SSAO 成本已区分。全屏分段原型未采用；SSAO 展开在 5 个状态的约 4147 万字节画面对照中完全相同，但稳定性能收益尚未证明。产品源码与阈值未变，详见[网络与 GL 定位报告](../reports/optimization-native-network-gl-profile-2026-09-13.md)。状态仍按完整质量链计算。


2026-09-13 硬件渲染调查：实际 Intel Arc／D3D12 已完成 1080p 引擎帧和状态／图像对照，但重复初始化暴露可独立复现的 Mesa slab 自身死锁。隔离源码修复正在构建验证；成功样本 p95 仍为 18.948–24.990ms，不能提升产品质量状态。见[硬件渲染与驱动定位](../reports/optimization-native-hardware-rendering-2026-09-13.md)。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。


2026-09-13 捕获策略第二次复核：已补齐 GameEnv 无头边界与固定 input_contract 接入；Release 软件/GPU、Sanitizer 软件各 174 条断言通过，原有骨骼/卡片双构建回归通过。首次 GPU Sanitizer 初始化失败及独立 D3D12 复现保留，完整固定输入验收运行中。详见 [当前实现证据](../reports/optimization-native-frame-capture-2026-09-13.md)，不提升产品验收状态。


2026-09-13 本轮最终复核：十文件捕获优化、默认 Python API 和 GPU 三模式功能检查完成，1,194 次渲染无产品回读；2,050 个真实权威帧在 Release 与 Sanitizer 分别回放通过。完整固定输入仍失败于软件 UDP 恢复延迟，GPU Sanitizer 初始化及渲染 p95 仍未达标，保持未通过。见 [最终实现与证据](../reports/optimization-native-frame-capture-2026-09-13.md)。
