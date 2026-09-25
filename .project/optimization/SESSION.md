# 优化阶段当前检查点（2026-09-25）

目标 ACTIVE：按里程碑→计划→任务推进产品级实现与验收。此检查点记录局部验证进展，整体产品验收尚未通过。

## 当前执行阶段

native-state-permanent-validation-20260925-b：owner PID 8327，start_ticks 30397，boot_id 83c934ba-d634-4fa5-b636-b52276e0095b，前台 exec 会话 42055。本次提交前已核实进程身份；状态门禁 24 项结果通过，报告断言合计 81100，控制门禁正在执行。后续必须再次核实 boot_id、PID 与 start_ticks，不得将历史状态当作当前状态。

阶段冻结 46 份候选文件与 1164 份状态源文件，正式源码 1138 份固定输入不变。Release/sanitized 构建位于阶段目录；证据位于 workspace/.project/optimization/benchmarks/state-evidence 和 control-evidence。控制门禁预期 38 项结果，包括 12 个普通客户端、6 个恢复客户端、4 个 TCP/UDP 窗口和 22 次独立回放；尚未确认全部通过。以本阶段 candidate-hashes.json 为准，较早永久控制准备副本仍为 45 份文件。

A 阶段 PID 26079/start_ticks 33044、child 26080/start_ticks 33178 在环境重启后消失，构建日志留下 662 个 NUL 字节，无 exit/report，不能标记通过。B 未复用 A 的中断构建对象。中断证据：native-state-hash-progress-20260925-a/environment-interruption.json。

## 已确认结果

2026-09-25 永久验证进展：native-state-permanent-validation-20260925-b 的 Release 与完整 Debug 状态门禁已全部通过，共 24 项结果、81100 项断言；双向各 1500 份跨配置快照恢复通过。当前进入控制门禁，尚未完成实际窗口与独立回放验收。正式源码未采纳候选，产品级验收仍未通过。

2026-09-25 渲染调度验证：旧逻辑持续权威积压时的呈现饥饿反例已复现；native-render-fairness-contract-20260925-b 在完整 Debug/Release 各通过 31398 项断言，836 份输入和 6 份日志核验通过。候选将调度主动延后限制为 100ms，但不保证包含在途工作耗时的实际帧间隔。永久验证纳入 46 份候选文件，控制门禁预期 38 项结果。A 阶段因环境重启失去 owner/child，未形成终态，B 在持久构建目录重新验证。基准源码经全 Git 小于等于 4MiB 的 blob 搜索后恢复至 844/881，仍缺 37 份及原基准二进制。

2026-09-25 哈希整机终态：native-state-hash-engine-20260924-a 退出 1；组件、双向各 1500 份快照及 946/950 项恢复断言通过，但 TCP 仅 65 次呈现，未达到 1000 门槛。客户端确认 12835 帧、核验 1284 次哈希，双方各 12836 步；客户端退出 0，服务端因 Host deadline 退出 1。提供者哈希中位约 0.063307ms，状态摘要序列化约 3.931ms，Step 约 14.751ms，完整呈现约 89.876ms。未进入 UDP、整机 Release 和后续窗口回放，不能宣称整机性能达标。终态复核 9174 份输入中 9151 份匹配，23 份 /tmp 构建产物已缺失；53 份日志匹配，当前复现材料不完整。

Release 与完整 Debug 每种配置的 10 项状态组件/恢复结果各 37551 项断言通过。跨配置双向各生产 1500 份快照，消费者各验证 2999 次哈希与 1499 次后续运行；这是同一候选源码的跨配置兼容性，不是跨版本兼容性。

## 分析与尚未执行的准备

native-pipeline-profile-preparation-20260925-a 准备了 18 个观测钩子：13 个比赛处理步骤、3 个状态保存/加载入口、ECS 同步和镜像。尚未编译运行，不能以缺失钩子推断耗时为零。图索引服务 Transport closed，相关定位使用精确源文件与 ELF 符号回退。

native-pipeline-retained-analysis-20260925-a 仅只读处理已经结束的失败运行日志：65 个完整呈现帧中，模型变形按帧聚合中位 12.449058ms、图形提交 72.560284ms、完整呈现 89.876249ms。PrepareRender 与模型变形计时包含关系重叠，不能简单相加；这些带观测开销的旧样本不是新性能验收。

