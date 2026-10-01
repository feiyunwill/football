# 网络真实故障回归

`task-23.1.2.2` 使用 `.project/checks/network_regression.py` 作为自动验收入口。门禁从源码构建原生 GameEnv Python 绑定，在真实 loopback UDP socket 上运行两名客户端；服务端和独立副本各自推进比赛，客户端对每一帧核对权威输入和非零状态哈希。40 帧输入按帧变化，两个槽位都不是零输入。一次发送两帧的未来输入，使线路代理能够制造可观察的乱序，而不是仅延迟唯一的在途报文。

| 档位 | 注入 | 验收 |
| --- | --- | --- |
| 基线 | 无代理 | 两客户端各 40 帧权威输入与哈希一致 |
| 延迟与抖动 | 服务端 DATA 报文交替延迟 6/14 ms | 两种延迟均被施加，两个客户端仍逐帧一致 |
| 故障 | DATA 交替延迟 4/10 ms；确定性首次丢包、重复及保留后发 | 丢包、重复、计划乱序及真实出站序号倒置均大于零，两个客户端仍逐帧一致 |
| 断线 | 原生 GameEnv 单客户端自动 token/snapshot 恢复；双客户端真实 UDP 会话恢复 | 原槽位、原 token、新 epoch 与追帧由现有集成测试验证 |

代理只改变服务端到第二客户端的真实 UDP 数据报，保留协议和引擎实现。每帧哈希在独立 GameEnv 上重算；`test_multiplayer_udp` 的双客户端断线测试使用 MatchOracle，因此不能代替原生引擎恢复测试。C++ 原生 TCP/UDP 互操作性另由 `native_session_ports` 等门禁覆盖，本门禁不宣称在 C++ 原生服务端上注入相同故障矩阵。

运行：`python3 .project/checks/network_regression.py`。命令输出 JSON 指向 `benchmarks/network-regression-*` 报告；报告保留命令、日志哈希、故障计数与范围。验收证据归档在 `evidence/network_regression_20261001.tar.gz`。如源码或环境指纹改变，须重新运行门禁，不能复用历史通过状态。
