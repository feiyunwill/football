# 框架验收 Python 环境修复与架构门禁刷新

归属 ms-19.1 → plan-19.1.2 → task-19.1.2.2，并顺序刷新 ms-20.1 的架构任务。当前系统 Python 3.14 缺少 `pytest` 与项目运行依赖，原生框架回归先在 773/773 项 C++ 测试通过后，因 `No module named pytest` 失败；失败日志保留为 `framework_regression-1790582311814415387.log`。隔离环境第一次复跑又暴露缺少 `cv2`、`gymnasium`，783 个 Python 测试中 75 个失败，失败 XML 随后由正式成功运行覆盖，独立原型输出留在本地忽略阶段 `native-framework-python-env-20260928-a`。

正式 `framework_regression.py` 现在按验收依赖文件内容与 Python ABI 建立独立虚拟环境，安装固定测试依赖及 `pyproject.toml` 对应的运行依赖，执行 `pip check`，并在结果中记录实际包版本。显式 `--python` 入口仍可用于隔离诊断。虚拟环境位于 `/tmp`，不修改系统 Python 或已有 Gym 环境。环境准备与完整测试均是同一正式检查的一部分；依赖安装失败会使门禁失败。

按当前源码重新执行正式任务后，`quality_selftest`、`native_boundary`、`framework_regression`、`state_ownership`、`environment_lifetime`、`simulation_contract`、`architecture_regression` 全部通过。框架回归包括 773 个 C++ 测试、783 个 Python 测试、305 个 Python 子测试、两个种子各 1000 帧的独立进程及快照回放；C++/Python JUnit XML 分别有 773/783 个用例，失败、错误、跳过均为零。完整架构 ASan/UBSan 回归报告 1,632,088 条断言、零跳过。各检查的正式 JSON、命令日志及日志 SHA-256 位于[验收证据目录](../optimization/evidence/)；当前 `quality.py status` 将 ms-19.1、ms-20.1 判为 `verified`。

首次原生边界重建耗时超过外层观察脚本的 300 秒上限，观察脚本终止后实际检查子进程仍继续编译并写出成功日志，但正式证据未更新；在确认原进程终结后，以正式命令重新执行并获得有效清单。未将观察超时或直接指定解释器的原型运行算作正式验收。

下一项是 task-21.1.1.1 真实比赛基准。性能、手感、网络、渲染、AI 与产品发布里程碑仍为 `stale`；这次框架与架构通过不代表它们已经达标。
