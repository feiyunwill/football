# 优化进展：比赛 v5 节拍契约

2026-09-10。对应 ms22 → plan22.1.1 → task22.1.1.2，并继续支撑 ms21 的比赛集成与资源验收。本轮为真实 TCP/UDP 比赛增加了显式节拍和 Ready 确认，限制实时比赛循环的速率，并检查原生适配器每次推进前的配置。完整可移植回归全部通过；正式产品验收仍未完成。

## 已实现

- [match_cadence.py](../../gfootball/frame_sync/match_cadence.py)：不可变契约，10 Hz 输入、10 Hz 权威帧、每帧 10 个物理步、每步名义 10000 微秒。只支持这一组，严格拒绝浮点、布尔、额外/缺失字段及其他值。
- [match_bootstrap.py](../../gfootball/frame_sync/match_bootstrap.py)：比赛版本从 4 升到 5，原点标记改为 `FMATCH5\0`，加入必需 cadence 元数据。完整原点及契约在缓冲进入 ready 前验证；逻辑所有者在创建引擎和恢复前再次校验。旧版本不自动降级，状态文件格式未修改。
- [multiplayer_transport.py](../../gfootball/frame_sync/multiplayer_transport.py)：客户端发送 13 字节 MatchReady，包含版本与完整节拍；服务端只在参数一致后释放 Ready/handback，拒绝旧的一字节 Ready。TCP/UDP 通过现有共同协议层执行同一检查，恢复也需要重新确认。
- `MatchServerRuntime.run_loop()` 和比赛客户端逻辑循环要求 10 Hz；通用 v2/v3 API 仍允许原有可配置速率。手动步进、快速测试及回放保持原来的模拟帧定义，不承诺墙上时钟同步。
- [match_identity.py](../../gfootball/frame_sync/match_identity.py)：原生适配器每次推进前检查所有者、物理步数、渲染角色和分辨率，不在步进路径重哈希文件。初始化、调度默认值和配置检查共用契约；兼容性指纹新增契约源码，因此旧原生版本存档可能在身份检查处被拒绝。

协议布局、报文向量、拒绝边界和运行约束详见[节拍文档](../../gfootball/doc/match_cadence.md)。源码修改保留带日期和原因的原代码注释。没有执行 Git 操作、安装、C++ 构建或 WSL 重置，没有调整正式验收阈值或 ready 标志。

## 当前证据

环境为 Windows Python 3.14.6、NumPy 2.5.1、OpenCV 5.0.0。测试使用明确的独立归约器及适配器夹具，实际执行 TCP/UDP socket、线程和文件；没有伪造 GameEnv 导入。

| 检查 | 当前结果 | 归档 |
| --- | --- | --- |
| 比赛、图形协调、存档与回放 | 283 项通过，98 个来源文件 | [报告](../optimization/benchmarks/python-match-cadence-match-windows-20260910-a/report.json) |
| 共享 TCP/UDP 和自动恢复回归 | 219 项通过，44 个来源文件 | [报告](../optimization/benchmarks/python-match-cadence-network-windows-20260910-a/report.json) |
| 引擎资源所有权、录制和环境回放组件 | 146 项通过，36 个来源文件 | [报告](../optimization/benchmarks/python-match-cadence-recording-windows-20260910-a/report.json) |
| 实际资源和 Python 策略文件读取 | 上限检查通过，21 个来源文件 | [报告](../optimization/benchmarks/python-match-cadence-identity-files-windows-20260910-a/report.json) |

三套测试均无失败、错误、跳过、受检工作线程遗留或已检测异步警告。比赛与录制检查的受检子进程及目录锁均归零；录制检查的共享池 live/leased/idle 为零。源码与日志 SHA256 已逐一验证，汇总见[证据清单](../optimization/benchmarks/python-match-cadence-evidence-20260910.json)。以前固定节拍阶段的相关源文件指纹现已过期，旧报告仅保留为历史。

新增 13 项必需检查涵盖严格字段与独立十六进制向量、逐字节分片、旧版本/旧 Ready/错误确认拒绝、原点在客户端引擎创建前拒绝、恢复参数变化在原引擎反序列化前拒绝、TCP/UDP 正常恢复与结束、运行时频率覆盖拒绝，以及原生适配器在步进中不读取身份文件。既有两种公开比赛服务端循环也改为实际 10 Hz 执行。

初次开发测试发现测试代码误用了失败阶段名、不存在的打包助手和无布尔返回值的结束接口，已按实际 API 修正。UDP 客户端关闭 socket 后，服务器默认需 3 秒检测空闲，原测试设置的 2 秒恢复期限不足；新测试使用 6 秒总恢复窗口，保留真实空闲检测，没有注入服务端断开。最终新增组及身份组共 36 项先通过，之后整套回归重跑通过。

资源读取实际处理 90,974,146 字节，6.036 秒，Python 峰值 1,155,745 字节，单次读取上限 65,536 字节；Python 策略处理 383,500 字节。测量与回归并发运行于 Windows UNC，不是原生 RSS/GPU 指标，也不作为性能改善结论。本轮没有重新测量实际时钟延迟；上一轮时钟数据是历史观察，不能替代当前原生或端到端验收。

## 未完成项与下一步

`memory_budget`、`input_contract`、`fixed_timestep`、`presentation_smoothing` 四个 ready 标志仍为 false。ms21—ms26 没有因局部测试通过而完成。

真实 GameEnv 比赛/图形组共 10 项，以及另 28 项环境/原生/渲染检查，仍未执行。本轮在已有原生检查中增加了修改 physics_steps 后推进失败且摘要不变的断言，该断言同样未执行。C++ 源码显示 Match::Process 使用 10 ms 时间推进，Python 适配器的实际运行仍须原生验证；36 项 Python 3.9 AST 检查也不代表执行过 Python 3.9。

C++ 通用 `protocol.hpp` 仍声明版本 2，消息表与 Python 比赛扩展不同，不能宣称已有 v4/v5 比赛互通。额外审查发现 `asio_server_engine.cpp` 的 VersionNegotiate 分支当前只解码并记录版本，未在该分支核对支持范围；这一入口的兼容性防护及实际构建测试需在网络里程碑继续处理。本轮没有修改 C++ 协议。

接下来推进 task22.1.2.1：核对原生 PrepareRender、相机与动画现有时刻模型，实现暂停恢复和展示平滑；继续保证已发送输入不可被重新采样、回滚边沿不重复消费。网络暂停必须有权威状态语义，不能仅暂停客户端副本。真实设备输入、SDL/GPU、原生步数、广域网、长期 p99/RSS、AI 及发布验收继续按既有里程碑推进。整体目标保持 active。