native-skinning-lookup-preparation-20260925-a 只准备了顶点、骨骼与关节查找复用，保留原浮点运算及遍历顺序；尚未排队、编译、执行或采纳。必须验证实际网格属性一致性、完整 Debug/Release、窗口与独立回放后再判断收益。

输入异常定位：NativePublishedHistory.Read 使用 Find，缺失时返回默认值；“Local input frame is outside the retained window”来自 ForFrame 的保留窗口边界，可能经 pump_input/PublishTimed 触发。运行时具体跨度未取得，根因仍未关闭，不得以扩大容量或强制默认输入掩盖问题。

## 后续约束

构建、测试和测量串行；执行中的候选与固定输入不可修改。原始启动 30s、1000 权威/呈现帧、退出 250ms、1500 快照、独立回放 300s 与 RSS 16MiB/12 次重启等门槛保持不变。原始 RSS 与输入问题、实际 Host 菜单、完整恢复/弱网矩阵、历史性能基准、硬件与 AI/打包验收仍待完成。

以下为历史检查点，其中进程身份和运行状态仅代表当时记录。

# 优化阶段当前检查点（2026-09-24）

目标 ACTIVE：按里程碑→计划→任务完成框架、架构、性能、手感、网络、渲染、AI 的产品级实现与自动验收。本轮 PROGRESS：增量日志工具的边界与旧记录等价验证通过；实际窗口仍未达到1000呈现。已验证SHA-256提供者组件等价、失败与并发行为，并开始实际产品整机验证。局部通过不能当作整体完成。

## 当前唯一执行阶段

native-state-hash-engine-20260924-a，PID 3157430，start_ticks 71703087。先核验 /proc/3157430/stat 身份与真实终态，再读status/exit/failure；观察超时不重启。基于capture engine A，仅修改state_hash.hpp及显式Crypto CMake传递链接。完整Debug复用已核验的相同核心库，121份核心原始/替换对象依赖文件均不包含该哈希头；所有使用哈希的主程序、契约与观察器重新编译并显式链接现有OpenSSL。Release仍要求完整源码构建。验证2054哈希、306姿态、动画/镜像/字节/缓存、双向1500快照、两个种子恢复、原TCP/UDP窗口、旧核心独立回放。窗口使用已验证的增量日志读取，增加真实EVP调用字节数/耗时记录，原门槛不变。

前置native-state-hash-provider-contract-20260924-a已exit0、进程不存在，373输入/4日志核验。完整Debug/Release各2054断言通过，保留SHA-256完整摘要与前8字节小端协议值；提供者失败、异常长度、空输入/非法非空指针、失败后的调用和并发一致性通过。固定87132字节9批×100次，新候选组件Debug原291.914258ms/提供者2.728352ms，Release原24.681695ms/提供者2.343851ms。仅组件，不是整机吞吐。

native-trace-reader-validation-20260924-a已exit1、进程不存在，8499输入/3日志核验。11项单测和两份旧日志270600条记录/31899958字节等价通过。相同产品程序实际窗口仍只22呈现；服务端Private GUI Host deadline expired，客户端随后进入重连，最终退出0，服务端1。客户端13542帧、1354哈希核对、failed=0，服务端13613步；未在该次复现客户端输入窗口耗尽，但1000呈现未过。客户端步中位12.696ms、摘要3.420ms、保存姿态0.922ms，渲染110.634ms（少量样本）。不能把不同运行的中位差全部归因于工具，也不能称网络/吞吐已达标。UDP、窗口旧核心回放未执行。

永久native-control-adoption-preparation-20260924-a当前45候选；隔离native-control-permanent-preparation-20260924-a已复制1937文件，状态源范围1163文件。加入哈希头、2054断言契约、传递Crypto链接；状态门禁两构建20组件/种子用例加4跨构建快照操作，共24结果。永久入口尚未执行/排队，ready=false。新增11项Python边界测试等待完整quality_selftest验证；框架仍要求878项C++测试。正式1138源文件和program继续冻结，rl-tools子模块仍为空，产品其他未完成范围不变。

## 上一执行阶段（已结束）

native-animation-state-engine-20260924-a，PID 3112746，start_ticks 71425205。先核验 /proc/3112746/stat 身份及真实状态，再读 status.json / exit.json / failure.json；观察超时不是终态，不重复启动。

