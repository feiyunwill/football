# 共享输入验收入口 — 2026-09-13

`input_contract` 已从“实现未就绪”变为可执行检查，首次独立执行完整通过：2150639 条断言、零跳过、耗时 265.016 秒。它现在编译正式源码并重新生成输入、窗口与回放证据，不读取旧阶段的成功结果替代执行。

这对应 **ms-22.1 → plan-22.1.1 → task-22.1.1.1（统一输入采样）**。本次运行直接验证注册检查器；未执行完整前置里程碑链，也未向质量状态写入成功记录。当前 `input_contract` 状态仍为 pending；任务与依赖里程碑因前置源码变化仍为 stale。

## 固定入口

- [检查器](../checks/input_contract.py)：生成新证据目录，单线程构建 Release／ASan，校验编译选项、动态库、源码和工具文件指纹；任何失败或缺失覆盖都会退出非零。
- [Python 输入对照生成器](../checks/native_input_oracle.py)与[Python 行为测试入口](../checks/python_input_probe.py)：执行当前实现，保留固定种子的 20168 次操作及序列化结果。
- [私有 X11 执行器](../checks/native_input_x11.py)与[产品窗口用例](../checks/native_input_window_cases.py)：XTEST 键盘、SDL 虚拟手柄、焦点／断连，以及三个实际产品入口的按键、暂停、换帧、权威输入和保存回放验证。
- [CMake 注册](../../engine/CMakeLists.txt)与[源文件登记](../../engine/sources.cmake)：七个固定合同可执行程序和一个窗口观测模块；通过 `EXCLUDE_FROM_ALL` 避免正常产品构建携带测试目标。
- [正式检查配置](../optimization/program.json)：`input_contract` 为 ready，要求至少 2150000 条断言，3600 秒上限；固定步长、展示平滑、手感和完整网络输入窗口检查仍保留各自未完成状态。

运行单项检查器：

```bash
python3 .project/checks/input_contract.py
```

按任务执行全部前置验收并计算完成状态：

```bash
python3 .project/quality.py run task-22.1.1.1
```

检查器需要 Linux 的私有挂载命名空间，以及 Xvfb／XTEST 测试依赖。可通过 `FOOTBALL_TEST_X11_ROOT` 或 `--x11-root` 指定已准备的依赖根目录。本机使用此前签名校验后解包的私有工具目录；缺失依赖会报错，不跳过。工具文件全部纳入本轮证据指纹，不安装到系统目录。已经安装 xkbcomp 的环境无需私有工具覆盖；缺失时只在子命名空间内建立覆盖。

## 实际覆盖

| 测试 | 每种 native 构建的结果 |
| --- | --- |
| 完整输入／Python 差分 | 92699 条断言；20168 次操作；方向 float32 位、全部按钮、死区、同时按键、短按和释放一致 |
| 帧绑定与有界历史 | 16248 条断言；2000 个权威帧对照；1024 帧历史；等待和回滚恢复不重复取样 |
| 展示所有者模型 | 10102 条断言；1000 个普通逻辑帧及暂停／纠正场景 |
| 服务端未来输入窗口 | 552018 条断言；18000 帧；固定 3728 字节；重复／冲突／非法输入及槽位清理 |
| 真实 GameEnv 输入 | 3901 条断言；778 次单步；82 个确认帧、74 次纠正回滚 |
| 真实 SDL 设备采样 | Release 和 ASan 各 56 条断言；真实 XTEST、虚拟手柄、焦点转移与断连 |
| 共享时钟与实际网络回放 | 各 400291 条断言；40000 个调度事件；逐帧重放本轮 67 个实际确认帧 |
| Python 行为用例 | 共 9 个测试通过 |

框架的 70 个质量自测先行通过。独立的旧帧模拟算法已复制到固定测试夹具，并锁定 SHA-256 为 `78adff3d69ab0d8a133a545495aeeec0a04d9a8194ee90e80b6f36b929d1f590`；正式测试引用当前规范头文件，不再包含阶段目录中的候选实现。

真实 Release 窗口中，单机／TCP／UDP 分别完成 45／41／46 次比赛渲染，全部恰好一次换帧且渲染前后逻辑摘要不变；各自的一次初始化换帧单独保留。TCP 有 33 个确认帧，包含 8 个非零输入帧和 1 帧短按射门；UDP 有 34 个确认帧，包含 9 个非零输入帧和 1 帧短按射门。途中保存的 27／28 帧前缀保持一致。两个实际引擎构建各重放全部 67 个确认帧，全部哈希一致。

已查看三个入口本轮第 40 次换帧的实际图像：[单机](../optimization/benchmarks/native-input-gate-integration-20260913-a/input/x11/windows/standalone/trace/frame-40.png)、[TCP](../optimization/benchmarks/native-input-gate-integration-20260913-a/input/x11/windows/tcp/trace/frame-40.png)、[UDP](../optimization/benchmarks/native-input-gate-integration-20260913-a/input/x11/windows/udp/trace/frame-40.png)。这些软件渲染图像证明实际执行与画面输出，不证明延迟或 GPU 性能达标。

## 证据与限制

- [执行记录](../optimization/benchmarks/native-input-gate-integration-20260913-a/execution/commands.json)：实际检查器退出 0；日志 SHA-256 为 `97ff3150efdcf9417fd55df0b1fd99bb0fa9ef83b289c104d58f4caa8d2725b6`。
- [完整报告](../optimization/benchmarks/native-input-gate-integration-20260913-a/input/report.json)：SHA-256 为 `d5b8c2927888b9a59f9b6d65d84ba907da4bf244e4e98151e6921fe509096e45`。
- [2193 文件 receipt](../optimization/benchmarks/native-input-gate-integration-20260913-a/verification.json)：SHA-256 为 `9dbae1f74d4a2200cc4b00159539ee1fcf9ffa9a540f7e6b54af94796cbac02f`，生成后按固定哈希再次逐文件独立验证。
- 实际 Release／ASan 引擎核心仍分别为 `2836c626...`／`24cccb16...`；原性能基准、默认场景、AI 固定样本和基线归档未更改。
- SDL 采样器在消毒器下执行；三个完整图形程序本轮使用 Release。UDP 服务端仍以 SIGTERM 结束，不能将其视作正常析构与完整异常生命周期的证明。
- 当前逻辑仍为 10Hz，50ms 手感验收尚未通过。整个优化目标保持未完成，完整前置门禁仍需自动重新运行。

## 已核实的节拍升级边界

[Python match_bootstrap](../../gfootball/frame_sync/match_bootstrap.py) 当前为 **v6／FMATCH6**；[match_cadence](../../gfootball/frame_sync/match_cadence.py) 的 v5 文档描述已经落后于控制 epoch 的实际协议。Python 的确认包是 17 字节，包含输入频率、网络频率、物理步数、物理 tick 时长及控制 epoch。

[原生 protocol.hpp](../../engine/src/frame_sync/protocol.hpp) 当前仍为 v2。消息编号 15 在原生表示 DeltaAuthoritativeFrame，在 Python 表示 MatchReconnectRequest，因此升级必须按真实协议处理，不能只同步版本常量或沿用旧上下文中的“Python v5”。

下一步先建立 50Hz／每帧 2 个 10ms 物理 tick 的明确产品节拍与版本合同，同时处理比赛时长、回放元数据、重连／暂停确认和服务端绝对截止时间。原始 10Hz 性能基准继续保留独立身份；完成实际球员响应测量前，不将频率变更当作手感达标。
