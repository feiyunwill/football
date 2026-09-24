# 优化阶段当前检查点（2026-09-24）

目标仍 ACTIVE：按里程碑→计划→任务完成框架、架构、性能、手感、网络、渲染、AI 的产品级实现和自动验收。不得把候选、局部通过或诊断执行成功当作整体产品完成。本目标轮为 PROGRESS：实现退出时的渲染检查点取消、真实暂停标题，Release 单元/窗口/独立回放均通过，完整 Debug 图形启动超时；新增分段计时诊断复现同一失败。

历史 SESSION 全文（5278 行）已原样归档到 native-control-render-quit-progress-20260924-a/documents-before-release-complete/.project/optimization/SESSION.md；旧失败、证据与状态仍保留在各阶段和报告中。

## 当前进程与不可变约束

当前没有上述阶段仍在运行：native-control-render-quit-20260924-a 已 exit 1；native-control-sanitized-starvation-diagnostic-20260924-a（PID 3031475，start_ticks 70976304）也已 exit 1，提交前核查其 /proc 句柄已不存在。两者均因 Actual graphical startup deadline 结束，失败记录和日志保留。后续修正必须新阶段。

全部构建、测试、性能测量严格串行。允许独立源码阅读和未排队候选准备。已执行/排队的输入不可修改；修正必须新阶段。正式 1138 项源文件、program.json 和此前4个采纳文件保持冻结直到当前阶段终止。来源清单为 native-input-authority-resync-adoption-20260924-b/sources-after.json 及 adopted-files.json。不要安装依赖、重启 WSL/服务、修改主机挂载或全局环境；私有 X11 命名空间助手已授权。

保留原门槛：30s 启动、Q到整个进程退出250ms、1000实际呈现/权威帧、1500快照帧、300s独立回放、12次重启/第3次预热/16MiB RSS。完整 Debug 必须保留 -g、ASan/UBSan、泄漏检查、不可恢复错误和帧指针，不加 O1。原 TSan 专属目标自己的配方不在此修改。

## 当前候选与已取得证据

render-quit A 相对已经验证的 recovery-refresh B 只有4个产品文件变化：
- native_render_cancellation.hpp：仅以私有取消信号停止自己的渲染调用；其他异常继续传播；既有4ms服务检查点仅读线程安全退出标志。
- native_loop.hpp：新增 RenderUntilQuit，不把SDL调用搬到游戏线程。
- native_client_loop.hpp：取消后继续原传输停止、回放持久化、连接关闭与正常资源销毁。
- integrated_client.cpp：已协商的全局控制显示 Pausing/Paused by host/Resuming，恢复连接提示保留。

Release 已通过10项作用域/资源析构/异常透传/服务恢复/采样节奏/线程隔离回归。真实TCP/UDP分别1003/1002次呈现，7825/7497权威帧，退出73.241/105.959ms，取消当前绘制帧耗时6.121/21.285ms。各恰好1次取消、0次交换、逻辑哈希不变。真实XTEST方向/冲刺、暂停射门不泄漏、旧按键不复活、松开重按恢复、实际X标题均通过。两场15322帧独立GameEnv回放全部一致。15份Release命令日志哈希独立核验，见 native-control-render-quit-progress-20260924-a/release-verification.json。

完整 Debug 的10项取消回归通过，但真实TCP窗口触发原30秒启动超时；客户端和服务端均正常退出。2739项输入和28份命令日志已核验，见 native-control-render-quit-progress-20260924-a/terminal-a-verification.json。分段计时诊断也复现该超时，数据仍待分析。不能表述成双构建图形通过。观测库记录render_begin/cancelled、SDL退出/环境清理/fsync；fsync保留errno。Q在新鲜的实际render_begin后用XTEST发送，1ms观察进程回收，和诊断对照相同。测试没有移除保存/清理，也没有缩短比赛规模或放宽时限。

现有异常清理证据：GraphicsTask::Render 的帧队列 RAII，GameEnv::render_interpolated 的 Tracker/context 守卫；ScopedRenderService 保留作用域与异常恢复。完整 Debug 图形验收仍未通过。图谱 Verify：root-work_space-football，最近确认 generation 2026-09-24T04:34:11Z；opengl_renderer3d.cpp 部分索引3057/3065和integrated_client.cpp 1334均已读源码。benchmarks被排除，私有源码已直接读取。