前置mirror D和bulk comparison A均已终态且原进程不存在。mirror D完整Debug的19项镜像断言与旧姿态参考、22项缓存断言、双向1500帧兼容（每个消费端2999哈希/1499续跑）、946/950断言恢复全部通过。实际TCP启动及暂停恢复通过，长程仍报 Local input frame is outside the retained window：4228客户端步/5270服务端步，仅16次呈现，退出1/0。客户端逻辑步中位16.705811ms，服务端14.223810ms；客户端摘要6.260773ms，动画Fetch每物理步2.023011ms对服务端1.171938ms。UDP、Release和窗口独立回放未执行。6900输入/37日志核验，证据native-mirror-graphics-progress-20260924-a/terminal-d-verification.json。相比缓存B的27.745ms客户端步有局部改善，但不代表1000呈现门槛已过。

native-state-bulk-write-comparison-20260924-a已exit0；真实完整Debug EnvState旧/新各24832断言，8192组Vector3/Quaternion/radian/二进制字符串的360448字节完全一致。保留有限数读取、截断原子性、规范角度标志/填充、参考比较/位级差异/抛错、canonical排除及最大边界部分写入偏移。9轮各20次序列化中位345.888984→104.618104ms，仅组件证据。6911输入/6日志核验，见当前engine阶段predecessor-verification.json。

当前组合候选相对mirror D只改defines.cpp与HumanoidBase.cpp：普通保存按明确字段数组批量写入（不复制结构体padding），读取/参考比较及不够容纳整个字段的边界仍走旧路径；逻辑动画FetchPutBuffers保留递归派生失效和非图形观察者，排除Graphics通知，实际全身/头发仍在Put发布。Header不变。完整Debug复用已核验批量defines.o、重编译HumanoidBase并替换gamelib同名成员；其余对象/库固定哈希。Release仍须完整构建。

执行顺序：动画旧反例/旧参考与新姿态位级对照、24832项真实批量字节契约、镜像/标量/缓存契约、1500双向旧/新快照、两个种子恢复、原TCP/UDP窗口和独立旧核心回放，成功后完整Release。不提前采纳或提升program就绪状态。

镜像A/B/C夹具失败保留：A误用世界XY取反，B/C旧核心往返也失败；C确认初始派生位置遗漏根平移（0.35,0.7,1.05→-24.65,0.7,1.05），前后旋转均单位四元数，先前四元数猜测已纠正。D在夹具基准前显式更新层级缓存，旧/新19断言及姿态摘要10057015697396660735通过。A/B/C各5351/5861/6371输入，12/9/9日志已核验。

2026-09-24 提交检查点：组合候选已复现旧动画通知反例，旧/新动画各16项断言通过，姿态摘要同为7577643041246268683；批量写入24832项、镜像19项、节点13项及球网9项断言通过。候选生成的1500帧快照已由旧核心完成2999次哈希核对和1499次续跑；反向消费仍在执行。实际窗口和完整Release尚未取得结论。永久控制窗口工具已改为显式传递sanitized模式，准备文件仅完成语法解析，未执行正式门禁。

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

native-control-adoption-preparation-20260924-a当前45候选文件、未排队/未采纳：控制/恢复/退出实现，分块缓冲及B的eos，追帧优化，5原测试套件100项加native_authority_backlog_test5项；framework最低773→878。最终注册和全套构建仍须验证。当前缓存、镜像、批量写入与动画实现和8个永久状态C++契约已加入准备树。
永久状态入口native_state_contract.py已准备双构建写入/缓存/镜像/批量写入/动画/姿态保存/SHA-256提供者、两个种子恢复与双向各1500帧跨构建快照（不冒充跨版本证据），proposed-checks.json登记状态与控制两项均ready=false，尚未执行。永久实际控制/恢复/窗口门禁入口native_control_contract.py已准备主体，并有独立回放CMake目标、恢复探针、私有X11助手及proposed-check.json（ready=false）；仅语法解析，尚未执行。覆盖双构建12普通客户端、6恢复故障客户端、4真实窗口、22独立回放，保留原门槛；fixture生成器按当前源码唯一锚点生成隔离Host与恢复故障夹具，不能把私有回执替代永久门禁。后续先完成当前阶段，若失败据真实证据修正，再补永久入口并用最终源码重新跑正式质量/输入/框架/战术/AI/边界/端口及新增门禁，满足要求后才采纳。不要提前将program或任务验收标为完成。
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
