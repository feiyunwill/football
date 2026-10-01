# 权威输入窗口验收

对应 `ms-23.1 → plan-23.1.1 → task-23.1.1.1`。入口为 `python3 .project/checks/network_input_window.py`。此检查可单独诊断，但质量编排仍要求 `ms-22.1` 手感里程碑先通过；单独检查通过不等于网络任务或里程碑已验收。

门禁重新构建原生 `ServerInputWindow` 契约，覆盖 1、2、22 个槽位共 18,000 帧，检查 16 帧未来窗口、乱序与重复、冲突/非法数据、槽位回收、已封帧不可修改及固定容量。Python 服务器与 UDP 契约覆盖字节预算、真实 TCP 慢读者写入超时、22 个真实客户端共享未来输入窗口，以及真实 UDP 丢包、重复、乱序和容量退款。原生 TCP/UDP 套件再验证 socket 路径。所有子命令必须成功，且 32 项服务器、27 项 UDP 和至少 37 项原生 socket 测试全部执行，不接受跳过。

2026-10-01 的独立运行通过：原生输入窗口 552,018 项断言，Python 59 项和原生 socket 37 项，总计 552,114。执行日志、报告、命令和 SHA-256 保存在 `.project/optimization/evidence/network_input_window_20261001.tar.gz`。正式任务仍受手感里程碑依赖约束；待手感通过后，由 `.project/quality.py run task-23.1.1.1` 对当前源码重新执行并验证。
