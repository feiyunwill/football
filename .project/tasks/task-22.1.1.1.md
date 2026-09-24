2026-09-24 更新：连续输入修复正式门禁已通过 42 项结果、3070762 个断言，TCP/UDP 共 1030 个记录帧在两种构建独立回放。证据来自 native-input-contiguous-adoption-20260924-a。之后战术检查器源码发生变更，native-control-fragment-adoption-20260924-a 已排新一轮完整 input_contract；此前通过不自动覆盖新清单。以下为历史记录。

# task-22.1.1.1 — 统一输入采样

2026-09-24 UDP 输入缺口已取得发送端证据并修复调度：真实抓包中输入帧 205 后直接出现 207，206 为权威空帧；旧算法对照复现，连续未来帧发布修复在两种构建中各通过 11,011 条断言及 12 项 RTT 测试。正式源码现为 1135 项，完整输入、框架、战术、AI 和原生边界门禁串行重验中。见[实现与证据](../reports/optimization-native-input-continuity-2026-09-24.md)，状态未提升。

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 键盘/控制器方向归一化、死区、按钮按下/释放和同时按键一致

依赖：ms-21.1

执行顺序：无

验收检查：input_contract

执行：`python3 .project/quality.py run task-22.1.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

局部实施（2026-09-10；依赖 ms21 和正式验收仍未通过）：

- [图形输入与比赛协调](../reports/optimization-graphical-match-progress-2026-09-10.md)：归一化、径向死区、动作按住/短按/释放、失焦和手柄断连；9 项输入合同及 14 项实际 socket/文件/菜单/显示模型集成回归通过。新增 C++ SDL 绑定未编译，真实设备驱动、焦点和延迟仍待验证，不能标记 input_contract 完成。

2026-09-13 新增只读输入审查：原生本地入口存在空闲不释放方向、粘性按钮未释放、同时按键仅提交首项的问题；Python 输入 API 只在绑定类封装。后续实现与实际 SDL／球员响应验收见[原生展示与输入审查](../reports/optimization-native-presentation-review-2026-09-13.md)。

2026-09-13 实际原生预检：当前 SDL 采样器在私有 X11 窗口中通过 56 条断言、零跳过，覆盖真实 XTEST 键盘短按／持续／释放、SDL 虚拟手柄、焦点转移及断连。已保留两次焦点驱动失败，并验证私有 X 服务回收及父环境不变。尚未调用 GameEnv 或验证球员延迟，输入门禁仍未完成，见[实际采样证据](../reports/optimization-native-input-sampler-2026-09-13.md)。

2026-09-13 共享缓冲实现：独立目录中的 C++ NativeInputBuffer 已通过现有 Python 实现的 20,168 次固定状态操作对照；Release／ASan+UBSan 各 92,699 条断言，float32 序列化位与全部按钮状态一致。包含短按缓存、持续／释放、死区、失焦、断连和恢复屏障。尚未替换三个入口或执行实际球员响应检查，见[实现与差分证据](../reports/optimization-native-input-buffer-2026-09-13.md)。

2026-09-13 帧绑定实现：独立目录中的输入供应回调及 1024 帧有界历史已通过 Release／ASan+UBSan 各 16248 条断言，包含实际 FrameSimulation 追帧、等待、快照预算恢复导致的帧号回退和 2000 权威帧旧算法对照。三个入口、GameEnv 和实际 socket 尚未接入验证，见[帧绑定实现与证据](../reports/optimization-native-input-admission-2026-09-13.md)。

2026-09-13 后续实现：已在独立目录加入 TCP／UDP 的 tick_buffered 入口，使用按确认淘汰的有界历史，让首次发送与预测共用真实帧号及完整输入；UDP 发送失败现在可由该调用者处理。尚未编译、验证实际 socket 或替换主循环，见[当前实现范围与后续验证](../optimization/benchmarks/native-network-input-20260913-a/README.md)。

2026-09-13 最新：共享缓冲／输入历史通过真实 GameEnv 集成，Release 与 ASan／UBSan 各 3901 条断言、82 个权威帧、74 次纠正回滚，详见[实际输入报告](../reports/optimization-native-input-gameenv-2026-09-13.md)。仍为独立阶段，套接字、三个产品入口和实际设备／延迟验收尚待完成。

2026-09-13 最新：真实 TCP 套接字、客户端缓存输入与权威 GameEnv 已通过 Release／ASan／UBSan 各四组场景，逐帧哈希与唯一发送一致，见[TCP 输入局部验收](../reports/optimization-native-tcp-input-2026-09-13.md)。产品服务器、UDP、产品主循环和完整网络条件仍待验收，任务不提升为整体完成。

2026-09-13 最新：共享输入／调度／展示已接入三个正式入口，并修复真实服务器丢弃提前输入的问题。实际 TCP／UDP 各确认 35 帧，均含移动、冲刺和短按射门；途中保存前缀保持一致，Release／ASan 实际重放 70 帧的全部哈希通过。详见[原生入口与权威输入集成](../reports/optimization-native-runtime-integration-2026-09-13.md)。当前 10Hz、50ms 手感目标、完整故障矩阵及正式门禁刷新仍待完成；源码变更使前置证据过期，状态不提升。

2026-09-13 正式输入检查器已注册并完成首次独立执行：2150639 条断言、零跳过，包含 Release／ASan 真实 SDL 采样与 GameEnv、三个产品窗口和 67 个确认帧的逐帧重放。固定 CMake 测试目标引用当前源码；详细范围、工具条件与前置状态见[输入验收入口报告](../reports/optimization-input-gate-2026-09-13.md)。完整前置质量链尚未执行，任务状态不提升。

2026-09-13 原生50Hz实施：三个产品入口已接入FNAT1与带节拍的回放，修复追帧后发送、TCP小包延迟及可靠UDP重复交付；完整输入门禁2419961条断言、零跳过，234个真实确认帧在Release／ASan中全部重放通过。双客户端TCP／UDP、88项数据报／文件测试及旧TCP重连回归通过。见[原生50Hz实现与证据](../reports/optimization-native-product-cadence-2026-09-13.md)。设备响应、持续输入、完整弱网与前置质量链仍待验收，状态不手动提升。

2026-09-13 比赛进行中实测与修复：本地保留固定步长欠帧、客户端优先追赶已收权威帧；完整输入回归2518183条断言、零跳过，三个实际进行中窗口通过。持续输入仍有空档，50ms响应与正式依赖链尚未验收。详见[进行中节拍报告](../reports/optimization-native-inplay-cadence-2026-09-13.md)。

2026-09-13 持续输入实施：网络工作线程、同步输入及单份有界发布历史已接入原生入口。加强后的固定输入门禁2584154条断言、零跳过，实际TCP／UDP持续输入区间零空档，1024个确认帧全部逐帧重放通过；并发组件在Release／ASan／TSan均通过。采样与释放延迟、权威暂停和完整依赖链仍未完成，详见[持续输入实现与证据](../reports/optimization-native-continuous-input-2026-09-13.md)。

2026-09-13 渲染期间采样：三个原生入口已接入主线程协作采样，当前固定输入门禁2625238条断言、1030个确认帧在Release／ASan逐帧重放通过；新组件TSan及实际画面回归通过。分段实测采样等待缩短，但本地应用约73–76ms，追帧短按、服务器接收空档及单次绘制阻塞仍未解决。详见[渲染采样实现与实测](../reports/optimization-native-render-input-service-2026-09-13.md)。完整前置链仍为过期，状态不提升。

2026-09-13 本地输入时间归属：已按原始固定截止时间消费带时间的有界观察，避免当前按键回填过去帧；当前固定输入门禁2773304条断言、1030个确认帧在Release／ASan逐帧重放通过，真实引擎903个对照帧状态逐字节相同。50ms产品延迟、网络接收空档和GL阻塞仍未完成，详见[本地输入时间归属报告](../reports/optimization-native-input-timeline-2026-09-13.md)。状态仍由完整质量链计算，不手动提升。


2026-09-13 接纳链路与线程职责：真实 TCP／UDP 的接收、接纳、封帧与实际引擎输入已逐帧对应，1036 个确认帧在 Release／ASan 全部重放通过；受控分片、重复、乱序、迟到、超窗与冲突契约通过。主线程采样原型在真实窗口中记录 p95 7.097ms、最大15.758ms采样间隔，尚未正式接入三个入口或完成线程／异常契约；实际55.897ms响应未达标。详见[本轮报告](../reports/optimization-native-admission-ui-owner-2026-09-13.md)。不提升整体状态。


2026-09-13 主线程采样实施：三个正式入口已接入窗口／游戏线程职责分离，Release／ASan／TSan 并发合同及真实线程观测通过，1035 个确认帧在 Release／ASan 全部重放通过。固定门禁 B 仍因 TCP 第 138 帧持续输入空档失败；后续观测又发现批量接收后未发布 505、506 帧，不能宣称网络或 50ms 手感达标。详见[实现、失败及下一步](../reports/optimization-native-main-ui-owner-2026-09-13.md)。状态不手动提升。


2026-09-13 独立发布节拍：已在真实 TCP／UDP 复现批量接收导致的发布空档，并接入有界 50Hz 发布时钟。当前完整输入检查 2,984,826 条断言、零跳过；正式构建的 100ms 权威暂缓期间各连续发送 5 帧，持续输入零空档。两个当前批次共 2056 个确认帧在 Release／ASan 全部逐帧重放一致。50ms 手感、完整弱网与前置质量链仍未完成，详见[实现与验证](../reports/optimization-native-publication-clock-2026-09-13.md)。不手动提升整体状态。


2026-09-13 GPU 运行复核：私有 Mesa 修复通过 15,000 次纹理操作与六次真实引擎启动；实际三模式窗口及 1,029 帧双构建回放通过。另轮 TCP 第 203 帧持续输入空档保留失败。RGB 回读 ABBA 改善平均耗时但 p95 未达标，正式捕获策略待实现。详见 [实测与后续任务](../reports/optimization-native-gpu-runtime-2026-09-13.md)，不提升验收状态。


2026-09-13 捕获策略第二次复核：已补齐 GameEnv 无头边界与固定 input_contract 接入；Release 软件/GPU、Sanitizer 软件各 174 条断言通过，原有骨骼/卡片双构建回归通过。首次 GPU Sanitizer 初始化失败及独立 D3D12 复现保留，完整固定输入验收运行中。详见 [当前实现证据](../reports/optimization-native-frame-capture-2026-09-13.md)，不提升产品验收状态。


2026-09-13 最新固定输入验收失败于软件 UDP 恢复再次按键：权威帧 442–447 中性，第 448 帧在约 342.668ms 响应，保留未通过。独立 GPU 三模式全部功能检查通过，1,194 次渲染无产品 RGB 回读；Python 软件/GPU 各 23 条断言通过。真实两轮回放交叉验证运行中，见 [最新证据](../reports/optimization-native-frame-capture-2026-09-13.md)。


2026-09-13 本轮最终复核：十文件捕获优化、默认 Python API 和 GPU 三模式功能检查完成，1,194 次渲染无产品回读；2,050 个真实权威帧在 Release 与 Sanitizer 分别回放通过。完整固定输入仍失败于软件 UDP 恢复延迟，GPU Sanitizer 初始化及渲染 p95 仍未达标，保持未通过。见 [最终实现与证据](../reports/optimization-native-frame-capture-2026-09-13.md)。


2026-09-13 最新：发布校准与真实无选中球员状态的 AI 接管修复已接入，确定性旧实现失败/候选通过及实际 100ms 暂缓、退出后 250 帧组合场景完成。正式固定验收正在执行，状态不提升；见 [实现与证据](../reports/optimization-native-publication-bot-recovery-2026-09-13.md)。


2026-09-13 本轮终态：发布校准与 AI 死球恢复已正式接入；32 项组件/采样检查共 2,080,418 条断言通过，四项真实 TCP 会话回归通过。正式 100ms 暂缓与退出后 250 帧 AI 场景通过，2,061 个确认帧在 Release/ASan 分别重放一致。完整固定输入仍失败于 UDP 第 200、201 帧缺口，未提升状态；见 [最终实现与限制](../reports/optimization-native-publication-bot-recovery-2026-09-13.md)。
