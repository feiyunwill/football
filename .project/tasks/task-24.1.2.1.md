# task-24.1.2.1 — 可重复图像验收

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 实际 OpenGL 输出基线、非空帧、亮度/色彩/边界断言及渲染开关对照

依赖：task-24.1.1.2

执行顺序：无

验收检查：render_images

执行：`python3 .project/quality.py run task-24.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-13 待执行审查项：[原生展示入口审查](../reports/optimization-native-presentation-review-2026-09-13.md)记录三个旧主循环的插值覆盖、重复窗口交换、本地插值时基及文字/surface 异常所有权。当前为源码发现，实际程序复现与修复验收尚未执行；容量正式链运行期间未修改这些源文件。

2026-09-13 实现准备：共享原生显示时序所有者与验证程序已落盘，区分普通逻辑姿态、实际显示姿态和回滚重定向，等待不重置插值。尚未编译／执行，也未替换三个主循环，见[当前实现范围](../reports/optimization-native-presentation-owner-2026-09-13.md)。

2026-09-13 最新：原生显示所有者在 Release／ASan／UBSan 下各通过 10,102 条模型断言，1000 个普通帧无累积延迟；实际 GameEnv 图像、窗口呈现计数和三个主循环仍待验收，见[显示时序实现与验证](../reports/optimization-native-presentation-owner-2026-09-13.md)。

2026-09-13 最新：共享输入／调度／展示已接入三个正式入口，并修复真实服务器丢弃提前输入的问题。实际 TCP／UDP 各确认 35 帧，均含移动、冲刺和短按射门；途中保存前缀保持一致，Release／ASan 实际重放 70 帧的全部哈希通过。详见[原生入口与权威输入集成](../reports/optimization-native-runtime-integration-2026-09-13.md)。当前 10Hz、50ms 手感目标、完整故障矩阵及正式门禁刷新仍待完成；源码变更使前置证据过期，状态不提升。

2026-09-13 正式输入检查器已注册并完成首次独立执行：2150639 条断言、零跳过，包含 Release／ASan 真实 SDL 采样与 GameEnv、三个产品窗口和 67 个确认帧的逐帧重放。固定 CMake 测试目标引用当前源码；详细范围、工具条件与前置状态见[输入验收入口报告](../reports/optimization-input-gate-2026-09-13.md)。完整前置质量链尚未执行，任务状态不提升。

2026-09-13 产品节拍：Python比赛已升级v7／50Hz，每帧2×10ms物理步，场景时长及AI接管冷却按模拟时间换算；checkpoint v3和回放显式验证节拍。当前Release核心上402项比赛／图形、123项旧接口回归均通过，零跳过；并修复实际运行库身份记录错误。见[50Hz实施报告](../reports/optimization-product-cadence-v7-2026-09-13.md)。原生v2入口、真实延迟、完整前置验收仍待推进，状态不提升。

2026-09-13 原生50Hz实施：三个产品入口已接入FNAT1与带节拍的回放，修复追帧后发送、TCP小包延迟及可靠UDP重复交付；完整输入门禁2419961条断言、零跳过，234个真实确认帧在Release／ASan中全部重放通过。双客户端TCP／UDP、88项数据报／文件测试及旧TCP重连回归通过。见[原生50Hz实现与证据](../reports/optimization-native-product-cadence-2026-09-13.md)。设备响应、持续输入、完整弱网与前置质量链仍待验收，状态不手动提升。


2026-09-13 硬件渲染调查：实际 Intel Arc／D3D12 已完成 1080p 引擎帧和状态／图像对照，但重复初始化暴露可独立复现的 Mesa slab 自身死锁。隔离源码修复正在构建验证；成功样本 p95 仍为 18.948–24.990ms，不能提升产品质量状态。见[硬件渲染与驱动定位](../reports/optimization-native-hardware-rendering-2026-09-13.md)。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。


2026-09-13 正式帧捕获策略已实现；Release 软件/GPU 各 169 条实际断言通过，Sanitizer 编译进行中，无头边界及固定验收接入待完成。见 [实现与验证进度](../reports/optimization-native-frame-capture-2026-09-13.md)，保留未通过状态。


2026-09-13 捕获策略第二次复核：已补齐 GameEnv 无头边界与固定 input_contract 接入；Release 软件/GPU、Sanitizer 软件各 174 条断言通过，原有骨骼/卡片双构建回归通过。首次 GPU Sanitizer 初始化失败及独立 D3D12 复现保留，完整固定输入验收运行中。详见 [当前实现证据](../reports/optimization-native-frame-capture-2026-09-13.md)，不提升产品验收状态。


2026-09-13 最新固定输入验收失败于软件 UDP 恢复再次按键：权威帧 442–447 中性，第 448 帧在约 342.668ms 响应，保留未通过。独立 GPU 三模式全部功能检查通过，1,194 次渲染无产品 RGB 回读；Python 软件/GPU 各 23 条断言通过。真实两轮回放交叉验证运行中，见 [最新证据](../reports/optimization-native-frame-capture-2026-09-13.md)。


2026-09-13 本轮最终复核：十文件捕获优化、默认 Python API 和 GPU 三模式功能检查完成，1,194 次渲染无产品回读；2,050 个真实权威帧在 Release 与 Sanitizer 分别回放通过。完整固定输入仍失败于软件 UDP 恢复延迟，GPU Sanitizer 初始化及渲染 p95 仍未达标，保持未通过。见 [最终实现与证据](../reports/optimization-native-frame-capture-2026-09-13.md)。
