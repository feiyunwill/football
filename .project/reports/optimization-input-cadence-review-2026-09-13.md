# 输入节拍预算审查

2026-09-13。对应 ms-22.1 → plan-22.1.1 → task-22.1.1.2，并约束 task-22.1.2.2 的动作生效 p95 ≤ 50 ms。当前没有修改比赛协议、物理步长或验收门槛。

现有 [比赛节拍](../../gfootball/frame_sync/match_cadence.py) 固定为 10 Hz 输入、10 Hz 网络帧，每个权威帧包含十个 10 ms 物理步。它严格拒绝其他节拍，协议说明要求变更时升级协商版本。提高画面刷新率或保留短按，均不能缩短逻辑输入的 100 ms 消费周期。

[相位扫描诊断](../optimization/benchmarks/input-cadence-diagnostic-20260913-a/report.json) 实际调用当前 FramePacer 与 InputBuffer，在理想虚拟时钟下，对两次逻辑准入之间的 99 个均匀输入时刻执行短按／释放。全部短按被保留并且只消费一次，但当前节拍的采样等待 p95 达到 95 ms，已经超过 50 ms。报告 SHA256：`eed353365797eb4bbb92ee3d90cbb51e010f7203a7ba8a32a5ada9acd1dd3bd8`。

| 调度频率 | 逻辑间隔 | 仅输入采样等待 p95 | 当前 v5 比赛是否支持 |
| --- | --- | --- | --- |
| 10 Hz | 100 ms | 95 ms | 是 |
| 20 Hz | 50 ms | 47.5 ms | 否 |
| 25 Hz | 40 ms | 38 ms | 否 |
| 50 Hz | 20 ms | 19 ms | 否 |

这些是现有调度器与输入缓冲的理想时钟诊断，未运行 GameEnv、操作系统设备事件或显示呈现，也没有证明备选节拍下的 CPU、网络、AI 和完整产品质量。20 Hz 仅剩 2.5 ms 的 p95 余量，不能据此直接认定可满足目标。后续应基于实际球员响应和显示路径确定新节拍，显式升级版本协商、恢复快照、录制元数据及对应拒绝规则；原短局基准的固定场景、步数和不可变基线保持独立。

原生网络入口还需要稳定的“帧编号→已采样输入”关系。[FrameSimulation::Tick](../../engine/src/frame_sync/frame_simulation.hpp) 可能先消费多帧权威状态，再决定是否执行一个预测帧；仅凭调用次数或返回枚举不能假定恰好推进一帧。输入缓冲应在实际新帧准入时消费短按，并在等待、重复发送和纠正期间维持已提交帧的输入。当前仍是待实现项，未新增测试覆盖或改变发送逻辑。

真实设备路径的下一步采用 XTEST 键盘事件、SDL 虚拟手柄和实际焦点切换；测试仍区分操作系统事件与真实物理设备。准备的 [原生探针](../optimization/benchmarks/native-input-window-preflight-20260913-a/probe.cpp) 直接调用当前 PythonWindowInput，包含同时按键、释放、快速短按、手柄轴／按钮和断开、两个真实 SDL 窗口间焦点切换。此探针尚未编译或执行，不作为输入门禁通过证据。

依赖包已由现有 pacman 签名验证后解包到 `/root/.cache/football-input-x11-20260913-a/root-relocated`，没有安装到系统或升级现有库。X11 socket 目录当前权限不适合 Xvfb，直接启动的失败已保留；准备的 [私有命名空间执行器](../optimization/benchmarks/native-input-window-preflight-20260913-a/namespace_probe.py) 使用独立的工具覆盖目录和 X11 socket 挂载，不改宿主目录权限或重置 WSL。该执行器仍待实际验证。

当前长局正式依赖链正在性能测量阶段，先保持被测源码与工具环境，再继续这些实际输入测试。
