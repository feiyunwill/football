# 优化进展：展示姿态插值与回滚过渡

2026-09-10。对应 ms22 → plan22.1.2 → task22.1.2.1，并继续支撑 ms21 的展示预算与比赛集成。本轮接通 Python 展示时序和 C++ 球、骨骼、相机插值路径。新增数值与时序检查通过，完整比赛和网络回归通过；C++ 尚未编译，真实中间帧图像尚未验证，任务没有完成产品验收。

## 实现与审查结果

[LogicStateHolder](../../gfootball/frame_sync/presentation_state.py) 增加原子 `read_pair()`，借用最后两个不可变快照，不复制载荷。已有最多 4 份、合计 4 MiB 和单份 1 MiB 的预算保持生效；显示读者临时引用仍需另计，不能解释为整个进程的上限。

[PresentationLoop](../../gfootball/frame_sync/presentation_loop.py) 可显式启用插值，[图形入口](../../gfootball/frame_sync/graphical_runtime.py) 强制启用。正常相邻帧以最新逻辑发布时间计算比例，从前一逻辑姿态过渡到当前姿态；确认号和等待标志变化不重置该时刻。停止接收时只到已知端点，不外推。正常模式带有约一个逻辑间隔的缓冲延迟，尚无输入到画面的测量。

回滚、同帧纠正、历史中断从最近实际显示姿态开始过渡。纠正过程中出现新目标时继续从可见姿态衔接。终局使用 `settle=True` 到达精确端点，后续绘制不会重新退回过渡起点。初始状态直接显示；非法时钟与绑定缺失明确失败，错误清理保留原有所有者规则。

[GameEnv](../../engine/src/game_env.cpp) 新增 `save_render_state(from_display=False)` 和 `render_interpolated(alpha, swap_buffer=True)`，[Python 绑定](../../engine/ai.cpp) 暴露这两个方法。捕获和绘制使用已有上下文锁与 tracker 守卫；参数要求有限的 0–1 比例，无渲染环境或尚无端点时拒绝。reset 清除环境渲染历史标志。

[GameTask](../../engine/src/gametask.cpp) 将插值比例传入 [Match](../../engine/src/onthepitch/match.cpp)，再执行既有蒙皮和几何上传。球处理位置与旋转，相机处理位置、旋转、视场角和裁剪距离。alpha=0 保留起点旋转，alpha=1 走普通 Put 的精确终点。ECS 显示同步在插值覆盖之前执行。

审查发现人物旧 `PutInterpolated()` 只改 spatialState，而实际 Put 读取骨骼节点，因此不能改变最终蒙皮姿态。[HumanoidBase](../../engine/src/onthepitch/player/humanoid/humanoidbase.cpp) 现在插值实际用于蒙皮的关节位置/旋转及 fullbody 位移，并更新头发。每个人物固定最多 64 个历史关节，不增加完整游戏快照；队伍和裁判传递镜像坐标选择，未激活球员清除历史。缓存不进入 ProcessState，不通过改写逻辑 spatialState 实现插值。

行为、延迟和 API 详见[展示插值文档](../../gfootball/doc/render_interpolation.md)。修改保留带日期与原因的原代码注释；本轮未执行 Git 操作、依赖安装、WSL 重置或 C++ 构建，也没有调整正式验收阈值。

## 当前证据

环境为 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0。Python 姿态 oracle 明确分开保存物理值和显示值；集成用例实际运行 socket、线程和文件，没有替代 GameEnv 导入。

| 检查 | 结果与执行范围 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、存档及回放 | 本轮重跑 297 项通过，115 个来源文件 | [报告](../optimization/benchmarks/python-render-interpolation-match-windows-20260910-a/report.json) |
| 共享 TCP/UDP、恢复与展示回归 | 本轮重跑 219 项通过，44 个来源文件 | [报告](../optimization/benchmarks/python-render-interpolation-network-windows-20260910-a/report.json) |
| 资源所有权、录制及环境回放组件 | 复用此前 146 项通过的证据，36 个来源文件仍匹配；本轮未重跑 | [报告](../optimization/benchmarks/python-match-cadence-recording-windows-20260910-a/report.json) |
| 实际资源和 Python 策略读取 | 复用此前证据，21 个来源文件仍匹配；本轮未重跑 | [报告](../optimization/benchmarks/python-match-cadence-identity-files-windows-20260910-a/report.json) |

本轮两套回归无失败、错误、跳过、受检工作线程遗留或已检测异步警告；比赛检查受检子进程和目录锁归零。复用的录制报告中共享池 live/leased/idle 为零。四份报告、相关来源文件和日志的 SHA256 均核对，详见[证据清单](../optimization/benchmarks/python-render-interpolation-evidence-20260910.json)。源码指纹覆盖不等于实际执行：比赛报告包含 17 个本轮修改的原生文件，但没有编译它们。之前节拍阶段的比赛与网络归档现为历史，录制和文件证据只在其未变动的范围内复用。

新增 [14 项必需检查](../../gfootball/frame_sync/test_render_interpolation.py) 覆盖逻辑发布时间、慢显示端点、连续 1000 帧时序、同帧及连续纠正、纠正期间新目标、同载荷不连续事件、元数据、等待、长停顿、终局稳定、清空会话、错误时间、钩子失败、选项边界和并发原子读取。既有图形协调用例也使用新钩子，并核对最终显示端点。39 个 Python 文件通过 Python 3.9 AST 语法检查，实际执行解释器仍为 Python 3.14.6。

新增 [真实原生图像用例](../../gfootball/frame_sync/test_graphical_native.py) 要求 alpha=0/0.5/1 出现不同中间像素、绘制前后规范摘要一致、捕获已显示起点后图像一致，以及非法比例和无渲染环境拒绝。它尚未执行。完整比赛探针选择 `--native --graphics` 后现在要求 11 项真实比赛/图形用例，不能用 Python 模型替代。

## 未完成项与下一步

- [Officials::PutInterpolated](../../engine/src/onthepitch/officials.cpp) 的持牌位置仍读取当前动画节点，可能与插值后的手部错位。下一步应统一附属物与人物显示姿态，再用真实持牌场景验证。
- 当前关节位置按相对 fullbody 根节点的派生位置混合，旋转采用球面插值；它不是局部骨骼的逐层正向运动学。大幅动作中的肢体长度、蒙皮形状、镜像与多场景质量仍需原生图像验证。
- 正常插值周期固定为 100 ms。逻辑状态不规则到达时可能提前切换上一个过渡端点；尚不能承诺网络抖动下连续无跳变，也没有 WAN、视觉延迟或长期 p99 改善证据。
- 暂停协议和新暂停按键本轮未实现。后续须建立权威暂停/恢复及输入清理语义，不能仅暂停客户端副本；已有保存、退出和换人按键仍按原用途工作。
- C++23 构建、11 项真实比赛/图形检查、另 28 项环境/原生/渲染检查、POSIX 文件、设备输入、GPU/RSS、原生分配与长期性能仍未完成。C++ 通用协议与 Python 比赛 v5 的互通边界，以及 AI 和发布里程碑继续待办。

`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 四个 ready 标志仍为 false。ms21—ms26 未因局部测试通过而标记完成，整体目标保持 active。
