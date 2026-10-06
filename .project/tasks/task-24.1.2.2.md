# task-24.1.2.2 — 渲染性能验收

2026-10-06 FXAA 零方向提前返回候选在两个画质模式、各五帧的 RGB／状态逐字节一致，但真实窗口双种子两轮交错 A/B 中种子 43 均变慢，八次完整帧均超预算。候选未合入，任务继续未完成；见[候选原始证据](../optimization/evidence/fxaa_zero_dir_20261006.json)。

2026-10-06 前五个里程碑重新验证后，当前源码的正式 Wayland／D3D12 1080p 完整 PBR 检查仍失败：种子 42/43 p95 为 26.618/25.863 ms，超过 16.67 ms；503 项断言、零跳过。见[当前正式报告与原始样本](../optimization/evidence/render_gpu_after_ai_refresh_20261006.json)。本任务保持未完成。

2026-10-06 FXAA 的 `texelFetch` 与 `textureOffset` 邻域采样候选分别在固定五帧中改变 1,678–2,407 和 4–42 个像素；虽未改变模拟状态，但未通过精确图像门禁，均未合入或进入性能验收。见[补丁和逐帧证据](../optimization/diagnostics/fxaa-sampling-20261006/report.json)。

2026-10-06 直接启用未使用的 GL 状态缓存，在隔离的紧凑 Bloom 条件下保持五帧 RGB/状态一致，但八次双种子真实窗口 A/B 无稳定收益，且未覆盖外部 GL 状态失效，未合入。交换调用逐帧计时显示大部分墙钟可位于交换阶段，同时出现 66–143ms 的运行间异常；不能把交换时间归因于合成器，也不能据此完成验收。见[完整诊断与失败证据](../optimization/render-presentation-20261006.md)。

2026-10-06 Bloom 中间纹理改为 R11G11B10F 的八次真实窗口 A/B 无稳定性能收益，五帧精确图像有 0–151 个像素差异，未合入。随后 540p／720p／1080p 各两种子两轮的完整画质测量确认 GPU 与额外墙钟时间都随分辨率增长；1080p p95 为 26.683–40.500ms，门禁仍未通过。见[候选与分辨率诊断](../optimization/render-presentation-20261006.md)。

2026-10-06 原 PBR 通道的九点 GPU 时间戳显示，本机完整 1080p 帧中 Bloom 提取 p95 为 2.097–2.884ms、FXAA 为 1.311–3.670ms，提供下一轮等画质优化优先级；四次墙钟 p95 为 25.223–28.673ms，任务仍未通过。见[阶段时间戳与原始证据](../optimization/render-presentation-20261006.md)。

2026-10-06 单盏方向光合并 IBL 与直接光照的隔离候选通过编译及实际画面捕获，但双种子两轮真实窗口 A/B 中仅种子 42 变快，种子 43 变慢，八次完整帧 p95 均高于 16.67ms；固定五帧每帧仍有 6,050–6,689 像素差异。补丁未合入主线，任务与里程碑继续未通过。见[渲染瓶颈与候选证据](../optimization/render-presentation-20261006.md)。

2026-10-03 分段 GPU 探针在隔离副本中显示几何与直接光照各约 5ms 均值，但强制同步会抬高整帧，不是正式性能通过；背光像素提前返回候选的双种子交错对照无稳定收益，未采纳。Wayland 后端在当前 SDL 构建不可用。见[分段诊断](../reports/optimization-render-stage-training-2026-10-03.md)。

2026-10-03 当前源码正式双种子 1080p PBR 复验失败：未选硬件时 llvmpipe p95 为 258.225/220.760ms；显式选 Intel Arc 140T 私有 D3D12 驱动后 p95 为 32.619/31.921ms，仍超 16.67ms。隔离诊断将主要等待定位到图形任务的交换/呈现阶段，EGL 对照亦无收益；尚未形成产品修复；任务继续未通过。见[本轮复验与诊断](../reports/optimization-smoothing-network-render-2026-10-03.md)。

2026-10-02 连续比赛双种子复核：正式基准新增显式私有 D3D12 驱动选择及实际加载库路径核对。Intel Arc 140T 上种子 42／43 的 1080p 完整 PBR p95 分别为 139.290／41.285ms，均超过 16.67ms，任务继续未通过。见[驱动身份与预算复核](../reports/optimization-render-budget-driver-2026-10-02.md)。

2026-09-28 环境光采样复用原型：候选与基线的固定画面和模拟状态一致，但两组交错真实窗口比较未显示稳定的无探针 p95 收益，且基线及 PBR 对照波动大；正式着色器已恢复，不采用原型。见[环境光原型实测](../reports/optimization-ambient-shader-trial-2026-09-28.md)，`render_regression` 继续 `ready:false`。

2026-09-28 当前源码 1080p GPU 预检：实际 Intel Arc 140T/D3D12 私有修复驱动上，关闭未消费 RGB 回读的离屏 Legacy 两轮 p95 为 14.98/13.85ms、PBR 完整效果为 11.11/10.64ms；相同源码的真实 SDL 窗口分别为 31.88/28.84ms 和 23.76/24.01ms，均未达到 16.67ms。交换入口占带探针整帧平均约 81%–86%，但包含已排队 GPU 工作；GLX/EGL 请求对照没有稳定收益，不采纳。PBR 离屏/窗口五帧 RGB 相同，Legacy 存在明显亮度差异待定位。四阶段原始样本与终态核验已存档，`render_regression` 保持 `ready:false`，任务和里程碑不提升。见 [当前硬件预检报告](../reports/optimization-current-gpu-1080-2026-09-28.md)。


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
