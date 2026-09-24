2026-09-24 提交快照：权威时钟校正 adoption B 已终止且七项正式门禁全部通过，七份日志哈希已复核；详细结果见 optimization-native-authority-resync-2026-09-24.md。原生控制会话私有集成 A 正在串行验证，未采纳为正式暂停功能。原 UDP 中立帧根因及整体产品缺口仍未关闭。以下保留历史阶段记录。

2026-09-24 当前 1138 项源码清单：正式 input_contract 已通过，42 项结果、3067495 个断言，Release/full Debug 各独立回放 1021 个真实记录帧；87 份命令日志及报告哈希已核对，真实窗口和双构建 56 项采样器检查通过，X11 已回收。正式 framework_regression 随后通过，包含新增回归后的 773 项 C++ 要求。当前继续战术、AI、边界和端口验收，尚非全部门禁通过；原 UDP 中立帧根因仍未证实。输入验证文件在 native-input-authority-resync-adoption-20260924-b/input-verification.json。

2026-09-24 已正式采纳权威时钟校正：runtime C 三轮原始窗口套件全部通过，共 9 个 standalone/TCP/UDP 场景；持续输入、释放、失焦、控制暂停及重新按键断言全部保留，私有 X11 均回收。TCP 候选双构建共 4 个真实客户端通过；复用的 UDP 候选此前双构建共 4 个真实客户端通过。每个会话 100 个确认帧、10 次哈希核验；窗口产品场景为 Release，键盘采样器另覆盖完整 Debug Sanitizer。runtime C 的 9 份命令日志已核对。

adoption B 已接入 4 文件：NativePublicationClock 校正适用于多帧提前、原 RTT 测试增至 14 项、冻结旧实现反例夹具、框架最低计数升至 773。当前源码清单 1138 项，sources-after.json 及 adopted-files.json 在 native-input-authority-resync-adoption-20260924-b；正式 quality_selftest 已通过，input_contract 正在执行，随后串行 framework_regression、tactical_integration、ai_decisions、native_boundary、native_session_ports。执行期间冻结当前源码及程序配置。正式门禁尚未全部完成；原始 UDP 中立帧未在三轮抓取复现，根因仍未证实，不能仅靠本次候选窗口通过关闭该问题。

2026-09-24 当前版本输入验收仍失败：自动端口 adoption B 的 input_contract 在 UDP 持续按住方向和冲刺期间，服务端 68 个检查区间步骤中有 1 个中立步骤（trace index 163）；客户端同时记录该步骤。trace index 不当作网络帧号。原始 actions、两端 trace 和 replay 的哈希及精确时间见 native-input-failure-review-20260924-b/failure-proof.json。新诊断 native-input-wire-diagnosis-20260924-b 已串行启动三轮真实窗口场景，保留原动作和全部断言，额外记录本机 UDP 原消息与持续按住区间的网络空帧邻居，用于区分漏发、迟到与中立值。观察器增加本机转发开销，不用于延迟验收；正式失败未关闭。

2026-09-24 完整阶段结果：native-control-fragment-adoption-20260924-a 已全部通过 quality_selftest、tactical_integration、input_contract、framework_regression、ai_decisions、native_boundary；日志及私有 X11 回收已核对。输入为 42 项结果、3098318 个断言、两种构建各 1031 帧独立回放，战术为 32 项结果、163494 个断言及 24 次回放。之后自动端口采纳改变源码，新版相关门禁另行执行；此记录只覆盖分片采纳的 1135 项清单。

2026-09-24 更新：连续输入修复正式门禁已通过 42 项结果、3070762 个断言，TCP/UDP 共 1030 个记录帧在两种构建独立回放。证据来自 native-input-contiguous-adoption-20260924-a。之后战术检查器源码发生变更，native-control-fragment-adoption-20260924-a 已排新一轮完整 input_contract；此前通过不自动覆盖新清单。以下为历史记录。

# UDP 持续输入空帧：发送证据、调度修复与验收

归属：ms-22.1 → plan-22.1.1 → task-22.1.1.1；关联 ms-23.1。正式修复已接入，完整门禁正在重新执行；输入和产品完成状态尚未提升。

## 实际缺口

native-input-wire-diagnosis-20260924-a 使用当前真实产品、私有 X11 和原物理键盘动作，串行完成三轮 standalone/TCP/UDP 场景。仅 UDP 增加逐字节转发的本机观察端，所有原检查条件保留。三轮结果为通过、UDP 持续按键检查失败、通过；每轮均回收 X11 和观察线程，双构建键盘采样检查通过。观察端增加一个本机转发环节，结果用于定位，不用于产品延迟验收。

第二轮的明确线上帧号 206 缺少客户端输入记录，服务端输出两席位中立输入；205 和 207 均有两席位方向 x=1、buttons=512 的输入。客户端可靠流 545 条、服务端可靠流 614 条已完整重组，没有遗留序号或应用缓冲。缺口落在原持续按住动作的检查区间，说明本轮空帧并非只是图形端观察迟到。wire-gap-proof.json 保存精确时间、原数据和哈希。逐步观察序号与网络帧号的全量映射未通过，因此本结论直接使用网络帧号，不依赖该映射。

## 修复

NativePublicationClock 在权威帧成批推进时，原分支可直接把发布目标从 205 跳到 207，即使 206 仍在服务端未来接收范围内。冻结的旧实现已用 Next(203,0,0,2) → 205，随后 Next(205,0,14ms,2) → 207 实际复现。提前量增大及本地调用迟到也可能跳过未来帧。

新实现先连续发布仍可接收的未来帧，再达到按 RTT 计算的目标。该序列先发布 206，下一次采样发布 207；每个已发布帧保持不可变，短按边沿只消费一次。单帧提前调度及权威帧大幅前进后的重新定位保留原语义。固定接收窗口仍为 16 帧。

## 已验证与正在验证

私有候选 native-input-contiguous-horizon-20260924-a 在 Release 和完整 Debug ASan/UBSan 下，各通过 11,011 条独立断言及 12 项 RTT 测试。独立程序覆盖旧算法反例、提前量变化、延迟调用、实际输入历史、一次性短按、1,999 个批量权威调度帧，以及 5,000 次单帧调度对照。4 项新回归已成为永久测试，原 8 项保留。

在所有先前进程终止并取得门禁锁后，正式接入 4 个文件：调度器、RTT 测试、冻结旧实现夹具、框架检查数量要求。当前正式源码清单为 1135 项，框架至少要求 771 项 C++ 测试及 RTT 套件 12 项。执行目录 native-input-contiguous-adoption-20260924-a 依次运行完整 input_contract、framework_regression、tactical_integration、ai_decisions、native_boundary，并独立核验完整 Debug 编译参数。执行期间源码冻结。

此前战术边界修复在 1134 项源码版本上通过完整战术门禁：32 项结果、161,819 条断言、19 项测试端自检，以及原生边界门禁。输入调度修改使这些记录不再代表最新源码，因此同样纳入本轮重新验收。

## 剩余事项

新的完整门禁尚未取得终态。原架构重复重启 RSS 失败仍未关闭，三轮输入诊断的通过结果也未覆盖原失败。原生菜单、暂停屏障、重连与弱网全场景、硬件渲染、产品手感与延迟、训练和包装等继续按原里程碑要求推进，不以本次局部修复替代产品验收。
