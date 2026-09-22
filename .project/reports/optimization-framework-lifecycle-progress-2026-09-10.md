# 框架门禁、reset 原子性与当前安装包

2026-09-10。本轮修复了一个实际原生状态污染问题，恢复了当前打包实现对应的边界门禁，并完成框架和架构的正式依赖链。`ms-19.1`、`ms-20.1` 当前为 `verified`；`ms-21.1` 至 `ms-26.1` 仍为 `stale`，整体产品目标继续推进。下一项正式任务是 `task-21.1.1.1`：真实比赛基准。

[当前正式证据](../optimization/benchmarks/native-formal-evidence-20260910/report.json)保存了七个门禁的记录、日志、两个 JUnit 报告、1,123 个源码指纹、18 个实际二进制指纹及构建配置。状态由原有质量程序验证，未手动放行就绪标志，也未执行 Git 操作。

[最终完整性复核](../optimization/benchmarks/native-formal-evidence-20260910/integrity.json)校验了 1,921 个唯一路径，包含当前源码、归档记录、二进制、安装文件、字体与新分发包。在当前 Linux 环境运行 `python3 .project/optimization/benchmarks/native-formal-evidence-20260910/verify.py` 可重复这项指纹检查；它不重跑测试，也不授予新的验收状态。

## 实际修复

[Python 原生 reset 适配器](../../engine/ai.cpp)在调用公共原生 reset 之前，先把当前帧设为 -1 并增加 tracker 禁用层数。因此，非法场景参数虽然被校验拒绝，已经开始的比赛仍被改变。[实际复现](../optimization/benchmarks/native-invalid-reset-20260910-c/run.log)显示当前帧从 2 变为 -1，状态摘要发生变化。最初探针使用了不存在的构造器，随后使用正确的 `ScenarioConfig.make()`；另一次探针仍处于开球前的 -1 帧，不能证明原子性，相关日志均保留。

适配器现在直接调用公共 reset，由公共入口负责所有者上下文和参数校验，不提前写入帧号或 tracker。[公共 reset](../../engine/src/game_env.cpp)也把渲染历史失效操作移到参数校验之后，防止无效参数清掉已经捕获的展示姿态。成功 reset 的既有 tracker 禁用语义保留；本轮没有将嵌套计数直接改成布尔值。

- Python 生命周期检查新增每轮 6 条不变量，四轮共增加 24 条：已离开开球阶段、非法参数被拒绝、帧号/摘要/比赛状态保留、下一步正常推进。
- 原生 EGL 生命周期检查对非法场景和非法节拍分别检查拒绝、帧号、摘要、tracker 深度及继续使用已有插值姿态，共增加 10 条。门禁最低要求从 390 提高到 424。
- 这些验证使用实际 GameEnv；原生 EGL 检查在普通构建、LeakSanitizer 和全引擎 ASan/UBSan 下均通过。

## 框架验收的修正

[native_boundary.py](../checks/native_boundary.py)原先通过 AST 查找 `CustomBuild.run_unix` 和旧复制函数，已经不适用于上一轮的 PEP 517 构建实现。现在直接重定位实际绑定、核心库和当前包加载器，从无关目录启动隔离 Python，去除 `PYTHONPATH`、`LD_LIBRARY_PATH` 和 `LD_PRELOAD` 对结果的影响。

检查不仅验证模块导入成功，还读取 `/proc/self/maps`，确认进程实际加载的是重定位目录中的核心库，并检查包/旧模块别名、类型身份及枚举 pickle。真正的 wheel 构建和安装由单独的安装探针验证，未用库复制冒充安装测试。绑定配置显式选择当前 Python 和已安装的 pybind11 3.1.0，无需触发 Git 获取。

[framework_regression.py](../checks/framework_regression.py)改为使用当前独立测试环境，并为完整 Python 套件暂存本轮编译的绑定、核心库和加载器，记录它们的真实路径和摘要。它不再自动向旧 Gym 实验环境安装依赖，也不会悄悄使用旧 wheel 中的核心库。门禁指纹增加了现有包加载器和实际被测试的 Python 源码范围。

第一次正式矩阵运行了 528 项 C++ 测试，其中 7 项失败。它们把方向值 5、10 或随帧数不断增大的坐标当作合法输入，碰到了已有 `[-1, 1]` 校验；部分录制测试还忽略了 `RecordFrame` 的失败返回值。修正测试数据后，回滚仍使用与预测相反的方向并检查精确结果；回放仍验证全部 50/100 帧及中间定位，另增加逐帧录制成功和方向往返断言。生产输入/容量校验保持不变，没有删除或跳过这些测试。

修改集中在 [frame_sync_test.cpp](../../engine/tests/frame_sync_test.cpp)、[engine_integration_test.cpp](../../engine/tests/engine_integration_test.cpp)和 [phase16_integration_test.cpp](../../engine/tests/phase16_integration_test.cpp)。[首次失败的 JUnit](../optimization/benchmarks/native-framework-formal-20260910-a/framework-ctest.xml)和完整日志保留。

## 正式里程碑 → 计划 → 任务结果

