2026-09-24 提交快照：权威时钟校正 adoption B 已终止且七项正式门禁全部通过，七份日志哈希已复核；详细结果见 optimization-native-authority-resync-2026-09-24.md。原生控制会话私有集成 A 正在串行验证，未采纳为正式暂停功能。原 UDP 中立帧根因及整体产品缺口仍未关闭。以下保留历史阶段记录。

2026-09-24 已正式采纳权威时钟校正：runtime C 三轮原始窗口套件全部通过，共 9 个 standalone/TCP/UDP 场景；持续输入、释放、失焦、控制暂停及重新按键断言全部保留，私有 X11 均回收。TCP 候选双构建共 4 个真实客户端通过；复用的 UDP 候选此前双构建共 4 个真实客户端通过。每个会话 100 个确认帧、10 次哈希核验；窗口产品场景为 Release，键盘采样器另覆盖完整 Debug Sanitizer。runtime C 的 9 份命令日志已核对。

adoption B 已接入 4 文件：NativePublicationClock 校正适用于多帧提前、原 RTT 测试增至 14 项、冻结旧实现反例夹具、框架最低计数升至 773。当前源码清单 1138 项，sources-after.json 及 adopted-files.json 在 native-input-authority-resync-adoption-20260924-b；正式 quality_selftest 已通过，input_contract 正在执行，随后串行 framework_regression、tactical_integration、ai_decisions、native_boundary、native_session_ports。执行期间冻结当前源码及程序配置。正式门禁尚未全部完成；原始 UDP 中立帧未在三轮抓取复现，根因仍未证实，不能仅靠本次候选窗口通过关闭该问题。

2026-09-24 更新：私有候选 runtime A 的双构建 UDP 真实会话通过；窗口第 0、2 轮通过，第 1 轮在尚未替换的 TCP 路径失败（暂停后 315.8～385.9 ms 仍有方向/冲刺，411.7 ms 起清空）。所有 9 份命令日志已核对；采纳 A 因依赖失败在修改正式源码前终止。该 TCP 症状保留为未关闭证据，不能据此声称 UDP 已覆盖所有产品场景。

永久回归候选现保留原 12 项并新增 2 项（旧时钟提前量漂移反例、25 种权威节奏/预算组合的连续帧约束）。regressions A 因驱动错误地将动态 status.json 纳入固定输入而失败；新建 regressions B 只固定真正输入，Release/full Debug 下 25 个独立模型及全部 14 项 RTT 测试通过，8 份日志已核对。框架最低计数候选为 773，原断言均保留。runtime B 在依赖检查失败，未编译；已执行输入未修改。

当前 runtime C（PID 2902866 / start_ticks 70362401）编译私有 TCP 候选并复用已固定的 runtime A UDP 候选，验证双构建 TCP 真实会话和三轮 TCP/UDP 都使用候选的原窗口套件。adoption B（PID 2902867 / start_ticks 70362401）仅排队，要求 runtime C、regressions B 全通过且日志哈希吻合后，才采纳时钟、测试、冻结反例夹具、框架计数 4 文件，串行重验 quality/input/framework/tactical/AI/boundary/ports 七项正式门禁。当前正式源码仍 1137 项且冻结；原 UDP 持续输入空帧、架构 RSS 和其余产品缺口仍未关闭。

2026-09-24 更新：连续输入修复正式门禁已通过 42 项结果、3070762 个断言，TCP/UDP 共 1030 个记录帧在两种构建独立回放。证据来自 native-input-contiguous-adoption-20260924-a。之后战术检查器源码发生变更，native-control-fragment-adoption-20260924-a 已排新一轮完整 input_contract；此前通过不自动覆盖新清单。以下为历史记录。

# plan-22.1.1 — 输入闭环

2026-09-24 UDP 输入缺口已取得发送端证据并修复调度：真实抓包中输入帧 205 后直接出现 207，206 为权威空帧；旧算法对照复现，连续未来帧发布修复在两种构建中各通过 11,011 条断言及 12 项 RTT 测试。正式源码现为 1135 项，完整输入、框架、战术、AI 和原生边界门禁串行重验中。见[实现与证据](../reports/optimization-native-input-continuity-2026-09-24.md)，状态未提升。

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-22.1.1.1、task-22.1.1.2

验收检查：input_contract、fixed_timestep

