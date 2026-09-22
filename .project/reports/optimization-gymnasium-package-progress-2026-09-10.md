# Gymnasium、原生安装包与当前回归实施记录

2026-09-10。本轮解决了旧 Gym 依赖无法安装、公开环境入口不兼容及 wheel 重复加载原生扩展三个实际问题。当前源码已从 sdist 编译成 Linux wheel，在全新虚拟环境安装全部声明依赖，并从源码目录之外运行真实 GameEnv、SDL/EGL 和 Gymnasium 检查。整体产品验收继续进行。

本记录更新上一轮[原生恢复报告](optimization-native-recovery-progress-2026-09-10.md)中的依赖和安装状态。旧报告、失败日志及代码注释保留为历史，不能代替当前证据。

## 对应里程碑、计划和任务

| 里程碑 → 计划 → 任务 | 本轮实现或验证 | 尚需完成 |
| --- | --- | --- |
| ms-19.1 → plan-19.1.1 → task-19.1.1.1/2 | 在实际 Linux 刷新质量状态机 42 项自测，两个任务的正式证据有效 | 下一项为 task-19.1.2.1 |
| ms-19.1 → plan-19.1.2 → task-19.1.2.1/2 | 必需的原生扩展、隔离构建、相对导入与兼容模块别名；实际 C++23 Release 单并发编译 | 原生边界、Debug、无 PCH 与独立进程确定性的完整正式矩阵 |
| ms-20.1 → plan-20.1.1 → task-20.1.1.2 | 工厂包装失败释放、Gymnasium 异常终止、种子隔离与两个环境并行运行；录制/池回归 174 项 | tracker 嵌套计数、HUD surface 异常路径、长期原生资源检测 |
| ms-21.1 → plan-21.1.2 → task-21.1.2.1 | 最终 wheel 原生库上的比赛 392 项、录制 174 项、恢复 223 项 | 状态字节预算、长时 RSS/p99、C++ 与 Python 比赛协议互通 |
| ms-22.1 → plan-22.1.2 → task-22.1.2.1 | 392 项含 5 项真实图形检查；安装后的终局 RGB 帧与 SDL 人类模式通过 | 设备延迟、不规则到帧连续性及长期性能 |
| ms-26.1 → plan-26.1.2 → task-26.1.2.1 | 从实际 sdist 编译 wheel，全新目录安装、资源定位和加载顺序验证通过 | editable 安装、支持版本矩阵、诊断与构建信息整合、上游任务全部通过 |

