# 原生执行恢复、比赛与图形验收 — 2026-09-10

本轮恢复了真实 Arch Linux、GameEnv、SDL/EGL 执行，修复运行暴露的缺陷，并完成此前待执行的原生比赛、恢复、录制和持牌检查。工程继续按里程碑→计划→任务推进；局部通过不代表产品阶段完成。

## 实现审查与修复

| 环节 | 实际问题与影响 | 当前实现与验证 |
| --- | --- | --- |
| 框架／绑定 | 场景的 `left_team/right_team` 被 STL 转换为 Python 副本；`AddPlayer` 追加后原生球队仍为空，实际比赛 reset 失败 | `engine/ai.cpp` 将 FormationEntry 向量注册为 opaque 容器，返回保活引用；序列赋值先验证全部元素再提交。新增原生检查覆盖 11v11、元素修改、追加、删除、赋值失败原子性及生命周期 |
| 架构／可选依赖 | 安装了 Gym 或原生库后，纯存档／网络导入仍提前加载它们 | 清理四个旧门面中已无活跃调用的原生导入；根包使用幂等 Gym 注册回调，环境入口显式注册，setup 与 pyproject 声明实际插件元数据。两种新进程导入顺序均通过 |
| 网络／渲染启动 | SDL 初始化持有 GIL，Python 心跳线程超过空闲期限，图形启动或暂停测试断线 | `start_game` 绑定释放 GIL；真实图形比赛与本地暂停回归通过 |
| 渲染／帧读取 | 窗口交换后才读回缓冲，无法保证读取刚绘制的帧 | 在 `SDL_GL_SwapWindow` 前执行像素读取，保留像素打包对齐保护 |
| 渲染／插值与 HUD | 先计算投影再更新 FOV，使用上一帧视场角；恢复显示与清除 HUD 后像素不一致 | 相机先设置当前 FOV 再创建投影；5 项真实图形检查全部通过，包括纠正 alpha=0 和 HUD 清除后的逐字节图像一致性 |
| 录制／数值边界 | 原生角色枚举形成 object 数组，被有界录制器拒绝，环境与回放检查出现 9 个错误 | 环境观察显式转换角色为整数；174 项录制、回放与引擎池检查通过 |
| 验收／线程所有权 | 两个原生重连用例从测试线程读取服务端引擎摘要，违反已有所有者约束 | 通过服务端任务队列在所有者线程读取；保留实际恢复状态摘要比较，生产所有权检查保持启用 |
| 验收／UDP 边界 | 2007 字节测试包在本机路径中未抵达接收 socket，不能用于断言应用已计数拒绝 | 保留大包案例，增加实际可抵达的 1201 字节包，验证协议 1200 字节边界；223 项重连与网络回归通过 |

修改前代码均按项目规则保留日期与原因注释。没有进行 Git 操作、委派子代理、重置 WSL 或变更用户服务。

