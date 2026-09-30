# 当前源码的输入与固定步长验收

归属 `ms-22.1 → plan-22.1.1 → task-22.1.1.1 / task-22.1.1.2`。`python3 .project/quality.py run task-22.1.1.1` 在本轮源码上完成：`input_contract` 产生 42 项结果、3,084,908 条断言、零跳过。Release 和 ASan/UBSan 的原生合同均通过；实际 SDL/X11 单机、TCP、UDP 产品入口完成键盘采样、持续输入、松键、失焦、暂停与恢复检查。TCP/UDP 分别保存 509/510 个确认帧，两种引擎各自逐帧重放全部 1,019 帧。

新建的 [`fixed_timestep.py`](../gates/fixed_timestep.py) 不用过期历史结论代替执行。它先要求框架和输入门禁的当前指纹、日志哈希均为 `verified`，随后复核输入报告的 SHA-256、1,145 份源码、62 个二进制、1,004 份 X11 依赖及 206 件运行产物。它要求两种构建各自通过原生 50 Hz 比赛合同、6,000 帧发布时钟、30,003 帧离线输入时间线和真实引擎回放；检查单机及两个网络入口持续按住无空帧，松键、失焦、暂停、恢复后重新按键的权威输入都达到明确的帧数条件。它还检查本轮框架 JUnit 中 36 项 Python 节拍、协商与停顿回归，没有失败或跳过。

`fixed_timestep` 已在 [`program.json`](../optimization/program.json) 注册为正式检查。`python3 .project/quality.py run task-22.1.1.2` 通过，质量自测与因清单变化而过期的性能回归自动重跑并通过；`task-22.1.1.1` 和 `task-22.1.1.2` 均为 `verified`，前置的 `ms-19.1` 至 `ms-21.1` 仍为 `verified`。输入门禁记录见 [`input_contract.json`](../optimization/evidence/input_contract.json)，固定步长记录见 [`fixed_timestep.json`](../optimization/evidence/fixed_timestep.json)；两者的日志文件名及哈希由记录给出。两份完整报告的可提交压缩副本分别为 [`input_contract_current_20261001_report.json.gz`](../optimization/evidence/input_contract_current_20261001_report.json.gz)（SHA-256 `07539550b03c8b52c27b8ec73e534dbc6163edc2143e57c623f37cb3333bf82d`）和 [`fixed_timestep_current_20261001_report.json.gz`](../optimization/evidence/fixed_timestep_current_20261001_report.json.gz)（SHA-256 `1f25fb09fb559176525363a732ac430e6d1ebb9e056a14ad30cf25ce7cfa8dfd`）。重跑入口为 `python3 .project/quality.py run task-22.1.1.2`。

本轮窗口对第一次按住方向／冲刺的单次本地应用完成时间分别为单机 109.57 ms、TCP 106.14 ms、UDP 133.47 ms。这些值是单次软件渲染环境观察，不能当作 p95，也没有测得输入到实际球员像素响应。`fixed_timestep` 明确不接受设备到玩家延迟或渲染性能；`presentation_smoothing` 与 `feel_regression` 仍未就绪，`ms-22.1` 保持 `planned`。下一步按任务顺序验证实际插值、回滚及暂停恢复，再对多次真实输入事件建立 50 ms 响应分布并优化瓶颈。