所有里程碑 ms-19.1 至 ms-26.1 的正式状态仍为 `stale`，不能因为局部安装成功而标为产品完成。`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 和 `product_package` 的就绪状态未人为放行。没有执行 Git 操作。

## 接口与生命周期

[gfootball/gymnasium.py](../../gfootball/gymnasium.py) 提供真正的 Gymnasium 环境，遵循 reset 返回 `(observation, info)`、step 返回五元组的协议。使用方式及与旧工厂的边界见 [Gymnasium 使用说明](../../gfootball/doc/gymnasium.md)。接口调整依据 [Gymnasium 官方迁移指南](https://gymnasium.farama.org/introduction/migration_guide/)及 [v1.3.0 核心实现](https://raw.githubusercontent.com/Farama-Foundation/Gymnasium/v1.3.0/gymnasium/core.py)。

- 入口为 `gymnasium.make("gfootball.gymnasium:GFootball-11_vs_11_easy_stochastic-SMM-v0", ...)`。根包保持轻量；显式模块导入负责注册，重复注册幂等，不注册场景测试子包。
- 环境自身 RNG 生成原生种子，显式 seed 重置场景序列。发现并修复构造阶段消耗调用方全局随机状态的问题；相同 seed 的观察和完整原生状态摘要可以复现。
- 原生比赛结束返回 terminated，外部 TimeLimit 负责 truncated。单个策略控制同一队 1 至 11 人；多球员奖励取均值，逐人奖励放入 `info["agent_rewards"]`。参数和动作在改变环境之前验证。
- `human` 与 `rgb_array` 的返回行为明确，终局仍可读回画面。reset/step/render 异常触发中止释放；二次清理失败只附加说明，保留初始异常。
- [legacy_api.py](../../gfootball/env/legacy_api.py) 保留项目现有四返回值工厂和包装协议，空间类型来自 Gymnasium。现有回放、录制和比赛消费者继续使用原工厂。旧 `import gym` 注册入口已退役。
- [环境工厂](../../gfootball/env/__init__.py) 对原生环境创建之后的渲染和包装异常执行 `close(finalize=False)`。一次渲染器迁移可能留下有上界的空闲 headless 引擎；测试检查无租约、无空闲 renderer，再关闭池验证归零，不将合法缓存误判为泄漏。

新增 [9 项实际原生契约测试](../../gfootball/test_gymnasium_native.py)，涵盖官方 env checker、种子与全局 RNG、时限与自然终止、失败清理、终局像素、旧工厂快照恢复及 SyncVectorEnv。既有 gym/wrappers 的 6 项公开入口测试也已迁移，安装后的 15 项全部通过。旧 TensorFlow 1 / Baselines / 可选 RLlib 示例尚未完成现代训练栈迁移，不能以环境兼容代替 AI 训练验收。

## 构建与加载

[setup.py](../../setup.py) 的扩展名与实际包路径一致，为 `gfootball_engine._gameplayfootball`。构建走 PEP 517 隔离环境，调用 CMake C++23 Release，只构建必需的绑定目标，单编译任务运行；绑定或核心共享库缺失即失败。依赖与 ABI 标记遵循 [setuptools 扩展模块文档](https://setuptools.pypa.io/en/latest/userguide/ext_modules.html)。

编译输出进入构建目录，再复制 ABI 扩展、核心库与字体。wheel 包含运行资源，不再包含空的可选扩展或原生源码目录；准备元数据不再删除已有本地原生产物。本轮没有用预编译绕过变量代替实际编译。

第一份 wheel 在真实导入时出现 `generic_type: type "FloatVec" is already registered!`。根因是 [engine/__init__.py](../../engine/__init__.py) 用顶层模块导入再由包路径导入，导致同一个扩展初始化两次。现改为包内相对导入，同时为旧模块名保留同一模块对象；遇到已加载的其他安装副本会明确报错。包优先和旧模块优先两种顺序均验证了路径不污染、模块与类型身份一致、枚举 pickle 往返。

`pyproject.toml`、`setup.py`、`requirements.txt` 的运行依赖一致，Python 下限为 3.10，使用 Gymnasium 和 pygame-ce，补齐实际需要的 six；旧 Gym 和运行时 wheel 依赖已移除。实际验证环境为 Python 3.14.7、Gymnasium 1.3.0、NumPy 2.5.3、pygame-ce 2.5.8、OpenCV 5.0.0.93。没有安装旧 Gym，也不需要 setuptools 为旧 Gym 补 distutils。

## 产物与自动证据

最终产物：

- [Linux CPython 3.14 wheel](../optimization/benchmarks/native-package-build-20260910-c/wheel/gfootball-2.10.3-cp314-cp314-linux_x86_64.whl)，10,923,119 字节；SHA-256 `29101c1c3fcc679d7b232f0c6c83bf8ad6f4b31b6c6bdd66c9f7bfd0eaedc123`。
- [源码分发包](../optimization/benchmarks/native-package-build-20260910-c/sdist/gfootball-2.10.3.tar.gz)；SHA-256 `c8d3e988209626df69cb97ceee8c563663fc6ba68fc98699b2f5f723d4aaf3a8`。
- 原生绑定 SHA-256 `7fbd727facffe81f5f3326222732df36916016d5543b8ed4602875bc296bb80c`；核心库 SHA-256 `0965455c4042d77796c5da53fcb571cd66a029df478e730e9b354c8598e356ea`。

| 证据 | 结果和边界 |
| --- | --- |
| [实际 sdist → wheel 构建](../optimization/benchmarks/native-package-build-20260910-c/report.json) | 582 个捕获的源码输入、381 个 sdist 原生输入与当前源码一致；隔离构建使用 setuptools 84.0.0 / wheel 0.48.0 / pybind11 3.1.0 |
| [全新虚拟环境安装](../optimization/benchmarks/native-package-install-20260910-c/report.json) | pip check 通过；15 项原生接口测试、29 条注册断言、8 条加载顺序断言、4 条实际 SDL 断言；无跳过、失败或残留租约 |
| [当前比赛与图形](../optimization/benchmarks/native-gymnasium-full-match-20260910-a/report.json) | 392 项通过，包含 13 项原生检查，其中 5 项图形检查 |
| [录制与引擎池](../optimization/benchmarks/native-gymnasium-recording-20260910-a/report.json) | 174 项通过；收尾 live/leased/idle 归零，无残留所属线程、子进程或锁描述符 |
| [TCP/UDP 自动恢复](../optimization/benchmarks/native-gymnasium-reconnect-20260910-a/report.json) | 223 项通过；实际 GameEnv 加 Python socket 服务端；未执行 WAN 或 C++ 服务端互通 |
| [正式质量状态机](../optimization/benchmarks/native-gymnasium-quality-20260910-a/quality_selftest.json) | 42 项通过；已刷新两个正式任务，下一项 task-19.1.2.1 |
| [归档完整性](../optimization/benchmarks/native-gymnasium-evidence-20260910/report.json) | 1,850 个唯一路径，包括 6 份报告、21 份日志、7 张图像、源码、资源、已安装文件和原生库，摘要匹配 |

安装测试使用 `python -I`，从源码目录之外加载 site-packages 中的完整 Python 包与原生库，不依赖源码路径或数据/字体环境变量。较大的 392/174/223 套件使用当前 checkout 的 Python 源码和最终 wheel 安装的原生库；每份报告记录实际加载路径、库摘要及随包资源路径。这两种验证范围分别记录，没有混称。

套件相互重叠，不把数量相加成独立测试总数。上轮持牌契约的 439 条断言和 6 张图像按当前未变的 C++ 源码、资源、原始二进制和日志指纹继续有效；本轮未重新执行该独立二进制，也未把它标为当前 wheel 的测试。160×90 [终局 RGB 帧](../optimization/benchmarks/native-package-install-20260910-c/terminal-rgb.png)验证读回契约，不代表产品画质验收。

1 MiB UDP 故障快照本次耗时约 0.506 秒，注入首发丢包 53、重复 43、乱序 37，最大数据报 1200 字节。这是本机功能证据，不能与旧环境耗时直接比较或推导 WAN/p99 提升。

构建 a 的重复原生注册错误、构建 b 的错误空闲池断言和种子测试首次失败日志均保留；最终 c 从修正后的 sdist 重新构建、安装并验证。构建日志仍有 setuptools 元数据弃用和旧 C++ 枚举/浮点诊断；Gymnasium checker 对既有 Simple115 无限 Box 边界有两条警告，没有声称零警告。

可在当前 Linux 工作区重新执行 `python3 .project/optimization/benchmarks/native-gymnasium-evidence-20260910/verify.py` 检查这批证据的指纹；它不会重跑测试或修改正式任务状态。后续源码或临时安装目录变化时校验应失败，届时必须刷新对应证据。

## 后续顺序

先刷新 task-19.1.2.1 的原生边界，再完成框架与生命周期正式依赖链；实际验证 editable 安装，不预设其成功。接着处理 tracker/HUD 异常释放和长时状态/RSS/p99，推进设备输入与不规则到帧渲染、协议互通、AI 训练及发布验收。当前 wheel 是本机 Linux/CPython 3.14 产物，尚不是通用 manylinux 包或支持版本矩阵的验收结果。
