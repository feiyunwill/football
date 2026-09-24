# 优化阶段当前检查点（2026-09-24）

目标 ACTIVE：按里程碑→计划→任务完成框架、架构、性能、手感、网络、渲染、AI 的产品级实现与自动验收。局部通过、候选实现、诊断执行成功均不能当作整体完成。本轮 PROGRESS：完整Debug引擎构建完成，双向1500帧快照兼容性等通过，窗口长程揭示持续落后导致输入保留窗口耗尽；已实现新的缓存保存纯读取候选并开始串行验证。

## 当前唯一执行阶段

native-state-cache-purity-engine-20260924-b，PID 3069154，start_ticks 71184523。先核验 /proc/3069154/stat 身份和真实状态，再读 status.json / exit.json / failure.json。观察超时不是终态；不要重复启动。该阶段基于 state-writer engine B，仅修改 scene/scene3d/node.cpp 和 onthepitch/match.cpp，使保存/摘要/比较不再把缓存标记失效，只有读取快照才失效。前置A完整Debug已重新编译两对象、替换对应静态库成员并链接；A随后因验证工具使用不支持的四元数相等运算及私有球网方法而编译失败。新B通过分量比较和公开Match::Put路径修正工具，复用A的相同产品源码/核心库（SHA 5259081c0fda4891f636b344463d299fedc141c119ac22399c42e4a827c7cc17）；其余对象和头文件固定哈希，Release计划完整构建。

验证顺序：既有11项追帧测试及旧实现3个反例；真实缓存行为的两个旧版反例与新候选节点/球网契约；1500帧双向跨版本快照（Debug旧版生成输入复用B固定文件）；两个种子的真实快照恢复契约；原TCP/UDP窗口；原引擎独立回放。只要阶段失败则停止后续，保留输入与失败，再用新阶段修正。当前阶段尚未终态，不得认定缓存修正或图形门禁通过。

2026-09-24 局部验证：cache-purity B的完整Debug已复现节点/球网两个旧版反例，新版节点13断言、实际球网9断言全部通过，写入与11项追帧回归也通过。正在复验跨版本快照；实际窗口、Release及整个产品仍未验收。

## 不可变约束

全部构建、测试、性能测量严格串行；允许独立源码阅读和未排队准备。已排队/执行的输入不可修改。正式1138项源文件、program.json及原4项采纳文件保持冻结；基线为 native-input-authority-resync-adoption-20260924-b/sources-after.json 与 adopted-files.json。不要安装依赖、重启WSL/服务、修改主机挂载或全局环境。私有X11命名空间助手已授权。

原门槛保持：30s图形启动，Q到整个进程退出250ms，1000实际呈现/权威帧，1500快照帧，300s独立回放，12次重启/第3次预热/16MiB RSS。完整Debug保留-g、ASan/UBSan、泄漏检查、不可恢复错误和帧指针，不加O1。原TSan专属配方不变。/proc stat拆分后state在[0]、start_ticks在[19]，Z为终态。

## 最近完成的证据与失败

- native-state-cache-purity-engine-20260924-a已exit1、原PID已消失；产品核心库和11项追帧测试通过，缓存契约工具编译失败尚未运行。4312输入/16日志核验，见缓存engine B/predecessor-verification.json。新B仅修正工具用法，产品源码逐文件相同。

- native-state-writer-engine-20260924-a 已exit1。完整Debug引擎构建成功，11项追帧测试通过、原实现新5场景中预期3失败；真实写入测试工具main()与引擎main(int,char**)声明冲突，未运行后续。3244输入/7日志核验，见engine B/predecessor-verification.json。
- native-state-writer-engine-20260924-b 已exit1，PID3065250已不存在。修正测试入口及保存模式eos，原A的eos错误在反例中复现，新版真实写入契约通过。新→旧和旧→新各1500快照、2999消费哈希检查与1499连续推进全部通过；seed42正常946断言、seed43反序950断言的真实快照契约通过。
- B窗口实际TCP完成启动、全局暂停epoch1和恢复epoch2（边界frame221）。长程中客户端1496步、服务端2542步，仅12次完整比赛呈现，客户端报 Local input frame is outside the retained window 并exit1，服务端exit0。UDP、Release、窗口退出与长程回放未执行，不能声称通过。3799输入/34日志核验，见缓存候选/predecessor-verification.json。分析见 native-state-writer-progress-20260924-a/engine-b-window-analysis.json。
- B客户端摘要中位6.074ms，逻辑步28.001ms；服务端摘要5.750ms，逻辑步14.574ms。更早原始摘要约12.132ms。分段有观察开销和嵌套，不能相加或直接声称整机性能达标。按相同模拟帧对齐，早期三个失败样本的客户端逻辑仍约慢1.94–2.06倍。
- native-state-writer-comparison-20260924-a 已exit0；Release/full Debug各baseline/append/chunked组件比较通过。Debug每20次32768字段写入的9轮中位202.473→71.642ms，Release5.088→3.344ms。仅组件证据。分块缓冲GetState裁剪和B保存eos语义已验证，头文件/类布局保持一致。
- 两次 starvation diagnostic A/B 各exit1复现原30s启动超时，各2748输入/3命令日志核验；phase和同模拟步分析在 native-control-starvation-analysis-20260924-a。
- render-quit A 已exit1：Release10单元、TCP/UDP分别1003/1002呈现、7825/7497权威帧、退出73.241/105.959ms，取消当前帧6.121/21.285ms、0交换且哈希不变；15322帧独立回放通过。完整Debug10单元通过但原30秒比赛呈现失败。2739输入/28日志核验，不能写成双构建图形通过。