## 已完成的前置阶段与原失败

- recovery-refresh B：Release/full Debug 各51测试；12普通客户端、6真实流断线/过期快照重试；18次独立回放含所有检查点。1594输入和74命令日志哈希核验，见 GUI A/predecessor-verification.json。旧 epoch Ready 返回 ControlChanged，保留原恢复期限/租约，错误哈希仍撤销；旧快照流隔离新epoch权威帧。
- client-owner A：双构建各48测试、12实际会话/24暂停周期、12独立回放；1578输入/54日志核验。
- frame-owner B、session-integration B：双构建测试/实际会话通过。A的原异步关闭断言和packed引用UBSan失败保留。
- GUI A：Release/TCP在8505确认帧/1003呈现后Q退出338.645ms，exit1。2632输入/7日志核验。原失败未闭合，不能用一次复测变绿否定。
- short quit diagnostic A：100呈现规模，仅诊断；TCP/UDP退出163/187ms，不能替代长程。
- long diagnostic A：8803帧/1003呈现、退出198.994ms；2719输入/6日志核验。
- long diagnostic B：两TCP/一UDP原1000呈现规模，退出136.885/137.710/168.543ms；游戏线程到退出边界89.448/89.544/113.210ms，回放保存10.149/14.398/14.748ms。2724输入/10日志核验，见 gui-progress/long-b-verification.json。所有诊断独立回放通过，但原339ms完整因果仍未证明。新实现直接消除观测到的退出后剩余渲染等待，未宣称已经证明原单次超时的全部原因。

## 后续动作

1. 分析已终止的分段计时诊断，核验其输入和日志，定位完整Debug客户端追帧期间无比赛呈现的成本与调度问题；在新阶段修复并重跑原门槛，不能改动已执行阶段。
2. native-control-adoption-preparation-20260924-a 目前22候选文件，尚未排队/构建/正式采纳：原控制/恢复9产品文件加退出helper/两loop，5套永久测试共100项，测试CMake、framework最低773→873、通用render_begin/cancelled观察器、精确唯一锚点夹具生成器和真实窗口探针。全部永久注册/最终头文件组合仍须验证。
3. 永久实际控制/恢复/窗口门禁入口还需完成。fixture生成器把变换内嵌受哈希的Python源，拒绝非唯一/失配锚点；恢复故障钩子只进入单独生成的客户端。最终必须用当前正式源重新执行，不以私有收据替代。
4. 只有上述验证完成后才采纳，并运行质量/输入/框架/战术/AI/边界/端口及相应新门禁。不要提前修改program就绪状态或任务验收完成状态。
5. 继续真正的Host产品菜单/暂停入口、完整恢复与弱网矩阵、性能等剩余产品工作。

## 其他未关闭项

原始UDP连续按键中立帧根因未证明；权威时钟校正和后续输入验证通过不能替代因果证据。原架构RSS失败（12重启/第3次预热后>16MiB）仍未闭合，成功复测/allocator映射不能代替原失败。保护性能基线缺失：/tmp/football-optimization-baselines/d5098f8bc112958cfed2c848263e9eb8f852065cb24691c81495e08e2ed0b32d/libfootball_engine.so，期望SHA ad3a56a95f06a900b487253b9986e6f9064dd20dbb2f60e342a0efef43fb9a0c。WAN、容量、50ms p95、目标硬件渲染、RLtools/训练和打包等尚未全量通过。network_reconnect/network_regression仍不应标为ready。

## 工作区与提交

当前正式分支master；本检查点更新9份进度和验证文档，记录已结束阶段的实际结果。此前提交8ea0dc6为进度文档，44f3ad7为权威时钟修复。新候选仍在被忽略的benchmarks中，尚未采纳为正式产品代码。

使用原生Git检查工作树，Windows Git会制造模式/符号链接差异。可靠原生入口：
wsl.exe --system --user root --exec /usr/bin/nsenter --target 2 --mount --uts --ipc --net --pid --root --wd -- /usr/bin/python3 -
--wd后不要跟路径。Python环境 /root/.cache/football-quality-20260910/venv/bin/python。functions存储的nativeRun包装可复用；JS String.raw中不要放字面反引号或美元加花括号插值。
