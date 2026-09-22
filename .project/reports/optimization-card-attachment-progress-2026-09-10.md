# 优化进展：裁判持牌与显示附件

2026-09-10。对应 ms22 → plan22.1.2 → task22.1.2.1。本轮修复持牌插值的源码缺陷，建立独立原生验收入口，并重跑比赛回归。原生代码尚未编译，原生契约和图像检查尚未执行，平滑任务继续未完成。

## 发现与实现

审查 [Officials](../../engine/src/onthepitch/officials.cpp) 确认三个问题：插值分支直接读取当前动画节点，不能跟随已经插值的蒙皮；红牌分支仍显示黄牌；局部持牌偏移与普通 Put 不一致。旧隐藏逻辑还依赖 previousFunctionType，快照恢复跳过出牌动画时可能保留旧物体。

[HumanoidBase](../../engine/src/onthepitch/player/humanoid/humanoidbase.cpp) 新增只读显示附件查询，[PlayerBase](../../engine/src/onthepitch/player/playerbase.hpp) 对激活人物转发该查询。查询用最后一次 Put 的实际蒙皮关节位置/旋转、fullbody 位移和人物缩放计算世界坐标。它不临时改写逻辑动画节点；缺失关节返回 false，非法部位拒绝，失败时输出参数保持不变。

普通与插值路径共用 `PutCard()`，左右手使用同一局部偏移 `(0.04, 0, -0.25)`，红黄牌分别选择正确几何体。非持牌、缺失关节、颜色切换和恢复到普通动画时隐藏旧物体。

牌色、持牌手、可见性作为固定大小的显示字段保存，不进入 ProcessState。正常端点捕获保存逻辑端点的外观；纠正捕获保存最后实际显示的外观。插值期间保持所捕获的离散状态，alpha=1 切换到目标外观，避免 alpha=0 时牌色或持牌手已经提前改变。人物位置和旋转继续沿既有显示插值路径变化。

[Spatial 的变换设置](../../engine/src/types/spatial.cpp) 会无条件触发递归更新。本次持牌处理仅在位置/旋转变化时设置，并避免每帧把当前牌隐藏后再显示。这消除了明确的重复调用；没有原生耗时或 GPU 测量，不能宣称已达到性能目标。

## 验证与证据

新增 [engine_render_pose_contract.cpp](../../engine/tests/engine_render_pose_contract.cpp)，在 [CMake](../../engine/CMakeLists.txt) 注册独立目标 `engine_render_pose_contract`，链接真实 football_engine。测试通过有限的 friend 夹具选择实际注册的 showcard 及镜像动画，应用真实关键帧，设置受控犯规状态；不重命名共享动画、不使用替代引擎或 renderer。夹具期间不执行物理步进，因此它不验证完整犯规判罚流程。

契约要求正反处理方向、左右手与红黄牌共 8 组组合，并检查位移、90 度旋转的中间姿态、连续纠正、离散外观、缺失关节、无牌状态、恢复原生快照、规范摘要和上下文释放。它还要求保存 6 幅真实中间 PPM 图像。上述要求目前均未执行，不计为通过的测试。

[render_pose_contract.py](../checks/render_pose_contract.py) 提供 Linux 自动入口：C++23、单编译任务、真实 EGL/OpenGL，校验必要组数、图像尺寸/变化、源码及资源稳定性，归档二进制、日志和图像指纹。此入口应纳入后续正式 `presentation_smoothing` 检查；它不能替代暂停恢复、设备输入、长期性能以及既有 11 项比赛/图形原生检查。

```text
python .project/checks/render_pose_contract.py --build /tmp/football-render-pose --output <全新证据目录>
```

| 检查 | 当前证据 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、存档及回放 | 本轮最终重跑 297 项通过，120 个来源文件 | [报告](../optimization/benchmarks/python-card-attachment-match-windows-20260910-b/report.json) |
| 共享网络与恢复 | 复用此前 219 项，44 个来源文件仍匹配，本轮未重跑 | [报告](../optimization/benchmarks/python-render-interpolation-network-windows-20260910-a/report.json) |
| 资源所有权、录制及环境回放组件 | 复用此前 146 项，36 个来源文件仍匹配，本轮未重跑 | [报告](../optimization/benchmarks/python-match-cadence-recording-windows-20260910-a/report.json) |
| 实际资源和 Python 策略读取 | 复用此前证据，21 个来源文件仍匹配，本轮未重测 | [报告](../optimization/benchmarks/python-match-cadence-identity-files-windows-20260910-a/report.json) |

当前比赛回归没有失败、错误、跳过、已检测异步警告、受检工作线程/子进程或目录锁遗留。四份报告及其 221 个来源文件条目、相关日志 SHA256 已逐一核对，见[证据清单](../optimization/benchmarks/python-card-attachment-evidence-20260910.json)。原生源文件出现在指纹中不代表编译或执行过。第一轮同为 297 项通过，但随后修订原生场景更新后其 Officials 指纹过期，已保留为历史并以 b 目录重跑归档。

实际执行环境为 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0。比赛探针原有 39 个文件的 Python 3.9 AST 检查仍通过；新增原生探针也独立通过该语法解析，未执行 Python 3.9。最大原点故障传输仍验证 1 MiB、5 帧及 1200 字节数据报上限；这不是 WAN 或原生性能改善的证据。

## 下一步

执行上述真实原生契约并检查中间图像，处理实际编译或运行暴露的问题；继续权威暂停恢复及输入清理。派生关节位置插值的大动作蒙皮形状、非规则网络到达时的连续性、设备延迟、GPU/RSS 和长期 p99 仍待完成。

本轮没有运行 C++ 构建、GameEnv/SDL 或图像验证，没有新增暂停协议和按键，也未操作 Git、安装依赖或重置 WSL。`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 四个 ready 仍为 false，ms21—ms26 与整体目标继续 active。
