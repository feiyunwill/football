# 当前源码正式验收与手感故障定位（2026-10-01）

基于提交 `1c5aa606e0f28a3ea5ce3d63d8f8d47f78f1d2b3` 顺序运行 `python3 .project/quality.py run ms-19.1`、`ms-20.1`、`ms-21.1` 和 `ms-22.1`。前三个里程碑的当前源码状态均为 `verified`；手感里程碑为 `failed`，后续里程碑因依赖尚不能正式验收。每项检查的指纹、退出码和日志 SHA-256 记录在 `.project/optimization/evidence/<check>.json`，对应日志随本次证据提交。框架、架构、性能各自的检查没有失败；手感前置的 `input_contract`、`fixed_timestep`、`presentation_smoothing` 均通过。

正式手感检查在 15 场独立产品窗口中对 60 次 XTEST 按键取样：60 次均被控制器接纳，只有 59 次具有合格的因果速度响应；速度 p95 为 **275.299 ms**，随后画面交换 p95 为 **277.685 ms**，都超过 50 ms 预算。20 次超预算按键的辅助归因是待触球 10 次、动画选择延迟 5 次、运动物理延迟 3 次、命令采样较晚 2 次。归因是诊断推断，不能替代失败判定。

种子 48 第 2 次按键提供了明确的局部复现：受控球员在触球动画第 6–32 帧期间持续收到向右的人工移动命令，`anim_select` 对该球员的移动命令均返回 `accepted=false`，待触球标志保持为真；这次按键没有合格的因果速度响应。`Humanoid::SelectAnim` 在当前动画不是移动而新命令是移动时，直接拒绝重排（`engine/src/onthepitch/player/humanoid/humanoid.cpp` 约 1205 行）。这条路径需要保留真实触球和球员/球的相对位置，不能靠降低门槛或仅改诊断脚本通过验收。既有隔离实验对单独放宽触球后转向或反向动量重排进行过完整样本复测，仍未达到 50 ms，故本次未把那些候选补丁合入主源码。

逐按键报告、动作、命令/动画原始事件、二进制与源码身份保存在 [`feel_formal_diagnostic_20261001_current.tar.gz`](../optimization/evidence/feel_formal_diagnostic_20261001_current.tar.gz)，SHA-256 为 `e607313f2be5bb05bfe2187fcef50ccd381fc4868ed76295f023d4e669ffe2ee`。为避免把约 159 MB 帧图写入 Git，该包仅省略 PPM；完整原始包仍在本机 `.project/optimization/evidence/feel_regression-1790860746755601975.tar.gz`，SHA-256 为 `146eac3b2b3576d678ed98f39efa136df88a98aba75f6dc0d14bb13cdb8b7acb`，可由正式门禁重新生成。
