# 原生显示时序所有者：实现与模型验证

2026-09-13 最新终态：独立模型验证已成功终止。Release 和 ASan／UBSan 各通过 10,102 条断言、零跳过，覆盖 1000 个连续普通帧、等待、追帧、连续纠正、暂停恢复、非法时钟／顺序／跨线程和回调装饰。测试分别耗时 0.004／0.065 秒；实际 GameEnv、图像和三个产品主循环仍待验证。

[实际模型报告](../optimization/benchmarks/native-presentation-owner-20260913-a/evidence/report.json) SHA256 为 f0c390469e48411fa8ac7ffc98067170713f9e0155d6b2c262ae22f1cef30b5e。[独立收据](../optimization/benchmarks/native-presentation-owner-20260913-a/verification.json)已核验 1034 个文件，SHA256 为 f603889b55c1c8a17db7a58d4f7404ca72b5d60149985d955226ced122a06639。该模型通过只证明时序状态机与回调边界，不证明实际渲染姿态、SDL 呈现次数或设备延迟。

以下保留实现准备时的历史说明，原“尚未编译”状态已由本段实际结果更新。

2026-09-13。对应 ms-22.1 → plan-22.1.2 → task-22.1.2.1，并服务 ms-24.1 的实际图像验收。已在独立目录写入 [NativePresentation](../optimization/benchmarks/native-presentation-owner-20260913-a/native_presentation.hpp)，尚未编译、执行或接入三个主循环，没有通过证据。

普通逻辑步之前保存物理姿态，追帧时保留最后两个相邻逻辑状态，避免每帧从未追上的显示位置开始而累积延迟。恢复快照前保存最后实际显示的姿态，之后整个纠正重演沿用这一姿态；尚未结束的纠正收到新目标时仍从当前显示姿态过渡。等待 tick 不保存新姿态，也不更新发布时间。

实现以明确的单调纳秒时刻计算插值，检查线程所有权，并拒绝在逻辑 tick 尚未提交时绘制。暂停保存最后显示姿态并冻结显示；恢复从该姿态重新过渡。普通、已稳定和首个画面分别处理，统一由一次公共 render_interpolated 调用负责呈现。无头模式的回调不增加显示 tick 依赖。

[时序验证程序](../optimization/benchmarks/native-presentation-owner-20260913-a/probe.cpp)已准备，包含 1000 个普通帧不累积延迟、等待、追帧、连续纠正、暂停恢复、非法时钟／顺序／跨线程、真实回调装饰接口等场景。它使用姿态算术模型，不是实际 GameEnv 或图像证据；C++ 还未编译。执行器仅完成 Python 语法解析，并要求正式 C 及其实际所属命令已经终止后才能启动。

后续必须实际执行模型验证，再接入 GameEnv 的快照、姿态和上下文验证；最终还要运行三个实际窗口程序，核对 SDL 呈现次数、非空图像及中间姿态。现有公共渲染 API 的通过记录不能代替这些环节。详细边界及运行约束见[实现说明](../optimization/benchmarks/native-presentation-owner-20260913-a/README.md)。