执行：`python3 .project/quality.py run plan-22.1.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

2026-09-13：已完成当前采样器的实际 SDL/X11 预检，56 条断言通过；原生入口统一提交、固定节拍升级及球员响应延迟验收仍待完成。见[输入采样证据](../reports/optimization-native-input-sampler-2026-09-13.md)。

2026-09-13：共享原生输入缓冲的独立实现已通过 20,168 次真实 Python 状态操作差分，Release 与 ASan/UBSan 各 92,699 条断言。下一步需接入三个入口，并在权威追帧后按实际帧号缓存／提交本地输入，避免短按在等待或回滚时被重复消费。见[共享缓冲验证](../reports/optimization-native-input-buffer-2026-09-13.md)。

2026-09-13 帧绑定实现：独立目录中的输入供应回调及 1024 帧有界历史已通过 Release／ASan+UBSan 各 16248 条断言，包含实际 FrameSimulation 追帧、等待、快照预算恢复导致的帧号回退和 2000 权威帧旧算法对照。三个入口、GameEnv 和实际 socket 尚未接入验证，见[帧绑定实现与证据](../reports/optimization-native-input-admission-2026-09-13.md)。

2026-09-13 产品节拍：Python比赛已升级v7／50Hz，每帧2×10ms物理步，场景时长及AI接管冷却按模拟时间换算；checkpoint v3和回放显式验证节拍。当前Release核心上402项比赛／图形、123项旧接口回归均通过，零跳过；并修复实际运行库身份记录错误。见[50Hz实施报告](../reports/optimization-product-cadence-v7-2026-09-13.md)。原生v2入口、真实延迟、完整前置验收仍待推进，状态不提升。

2026-09-13 原生50Hz实施：三个产品入口已接入FNAT1与带节拍的回放，修复追帧后发送、TCP小包延迟及可靠UDP重复交付；完整输入门禁2419961条断言、零跳过，234个真实确认帧在Release／ASan中全部重放通过。双客户端TCP／UDP、88项数据报／文件测试及旧TCP重连回归通过。见[原生50Hz实现与证据](../reports/optimization-native-product-cadence-2026-09-13.md)。设备响应、持续输入、完整弱网与前置质量链仍待验收，状态不手动提升。

2026-09-13 比赛进行中实测与修复：本地保留固定步长欠帧、客户端优先追赶已收权威帧；完整输入回归2518183条断言、零跳过，三个实际进行中窗口通过。持续输入仍有空档，50ms响应与正式依赖链尚未验收。详见[进行中节拍报告](../reports/optimization-native-inplay-cadence-2026-09-13.md)。

2026-09-13 持续输入实施：网络工作线程、同步输入及单份有界发布历史已接入原生入口。加强后的固定输入门禁2584154条断言、零跳过，实际TCP／UDP持续输入区间零空档，1024个确认帧全部逐帧重放通过；并发组件在Release／ASan／TSan均通过。采样与释放延迟、权威暂停和完整依赖链仍未完成，详见[持续输入实现与证据](../reports/optimization-native-continuous-input-2026-09-13.md)。

2026-09-13 渲染期间采样：三个原生入口已接入主线程协作采样，当前固定输入门禁2625238条断言、1030个确认帧在Release／ASan逐帧重放通过；新组件TSan及实际画面回归通过。分段实测采样等待缩短，但本地应用约73–76ms，追帧短按、服务器接收空档及单次绘制阻塞仍未解决。详见[渲染采样实现与实测](../reports/optimization-native-render-input-service-2026-09-13.md)。完整前置链仍为过期，状态不提升。

2026-09-13 本地输入时间归属：已按原始固定截止时间消费带时间的有界观察，避免当前按键回填过去帧；当前固定输入门禁2773304条断言、1030个确认帧在Release／ASan逐帧重放通过，真实引擎903个对照帧状态逐字节相同。50ms产品延迟、网络接收空档和GL阻塞仍未完成，详见[本地输入时间归属报告](../reports/optimization-native-input-timeline-2026-09-13.md)。状态仍由完整质量链计算，不手动提升。


2026-09-13 接纳链路与线程职责：真实 TCP／UDP 的接收、接纳、封帧与实际引擎输入已逐帧对应，1036 个确认帧在 Release／ASan 全部重放通过；受控分片、重复、乱序、迟到、超窗与冲突契约通过。主线程采样原型在真实窗口中记录 p95 7.097ms、最大15.758ms采样间隔，尚未正式接入三个入口或完成线程／异常契约；实际55.897ms响应未达标。详见[本轮报告](../reports/optimization-native-admission-ui-owner-2026-09-13.md)。不提升整体状态。


2026-09-13 主线程采样实施：三个正式入口已接入窗口／游戏线程职责分离，Release／ASan／TSan 并发合同及真实线程观测通过，1035 个确认帧在 Release／ASan 全部重放通过。固定门禁 B 仍因 TCP 第 138 帧持续输入空档失败；后续观测又发现批量接收后未发布 505、506 帧，不能宣称网络或 50ms 手感达标。详见[实现、失败及下一步](../reports/optimization-native-main-ui-owner-2026-09-13.md)。状态不手动提升。


2026-09-13 独立发布节拍：已在真实 TCP／UDP 复现批量接收导致的发布空档，并接入有界 50Hz 发布时钟。当前完整输入检查 2,984,826 条断言、零跳过；正式构建的 100ms 权威暂缓期间各连续发送 5 帧，持续输入零空档。两个当前批次共 2056 个确认帧在 Release／ASan 全部逐帧重放一致。50ms 手感、完整弱网与前置质量链仍未完成，详见[实现与验证](../reports/optimization-native-publication-clock-2026-09-13.md)。不手动提升整体状态。


2026-09-13 发布提前量和 AI 接管合法无选中状态已完成现场定位、原型对照与正式接入，固定验收仍待终态。见 [本轮实现](../reports/optimization-native-publication-bot-recovery-2026-09-13.md)，不手动提升计划状态。


2026-09-13 本轮终态：发布校准与 AI 死球恢复已正式接入；32 项组件/采样检查共 2,080,418 条断言通过，四项真实 TCP 会话回归通过。正式 100ms 暂缓与退出后 250 帧 AI 场景通过，2,061 个确认帧在 Release/ASan 分别重放一致。完整固定输入仍失败于 UDP 第 200、201 帧缺口，未提升状态；见 [最终实现与限制](../reports/optimization-native-publication-bot-recovery-2026-09-13.md)。
