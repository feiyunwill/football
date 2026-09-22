# 原生输入与逻辑帧绑定验证

2026-09-13。对应 ms-22.1 → plan-22.1.1 → task-22.1.1.1。已在独立实现目录完成输入供应回调和有界未确认帧历史，尚未合入三个原生入口。输入门禁及产品手感验收未完成。

此前 Tick 先消费权威帧，再预测下一帧。如果入口在 Tick 前按旧帧号取输入，追帧后会把输入用到别的帧；发生快照预算恢复时，下一帧号还可能回退，因此只记最后一次输入也不足以保证一致性。

[修改后的 FrameSimulation](../optimization/benchmarks/native-input-admission-20260913-a/frame_simulation.hpp)在处理权威帧之后，以真实待提交帧号调用供应者。等待服务器、关闭预测或达到预测上限时仍能取得本帧输入，避免客户端等不到权威帧、服务器等不到输入。旧 Tick 接口继续通过固定输入供应者调用同一实现。

[LocalInputHistory](../optimization/benchmarks/native-input-admission-20260913-a/local_input_history.hpp)按确认进度淘汰输入。重复或回退帧复用原 float32 位及按钮掩码；新的短按仅在首次接纳新帧时消耗。固定上限 1024 帧，实例 20512 字节；容量拒绝、非法帧及重入在消费供应者前拦截，不覆盖未确认输入。

[实际验证报告](../optimization/benchmarks/native-input-admission-20260913-a/evidence/report.json)已成功终止，SHA256 为 6e5ca23fc96ea91dcef70c8ffc1b3e03ada2ce759060a6fd09c0a693ecb8273b。Release 和 ASan／UBSan 各 16248 条断言、零跳过，包含 2000 个权威帧与冻结旧算法逐步对照。实际执行了等待、权威追帧、供应者异常／重入、历史容量、确认淘汰，以及快照超预算恢复后帧号从 3 回退到 1 的路径；旧帧 1／2 复用原输入，待处理新短按留给帧 3。

[独立核验收据](../optimization/benchmarks/native-input-admission-20260913-a/verification.json)逐项固定 30 个源码、二进制及日志文件，SHA256 为 fa679534dcf03abb3dfa530443c3e9be3433fc6e16d8fc224d8ae5a58d06809e。本次执行使用真实 FrameSimulation 算法及回调状态模型，未调用 GameEnv 或实际网络 socket，不能证明球员响应或网络往返延迟。后续仍需将共享采样缓冲、帧历史和显示节奏接入本地／TCP／UDP 入口，再完成实际引擎和联机验证。
