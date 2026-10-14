# NT-1.4：原生数值 frame stack

依赖：NT-1.1 `339bfd1`、NT-1.2 `409f167`、NT-1.3 `fb48103` 已验收提交。
当前状态：实现和验收通过，提交后登记 commit；S1 review 保持 pending。

合同：对 simple115/simple115v2，stacked=True 按现有 FrameStack(k=4) 沿最后
一维拼接，形状为 `(460,)` 或 `(agents, 460)`。reset 用同一个初始观测填满
四帧；每个实际 transition 追加一次，历史从最旧到最新排列。终态保留最终
transition；batch 返回每一步自己的历史，不受后续 step 覆盖。

实现重点：

- 历史与编码在共享 C++ 内核中完成，不把 Python FrameStack 当作原生实现。
- 预分配最多 4×11×115 的原始历史。批量输出仍限 256 步，维度最多 460。
- 现有 C++ 输出依赖 `vector<array<float,115>>`；为动态宽度设计连续、有形状
  信息的输出表示，更新绑定和合约，避免固定 460 缓冲造成未堆叠数据 stride 错误。
- 不改变 kernel 物理/动作/奖励；checkpoint 状态只在 reset 清零。
- C++/Python 默认值维持未堆叠；公开处理 unsupported/invalid 参数。

验收：两种布局、left/right、single/joint、scoring/checkpoints 的 scalar/batch
逐值 Python 对照，重复 reset、首个 terminal 前缀、数组寿命、invalid batch
保持历史/奖励状态，以及纯 C++ stack 合约。完整验收入口生成新证据并提交。

完成后：按 ROADMAP 做 S1 整阶段 review，审查整个 S1 diff、所有权、reward
与 history 的解耦、维度/容量/GIL、默认 Python 回归及未来快照状态完整性。
阻断项修复提交且 review 通过后才进入 S2。
