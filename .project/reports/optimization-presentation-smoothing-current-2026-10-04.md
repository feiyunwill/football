# 当前展示平滑门禁复验（2026-10-04）

`python3 .project/quality.py run task-22.1.2.1` 在当前源码上通过：543 条断言、零跳过。实际 GameEnv 像素检查覆盖回滚后首帧、过渡中间帧、再次重定向和暂停终点；原生姿态契约检查覆盖持牌附件与 6 张中间帧图像。报告还核对 72 项 Python 展示测试和 standalone、TCP、UDP 产品窗口证据。

可复核证据：

- 门禁回执：[presentation_smoothing.json](../optimization/evidence/presentation_smoothing.json)，关联日志：[presentation_smoothing-1791057698674981257.log](../optimization/evidence/presentation_smoothing-1791057698674981257.log)。
- [完整报告压缩归档](../optimization/evidence/presentation_smoothing_current_20261004_report.json.gz)：解压后 JSON SHA-256 `5c64ed75af07d20fd9b7f65837eea4b57c12dc4103ccc6df2f9ac10ef8a8376a`；归档 SHA-256 `9d9221944461f6d502feb91ec40ee37d806b8032f9c13200f6a6a0fe8fa1cef0`。报告记录当前 475 份源码指纹、原生二进制、窗口与图像哈希。

本次只确认 task-22.1.2.1。随后执行的 task-22.1.2.2 手感门禁未通过：60 次按键中 4 次在按下时没有可控球员，因此 plan-22.1.2 和 ms-22.1 不能据此标为完成。失败原始记录保留在本地待定位。