| 层级 | 当前证据 |
| --- | --- |
| ms-19.1 → plan-19.1.1 → task-19.1.1.1/2 | 质量状态机 42 项自测通过 |
| ms-19.1 → plan-19.1.2 → task-19.1.2.1 | 7 个原生可执行目标和核心库无 Python 链接依赖；原生编译不包含适配器/头文件；重定位包契约通过 |
| ms-19.1 → plan-19.1.2 → task-19.1.2.2 | 134 个 Debug 编译单元无强制发布优化；无 PCH 的 528 项 C++ 测试通过；758 项 Python 测试及 290 项子测试通过；两个种子各两个独立进程运行 1000 帧并通过快照回放 |
| ms-20.1 → plan-20.1.1 → task-20.1.1.1 | 两个种子的真实状态所有权契约共 8,190 条断言通过 |
| ms-20.1 → plan-20.1.1 → task-20.1.1.2 | 424 条生命周期断言通过：普通 headless 167、LSan headless 167、LSan EGL 19、启动失败 LSan 11、Python 原生适配器 60 |
| ms-20.1 → plan-20.1.2 → task-20.1.2.1 | 正常/反向/实际渲染组合共 3,568 条仿真与快照断言通过 |
| ms-20.1 → plan-20.1.2 → task-20.1.2.2 | 全引擎 134 个编译单元带 ASan/UBSan；34,562 条断言通过，包含动画元数据、生命周期、快照、并发实例、双 EGL、真实 SDL 事件和错误字体/上下文路径；无 sanitizer 错误，无抑制规则 |

所有正式检查零跳过。套件和断言存在重叠，不将它们相加为独立测试总数。C++/Python 单元套件中的替身引擎合同，与实际原生契约分开计量；完整 Python 测试使用 checkout 源码及本轮编译的原生库。

普通构建的重复重启测量在预热后与最终均为 152,743,936 字节；全引擎 ASan 重复/并发实例测量从 328,728,576 降至 327,393,280 字节。这些是指定周期与进程的资源证据，不能替代长时整机 RSS 或 p99 验收。实际 EGL 渲染器报告为 llvmpipe，SDL 使用 offscreen 驱动创建真实窗口上下文与事件队列；本轮未评估 GPU 吞吐或物理设备延迟。

## 包含修复的新产物

从当前 sdist 重新编译的 [Linux CPython 3.14 wheel](../optimization/benchmarks/native-package-build-20260910-d/wheel/gfootball-2.10.3-cp314-cp314-linux_x86_64.whl)大小为 10,922,855 字节，SHA-256：`9459f0caa8e6f0bd066384e4daa3b4be7fa5639acde4ae758d0d0c5819bb0f67`。

[源码包](../optimization/benchmarks/native-package-build-20260910-d/sdist/gfootball-2.10.3.tar.gz) SHA-256：`45b9fc28a1c977cbabed8e9effae3d329d65ba531196472c316db70199355c38`。[构建报告](../optimization/benchmarks/native-package-build-20260910-d/report.json)记录 582 个捕获输入、381 个 sdist 原生输入和单并发 C++23 Release 构建，均与当前源码相符。

[全新环境安装报告](../optimization/benchmarks/native-package-install-20260910-d/report.json)验证了全部声明依赖、pip check、15 项实际原生 API 测试、29 条注册断言、8 条加载顺序断言及 4 条 SDL 断言。没有安装旧 Gym，默认资源和字体来自已安装包，测试从源码目录之外以 `python -I` 执行。[终局画面](../optimization/benchmarks/native-package-install-20260910-d/terminal-rgb.png)用于读回契约，不代表产品画质验收。

[已安装库的 reset 复查](../optimization/benchmarks/native-wheel-reset-20260910-d/report.json)另执行 60 条无窗口生命周期断言和 9 条 EGL 断言，确认无效 reset 保留状态及展示姿态。无窗口测试通过 `/proc/self/maps` 确认核心库来自新安装目录；其数据与字体也显式指向同一安装包。核心库 SHA-256 为 `a13016bfb16af7658812330c66f0ee99189d0f69f395b63530906ee9e52b62b8`，绑定为 `13f25b6ea8fb3a1bda69dbd6163508eec1bef1a41d25e3bff99c241187365cc3`。

上一轮 c 包和 392/174/223 套件记录保留为历史。本轮原生源码已改变，旧聚合指纹会按设计失效，不能继续称为当前二进制的证据。本轮完整框架套件和新包测试承担对应的当前验证；没有无条件重复无关的纯文件/容量检查。

测试环境初次安装因 `/tmp` 的 7.7 GB 内存盘耗尽而失败。确认无所属进程后，仅删除本任务已停用的 a/b 安装环境和未完成环境，保留 wheel、源码分发包及失败日志；最终 c 环境保留。新测试环境、d 包构建和安装位于 `/root/.cache/football-quality-20260910/`，临时文件也使用该磁盘目录。[环境创建与清理记录](../optimization/benchmarks/native-formal-environment-20260910-b/commands.json)可核查。

## 已发现、仍需完成的事项

1. `task-21.1.1.1` 先刷新真实比赛基准，再继续状态字节预算、长时 RSS/p99 和后续容量验收。
2. [Humanoid::NeedTouch](../../engine/src/onthepitch/player/humanoid/humanoid.cpp)把 `anim->GetOutgoingVelocity() != e_Velocity_Idle` 的布尔值传给 `FloatToEnumVelocity`。输入只能是 0/1，而 [速度分档阈值](../../engine/src/gamedefines.hpp)为 1.8，故首个分支恒不触发。这是源码可证明的行为问题，本轮未修改；后续需结合真实动画/控球场景验证修正对球员响应的影响，归入 task-22.1.2.2 与 task-25.1.1.2。
3. HUD caption 的原始 SDL surface 所有权和 tracker 异常嵌套路径仍需单独注入失败验证；本轮门禁未证明这些任意分配失败路径安全。
4. editable 安装、支持版本/发布矩阵、C++ 与 Python 比赛协议互通、现代训练栈和 AI 对照验收尚未完成。

旧 C++ 速度表达式、setuptools 元数据以及 Mesa 驱动仍产生已归档的警告。本轮没有宣称零警告或所有环节已达产品质量。
