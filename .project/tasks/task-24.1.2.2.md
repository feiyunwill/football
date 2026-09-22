# task-24.1.2.2 — 渲染性能验收

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 明确 GPU/分辨率/画质设置下 1080p 帧时间 p95≤16.67ms；缺少测量不得通过

依赖：task-24.1.2.1

执行顺序：无

验收检查：render_regression

执行：`python3 .project/quality.py run task-24.1.2.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-13 渲染期间采样：三个原生入口已接入主线程协作采样，当前固定输入门禁2625238条断言、1030个确认帧在Release／ASan逐帧重放通过；新组件TSan及实际画面回归通过。分段实测采样等待缩短，但本地应用约73–76ms，追帧短按、服务器接收空档及单次绘制阻塞仍未解决。详见[渲染采样实现与实测](../reports/optimization-native-render-input-service-2026-09-13.md)。完整前置链仍为过期，状态不提升。

2026-09-13 本地输入时间归属：已按原始固定截止时间消费带时间的有界观察，避免当前按键回填过去帧；当前固定输入门禁2773304条断言、1030个确认帧在Release／ASan逐帧重放通过，真实引擎903个对照帧状态逐字节相同。50ms产品延迟、网络接收空档和GL阻塞仍未完成，详见[本地输入时间归属报告](../reports/optimization-native-input-timeline-2026-09-13.md)。状态仍由完整质量链计算，不手动提升。


2026-09-13 接收与 GPU 定位：补充实际 recv／GL／GPU 查询，保留 UDP 第 203 帧迟到导致的严格窗口失败；CPU 后处理入口等待与 GPU ambient／SSAO 成本已区分。全屏分段原型未采用；SSAO 展开在 5 个状态的约 4147 万字节画面对照中完全相同，但稳定性能收益尚未证明。产品源码与阈值未变，详见[网络与 GL 定位报告](../reports/optimization-native-network-gl-profile-2026-09-13.md)。状态仍按完整质量链计算。


2026-09-13 接纳链路与线程职责：真实 TCP／UDP 的接收、接纳、封帧与实际引擎输入已逐帧对应，1036 个确认帧在 Release／ASan 全部重放通过；受控分片、重复、乱序、迟到、超窗与冲突契约通过。主线程采样原型在真实窗口中记录 p95 7.097ms、最大15.758ms采样间隔，尚未正式接入三个入口或完成线程／异常契约；实际55.897ms响应未达标。详见[本轮报告](../reports/optimization-native-admission-ui-owner-2026-09-13.md)。不提升整体状态。


2026-09-13 主线程采样实施：三个正式入口已接入窗口／游戏线程职责分离，Release／ASan／TSan 并发合同及真实线程观测通过，1035 个确认帧在 Release／ASan 全部重放通过。固定门禁 B 仍因 TCP 第 138 帧持续输入空档失败；后续观测又发现批量接收后未发布 505、506 帧，不能宣称网络或 50ms 手感达标。详见[实现、失败及下一步](../reports/optimization-native-main-ui-owner-2026-09-13.md)。状态不手动提升。


2026-09-13 硬件渲染调查：实际 Intel Arc／D3D12 已完成 1080p 引擎帧和状态／图像对照，但重复初始化暴露可独立复现的 Mesa slab 自身死锁。隔离源码修复正在构建验证；成功样本 p95 仍为 18.948–24.990ms，不能提升产品质量状态。见[硬件渲染与驱动定位](../reports/optimization-native-hardware-rendering-2026-09-13.md)。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。


2026-09-13 正式帧捕获策略已实现；Release 软件/GPU 各 169 条实际断言通过，Sanitizer 编译进行中，无头边界及固定验收接入待完成。见 [实现与验证进度](../reports/optimization-native-frame-capture-2026-09-13.md)，保留未通过状态。


2026-09-13 捕获策略第二次复核：已补齐 GameEnv 无头边界与固定 input_contract 接入；Release 软件/GPU、Sanitizer 软件各 174 条断言通过，原有骨骼/卡片双构建回归通过。首次 GPU Sanitizer 初始化失败及独立 D3D12 复现保留，完整固定输入验收运行中。详见 [当前实现证据](../reports/optimization-native-frame-capture-2026-09-13.md)，不提升产品验收状态。


2026-09-13 最新固定输入验收失败于软件 UDP 恢复再次按键：权威帧 442–447 中性，第 448 帧在约 342.668ms 响应，保留未通过。独立 GPU 三模式全部功能检查通过，1,194 次渲染无产品 RGB 回读；Python 软件/GPU 各 23 条断言通过。真实两轮回放交叉验证运行中，见 [最新证据](../reports/optimization-native-frame-capture-2026-09-13.md)。


2026-09-13 本轮最终复核：十文件捕获优化、默认 Python API 和 GPU 三模式功能检查完成，1,194 次渲染无产品回读；2,050 个真实权威帧在 Release 与 Sanitizer 分别回放通过。完整固定输入仍失败于软件 UDP 恢复延迟，GPU Sanitizer 初始化及渲染 p95 仍未达标，保持未通过。见 [最终实现与证据](../reports/optimization-native-frame-capture-2026-09-13.md)。
