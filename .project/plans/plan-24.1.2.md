# plan-24.1.2 — 画质与帧预算

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
