## 2026-09-24 提交快照：权威时钟校正的七项正式验收通过

native-input-authority-resync-adoption-20260924-b 已终止，exit 0。当前 1138 项源码清单及 4 个采纳文件哈希均已复核一致。quality_selftest、input_contract、framework_regression、tactical_integration、ai_decisions、native_boundary、native_session_ports 全部通过，七份正式日志的 SHA-256 已逐一复核。本次提交包含时钟修复、两个永久回归测试、旧实现反例夹具、框架计数及对应文档与验收证据。

输入验收为 42 项结果、3067495 个断言，Release/full Debug 各独立回放 1021 个真实记录帧；框架覆盖 773 项 C++ 和 783 项 Python 测试。未修改原门禁时限或断言。

原生控制会话私有集成 A 已进入构建验证；帧线程暂停/ACK 私有候选仍在准备，均不属于本次正式代码。后台队列继续串行运行，正式源码仍冻结至控制会话 A 终止。原 UDP 中立帧根因、架构 RSS 失败及其余产品缺口尚未关闭，整体产品验收仍为 false，目标保持 ACTIVE。下方条目为历史记录，状态以本快照为准。

2026-09-24 当前 1138 项源码清单：正式 input_contract 已通过，42 项结果、3067495 个断言，Release/full Debug 各独立回放 1021 个真实记录帧；87 份命令日志及报告哈希已核对，真实窗口和双构建 56 项采样器检查通过，X11 已回收。正式 framework_regression 随后通过，包含新增回归后的 773 项 C++ 要求。当前继续战术、AI、边界和端口验收，尚非全部门禁通过；原 UDP 中立帧根因仍未证实。输入验证文件在 native-input-authority-resync-adoption-20260924-b/input-verification.json。

2026-09-24 已正式采纳权威时钟校正：runtime C 三轮原始窗口套件全部通过，共 9 个 standalone/TCP/UDP 场景；持续输入、释放、失焦、控制暂停及重新按键断言全部保留，私有 X11 均回收。TCP 候选双构建共 4 个真实客户端通过；复用的 UDP 候选此前双构建共 4 个真实客户端通过。每个会话 100 个确认帧、10 次哈希核验；窗口产品场景为 Release，键盘采样器另覆盖完整 Debug Sanitizer。runtime C 的 9 份命令日志已核对。

adoption B 已接入 4 文件：NativePublicationClock 校正适用于多帧提前、原 RTT 测试增至 14 项、冻结旧实现反例夹具、框架最低计数升至 773。当前源码清单 1138 项，sources-after.json 及 adopted-files.json 在 native-input-authority-resync-adoption-20260924-b；正式 quality_selftest 已通过，input_contract 正在执行，随后串行 framework_regression、tactical_integration、ai_decisions、native_boundary、native_session_ports。执行期间冻结当前源码及程序配置。正式门禁尚未全部完成；原始 UDP 中立帧未在三轮抓取复现，根因仍未证实，不能仅靠本次候选窗口通过关闭该问题。

2026-09-24 更新：私有候选 runtime A 的双构建 UDP 真实会话通过；窗口第 0、2 轮通过，第 1 轮在尚未替换的 TCP 路径失败（暂停后 315.8～385.9 ms 仍有方向/冲刺，411.7 ms 起清空）。所有 9 份命令日志已核对；采纳 A 因依赖失败在修改正式源码前终止。该 TCP 症状保留为未关闭证据，不能据此声称 UDP 已覆盖所有产品场景。

永久回归候选现保留原 12 项并新增 2 项（旧时钟提前量漂移反例、25 种权威节奏/预算组合的连续帧约束）。regressions A 因驱动错误地将动态 status.json 纳入固定输入而失败；新建 regressions B 只固定真正输入，Release/full Debug 下 25 个独立模型及全部 14 项 RTT 测试通过，8 份日志已核对。框架最低计数候选为 773，原断言均保留。runtime B 在依赖检查失败，未编译；已执行输入未修改。

当前 runtime C（PID 2902866 / start_ticks 70362401）编译私有 TCP 候选并复用已固定的 runtime A UDP 候选，验证双构建 TCP 真实会话和三轮 TCP/UDP 都使用候选的原窗口套件。adoption B（PID 2902867 / start_ticks 70362401）仅排队，要求 runtime C、regressions B 全通过且日志哈希吻合后，才采纳时钟、测试、冻结反例夹具、框架计数 4 文件，串行重验 quality/input/framework/tactical/AI/boundary/ports 七项正式门禁。当前正式源码仍 1137 项且冻结；原 UDP 持续输入空帧、架构 RSS 和其余产品缺口仍未关闭。

# 原生输入提前量随权威节奏校正

归属：ms-22.1 → plan-22.1.1 → task-22.1.1.1；关联 ms-23.1。当前仅为已验证模型及私有实际客户端候选，未采纳正式源码，也未关闭原输入失败。

## 实际证据

最新 input_contract 的原始失败是 UDP 持续按住方向及冲刺时出现一个中立权威步骤。native-input-wire-diagnosis-20260924-b 在当前产品上执行三轮原窗口动作，三轮均未重现持续按键空帧，但前两轮出现恢复后重新按键生效过晚。全部断言、超时及私有 X11 回收要求保留。六份诊断命令日志哈希已核对。

第一轮的网络消息记录显示：恢复后 30.831 ms 已发出方向和冲刺，目标网络帧 444，到 297.392 ms 才看到该权威帧。此时发布目标相对观察器最近权威计数提前 12～13 帧，原帧 440～443 已发布为中立，不能重写。原始消息、相邻记录和哈希见 native-input-failure-review-20260924-b/rearm-wire-proof.json。本机观察器增加转发开销，这些时间不能当作硬件手感验收；观察时间也不等于客户端接收时间，不能据此断言精确 RTT 预算。

## 独立反例和候选

NativePublicationClock 原实现只有单帧提前模式在收到新权威时校正本地发送时钟。多帧提前模式若继续按本机 20 ms 周期发布，而权威按 21 ms 周期前进，预设的 2 帧提前量会增长到接收窗口上限附近的 15 帧。

私有候选将同一校正用于全部提前模式：当新权威推进且对应目标已发布时，重设下一发送机会。保留已经发送的输入、连续帧填补、16 帧服务端窗口、恢复重定位与一次性采样。25 个独立模型组合覆盖 20/21/22/24/28 ms 权威节奏和 2/3/5/10/15 帧预算，各模拟 40 秒并检查严格递增、连续和接收窗口。21 ms / 2 帧反例从原最大 15 帧降为最大 3 帧，仍发布 1905 帧。Release 和完整 Debug ASan/UBSan 均通过，原有 12 项 RTT 测试也全部通过；8 份命令日志已核对。证据：native-input-authority-resync-20260924-a。

## 正在执行

native-input-authority-resync-runtime-20260924-a 已在前置进程终止后串行启动，基于当前正式编译配方构建私有 Release/full Debug UDP 客户端，随后执行两种构建的真实端口会话和三轮不经过转发观察器的原窗口套件。所有正式源码、已编译依赖及执行输入固定。真实窗口结果、原始中立帧根因、正式输入与框架等相关门禁均待验证。