绑定修复与 pybind11 对 STL 自动复制及 opaque 容器的说明一致；读回顺序依据 SDL 的双缓冲窗口交换语义。[pybind11 STL 文档](https://pybind11.readthedocs.io/en/stable/advanced/cast/stl.html)、[SDL_GL_SwapWindow 文档](https://wiki.libsdl.org/SDL2/SDL_GL_SwapWindow)

## 当前验收证据

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 完整比赛、TCP/UDP 多人、暂停、图形、保存继续与回放 | 392 项通过，包含 13 项真实比赛／图形检查，零跳过 | [比赛报告](../optimization/benchmarks/native-full-match-20260910-b/report.json) |
| 录制、回放、目录、原生引擎池与渲染切换 | 174 项通过，包含此前待执行的 28 项环境／原生／渲染检查；池 live/leased/idle 均为 0 | [资源报告](../optimization/benchmarks/native-recording-pool-20260910-b/report.json) |
| TCP/UDP 自动恢复及受影响回归 | 223 项通过，包含 4 项真实 GameEnv 检查，零跳过 | [恢复报告](../optimization/benchmarks/native-reconnect-udp-20260910-b/report.json) |
| 原生骨骼附件、裁判持牌与中间帧 | 439 条断言、8 种持牌组合、6 张真实图像通过 | [持牌报告](../optimization/benchmarks/native-render-pose-20260910-b/report.json) |
| 惰性 Gym 注册与实际包元数据 | 11 条断言通过；Gym 先导入、数据模块先导入均可注册且重复调用幂等 | [注册报告](../optimization/benchmarks/native-gym-registration-20260910-c/report.json) |
| 工具链、依赖、实际共享库及正式状态 | 记录环境和二进制摘要；暂存库与编译输出完全相同 | [运行清单](../optimization/benchmarks/native-runtime-manifest-20260910-a/report.json) |

这些套件存在覆盖交集，不能相加称为独立用例总数。全部当前报告重新核对了 693 条源码、461 条资源、15 份日志、6 张图像、10 个元数据文件及 5 个二进制文件记录。源码条目数也包含跨报告重复。归档核对在 Linux 中完成，包含资源符号链接。[汇总证据](../optimization/benchmarks/native-recovery-evidence-20260910.json)

汇总 SHA-256：`3ca498e4bb701c8be582b20044de455a9ef07e2fd6fa8dcc508eb38ba2ba1e0e`。C++ 核心：`e53d581e0be2c6a393e30a1b3e4b2b4386cbd2203afd1cd41b7467b87863434d`；Python 绑定：`e25ba6214f27b8edaecc73043eb126718f3d098cba85ed6ee79539dadbcedc2d`。

早期失败日志和报告保留原样。本轮第一次完整比赛报告因导入边界失败；第一次录制报告因角色枚举失败；第一次恢复报告因测试所有权和 UDP 包抵达条件失败。上表仅引用修复后的通过版本。旧的 Windows 报告及修复前的原生结果不自动作为当前代码的通过证据。

## 执行环境与复验入口

实际环境是 Arch Linux／WSL2、Python 3.14.7、GCC 16.1.1、glibc 2.44、NumPy 2.5.3、OpenCV 5.0.0、Gym 0.23.1，C++23 Release，编译并发固定为 `-j1`。通过 WSL 系统发行版启动自己持有的 `nsenter` 进程，进入实际 Arch 的 mount/pid/root；没有向用户 shell 注入命令。普通发行版启动故障未宣称修复。[WSLg 系统发行版说明](https://github.com/microsoft/wslg/blob/main/CONTRIBUTING.md)

实际运行路径：

```text
解释器 /tmp/football-optimization-python/bin/python
编译目录 /tmp/football-optimization-native
PYTHONPATH=/tmp/football-native-python-20260910-d:/root/work_space/football
GFOOTBALL_DATA_DIR=/root/work_space/football/engine/data
GFOOTBALL_FONT=/root/work_space/football/third_party/fonts/AlegreyaSansSC-ExtraBold.ttf
```

暂存包使用实际 `engine/__init__.py`、构建生成的 `libgame.so`（按包入口命名为 `_gameplayfootball.so`）及 `libfootball_engine.so`。没有替身原生模块。最终持牌契约会将 CMake 的 `BUILD_PYTHON_BINDINGS` 切为 OFF；已编译的绑定与暂存副本仍一致。后续修改绑定时需要重新以 ON 配置和编译，不能复用旧库。

在上述 Linux 环境与项目根目录下，使用唯一的新输出目录运行以下探针；命令中的目录名用于下一次复验，尚未执行：

```bash
/tmp/football-optimization-python/bin/python .project/checks/frame_replay_probe.py --match --multiplayer --udp-multiplayer --graphics --native --output .project/optimization/benchmarks/native-match-next
env -u DISPLAY /tmp/football-optimization-python/bin/python .project/checks/python_recording_probe.py --environment --replay --native --rendering --output .project/optimization/benchmarks/native-recording-next
/tmp/football-optimization-python/bin/python .project/checks/python_reconnect_probe.py --native --udp-resume --output .project/optimization/benchmarks/native-reconnect-next
/tmp/football-optimization-python/bin/python .project/checks/render_pose_contract.py --build /tmp/football-optimization-native --output .project/optimization/benchmarks/native-pose-next
/tmp/football-optimization-python/bin/python .project/checks/gym_registration_probe.py --output .project/optimization/benchmarks/native-registration-next
```

图形比赛使用实际 WSLg SDL 窗口；录制池和持牌探针移除 DISPLAY，使用实际 EGL/OpenGL。上述命令要求已提供列出的环境变量及有效原生构建；不代表已完成可安装产物验收。

## 里程碑→计划→任务的后续工作

- **ms19.1 → plan19.1.2 → task19.1.2.1／19.1.2.2**：绑定与可选导入缺陷已修复。仍需确定可安装的依赖组合、跑公开 Gym API 与构建矩阵，再更新正式框架证据。项目声明的 `gym<=0.21.0` 在当前 Python 上安装失败；本轮实验安装 Gym 0.23.1 后仍有 6 项既有 Gym／wrapper 检查因公开 `gym.make("gfootball:...")` 入口失败。这些问题保留为待办，注册探针不宣称依赖兼容验收通过。
- **ms20.1 → plan20.1.1 → task20.1.1.2**：原生创建、关闭、池回收已有实际证据；继续审查 `Gui2Caption::SetCaption/Redraw` 与 Python reset 的异常路径，确认 tracker 嵌套计数和 SDL surface 的异常释放。
- **ms21.1 → plan21.1.2 → task21.1.2.1**：有界网络、存档、录制及实际恢复通过本轮局部回归；继续真实状态字节预算、最长回放、长时 RSS 与 p99。数据包故障测试不是 WAN 或性能达标证明。
- **ms22.1 → plan22.1.2 → task22.1.2.1**：真实暂停 HUD、插值、恢复像素及持牌通过；继续物理输入设备、输入到显示延迟及网络不规则到帧下的视觉连续性。
- **ms23.1／ms24.1**：继续 C++ 通用传输与 Python 比赛 v6 的明确互通边界、真实网络故障矩阵，以及长期渲染性能与图形质量验收。
- **ms25.1 → 两个计划的四个任务**：战术接入、决策稳定性、训练恢复及对照验收继续按既有任务推进；本轮比赛能运行不代表 AI 产品验收已通过。
- **ms26.1 → plan26.1.1／26.1.2**：完整用户场景、长时测试、可安装产物与发布审查仍需完成。

实际 `quality.py status` 将 ms19–26 的旧证据均判为 stale；`quality.py next` 返回 `task-19.1.1.1`。更新正式证据必须从当前依赖链按序执行，不能把本轮局部 JSON 当作通过凭据。`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 的 ready 均保持 false。自动优化目标继续有效。