## 缓存修正依据和限制

Node::ProcessState原来在保存时也把父子节点的位置、旋转、缩放和包围盒缓存设为dirty。新候选只在Load()时执行；测试通过合法派生节点检查保存/比较/排除不改变缓存，既有dirty不清除，读取后父子派生值重新计算正确。
Match::ProcessState原来保存时也设置resetNetting/nettingHasChanged。新候选把这两项与读取mentalImages放在Load分支；真实GameEnv测试观察目标Geometry::OnUpdateGeometryData，要求保存/摘要不安排额外上传、读取仍安排上传、摘要不吞掉既有上传请求。
以上是代码审查发现，仍需反例/正例和实际窗口证据；不要提前把它解释成客户端所有额外逻辑耗时的根因。

## 永久集成准备与后续

native-control-adoption-preparation-20260924-a当前25候选文件、未排队/未采纳：控制/恢复/退出实现，分块缓冲及B的eos，追帧优化，5原测试套件100项加native_authority_backlog_test5项；framework最低773→878。最终注册和全套构建仍须验证。当前缓存修改尚未加入该准备树。
永久实际控制/恢复/窗口门禁入口仍未完成；现有fixture生成器按当前源码唯一锚点生成隔离Host与恢复故障夹具，不能把私有回执替代永久门禁。后续先完成当前阶段，若失败据真实证据修正，再补永久入口并用最终源码重新跑正式质量/输入/框架/战术/AI/边界/端口及新增门禁，满足要求后才采纳。不要提前将program或任务验收标为完成。
真正的Host产品菜单和完整恢复/弱网矩阵仍待实现与验证。

## 更早证据与其他未关闭项

recovery-refresh B：双构建各51项测试，12普通实际客户端、6断线/过期快照重试，18次独立回放含全部检查点；1594输入/74日志核验。client-owner A：双构建各48测试、12会话/24控制周期、12独立回放；1578输入/54日志。
GUI A原Q退出338.645ms失败仍保留；短程和long A/B复测均不能证明原单次超时完整因果。long B两TCP一UDP原1000呈现规模退出136.885/137.710/168.543ms，2724输入/10日志核验。渲染取消实现减少退出后等待，不等于原失败已完全闭合。

原UDP持续按键中立帧根因、原RSS重启>16MiB失败仍未闭合。保护性能基线缺失：/tmp/football-optimization-baselines/d5098f8bc112958cfed2c848263e9eb8f852065cb24691c81495e08e2ed0b32d/libfootball_engine.so，期望SHA ad3a56a95f06a900b487253b9986e6f9064dd20dbb2f60e342a0efef43fb9a0c。WAN、容量、50ms p95、目标硬件渲染、RLtools/训练和打包等尚未全量通过。network_reconnect/network_regression不应标ready。

## 工作区与工具

master最近用户要求的提交推送已完成：47fea0a（9进度文档）；此前8ea0dc6为进度文档，44f3ad7为权威时钟修复。本轮只有新的进度文档未提交，候选均在被忽略的benchmarks中。不要自动把未验收私有候选变成正式产品代码。
使用原生Git；Windows Git会制造模式/符号链接差异。可靠入口：
wsl.exe --system --user root --exec /usr/bin/nsenter --target 2 --mount --uts --ipc --net --pid --root --wd -- /usr/bin/python3 -
--wd后不要加路径。Python为/root/.cache/football-quality-20260910/venv/bin/python；functions存储nativeRun可复用，JS String.raw中避免反引号和美元花括号。
图谱Verify，root-work_space-football最新确认generation/metadata 2026-09-24T05:28:08Z；match.cpp1397、integrated_client.cpp1334等已读精确缺口；benchmarks排除，均直接读源码。无子代理授权，不要派生代理。
