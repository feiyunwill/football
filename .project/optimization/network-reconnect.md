# 断线与重连门禁

`network_reconnect` 对应 `task-23.1.1.2`。运行 `python3 .project/checks/network_reconnect.py` 会在独立目录配置并构建原生扩展，使用 `.project/checks/requirements.txt` 对应的 Python 环境执行测试，再运行 C++ TCP 客户端重连契约。脚本在任一命令失败、测试跳过、测试数量不足或指定场景缺席时失败。

门禁要求至少 163 项通过：135 项 Python 传输与恢复测试、2 项使用真实 GameEnv 的 TCP/UDP 自动续局测试，以及 26 项 C++ 客户端契约。指定场景覆盖真实 socket 的连接与握手期限、单调时钟 RTT、心跳接收、令牌与全量快照恢复、恢复前的权威帧保护、连续帧哈希、过期请求和旧工作线程清理。原生 GameEnv 测试确认恢复后继续推进 13 帧。

每次运行的命令输出、SHA-256 和汇总报告保存在 `.project/optimization/benchmarks/network-reconnect-*`。`program.json` 记录门禁输入与工具指纹；单独通过门禁只表示这项检查可用，任务还依赖输入窗口和手感里程碑，网络里程碑另需大厅与真实故障矩阵验收。
