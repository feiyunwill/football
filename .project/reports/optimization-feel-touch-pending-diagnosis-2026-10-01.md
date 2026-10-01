# 触球待处理时的移动输入：真实窗口诊断（2026-10-01）

对应 `ms-22.1 → plan-22.1.2 → task-22.1.2.2`。本报告基于 `feel-assist-projection-gate-20261001` 的 15 场、60 次真实产品窗口 XTEST 输入及逐帧事件；`triage.json` 的分类是诊断推断，不代替因果实验。

正式门槛失败的 21 次输入中，10 次归为 `touch_pending`。其中 9 次在 340 ms 按键期间没有可归因的目标方向速度响应，另 1 次约 163 ms 才响应。seed 48 的第 1 次按键开始约 15 ms 时，受控球员已在停球动画第 6 帧，触球点为第 33 帧；其后多次移动命令均未被接受，按键结束时动画才到第 32 帧。seed 54 与 56 的第 1 次按键则是在按键开始约 13 ms 后新选中第 33 帧触球的停球动画，此后移动命令持续被拒绝。这说明至少一部分长尾由输入期间新建立的触球承诺产生，而非仅由按键前已有的动画造成。

源码路径与事件吻合：`HumanController::RequestCommand` 每帧先排列带球控制、停球，再排列移动；`Humanoid::SelectAnim` 对当前非移动动画的移动重排队直接返回 `false`；`Humanoid::CalculateMovementSmuggle` 在 `touchFrame != -1` 时不增加移动修正。因此，单独优化移动命令的方向混合不足以解决这类长尾。直接取消触球动画可能造成接球丢失或动作穿帮，不能当作已验证的手感修复。

动画资源的 `extension,football,<frame>` 触球元数据还给出物理下界：40 个停球动作的最早触球帧为第 9 帧，45 个带球控制动作的最早触球帧为第 6 帧；停球没有第 8 帧及更早的触球候选，带球控制仅 8 个动作在第 8 帧或更早。以每帧 10 ms 计，单纯缩短触球等待仍无法保证 50 ms 内响应，不能把“优先短触球动作”当作足够的修复。可重跑 `.project/optimization/diagnostics/feel_touch_metadata.py`；逐资源哈希与统计保存在 `.project/optimization/evidence/feel_touch_metadata_20261001.json`，SHA-256 为 `c0a04dab343d51e117eb85ec7ee8a281bb9c6c7104f70dfe98daf527c549fda4`。

下一次实现实验应同时验证输入响应和触球正确性：针对手动移动期间新选中的长停球动画，研究触球前可维持球脚接触位置的受限转向；记录每次选择的候选触球帧、预期/实际触球位置、是否完成触球、球权、位置连续性及目标方向速度。通过固定回放、Release 与 ASan/UBSan 合同后，再跑同一 15 场真实窗口门槛；不得用缩短样本或放宽 50 ms 预算宣称完成。

原始输入、事件和门槛报告位于 `.project/optimization/benchmarks/feel-assist-projection-gate-20261001/`。该目录为本机大型诊断资料；可提交的精选事件包位于 `.project/optimization/evidence/feel-manual-assist-increment-20261001.tar.gz`。
