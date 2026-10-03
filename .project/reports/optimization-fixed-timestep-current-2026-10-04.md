# 当前固定步长与节拍验收

归属 `ms-22.1 → plan-22.1.1 → task-22.1.1.1 / task-22.1.1.2`。当前源码的 `python3 .project/quality.py run task-22.1.1.2` 通过；上游输入合同报告有 3,116,103 条断言、零跳过，固定步长检查有 52 条断言、零跳过。

固定步长检查复核了本轮输入报告的 SHA-256、1,177 份源码、62 个二进制、1,004 份依赖和 206 件运行产物。它同时核对 Release 与 ASan/UBSan 的原生 50 Hz 比赛、发布时钟、离线输入时间线和逐帧回放，以及 36 个 Python 节拍测试。真实产品入口均通过持续按键与重置边沿检查；TCP 和 UDP 分别保存 514 与 517 个权威帧，两种构建各自回放全部 1,031 帧。

正式回执为 [`input_contract.json`](../optimization/evidence/input_contract.json) 和 [`fixed_timestep.json`](../optimization/evidence/fixed_timestep.json)，日志名称及哈希由回执给出。可提交的完整报告副本为 [`input_contract_current_20261004_report.json.gz`](../optimization/evidence/input_contract_current_20261004_report.json.gz)（SHA-256 `cf9f03278a6b028e05d8c2d16e062db3b8e54f48ed8e8d120783cc0143b47b82`）和 [`fixed_timestep_current_20261004_report.json.gz`](../optimization/evidence/fixed_timestep_current_20261004_report.json.gz)（SHA-256 `b9f4a1139bbd2694df25d88ab63e0232aa1950e3277b914f2ea228537e0650d1`）。

本门禁证明节拍、物理步数和输入边沿的当前实现，不构成设备到球员响应延迟或渲染性能验收。下一项为 `task-22.1.2.1` 的平滑与暂停恢复；`ms-22.1` 仍需后续任务通过。
