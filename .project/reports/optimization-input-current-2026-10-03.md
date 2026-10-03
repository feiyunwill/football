# 当前源码统一输入采样复验

归属 ms-22.1 → plan-22.1.1 → task-22.1.1.1。2026-10-03 执行 `python3 .project/quality.py run task-22.1.1.1`，正式 `input_contract` 通过 3,073,292 条断言、零跳过；`quality.py verify task-22.1.1.1` 通过。报告覆盖共享 Python／原生输入、真实设备采样器、权威帧与回放，以及展示状态所有权回归。

私有 X11／XTEST 窗口中的 standalone、TCP 和 UDP 产品入口场景均通过；报告确认真实 GameEnv、X11、XTEST 和原生主程序均已执行，窗口服务正常回收。这些结果验证输入语义和回放一致性，`latency_acceptance=false`；50ms 产品手感延迟以及渲染帧时长仍须由后续独立门禁验收。

[完整机器可读报告与 206 份原始产物](../optimization/evidence/input_contract_20261003.tar.gz)已逐文件核对字节数与 SHA-256，原始总量 117,328,864 B。原始报告 SHA-256 为 `c4e5b8c24682e17550f5dcf0e333bf08b32a7445ed11f2c1f31494086b089908`；归档 SHA-256 为 `480303d89599fa4266dde63716389ff3ff891f48b583f4ed959726521c079507`。[正式回执](../optimization/evidence/input_contract.json)及[本次日志](../optimization/evidence/input_contract-1791001887178888894.log)保留检查结果。本任务通过不代表整个手感里程碑或产品优化目标完成。
