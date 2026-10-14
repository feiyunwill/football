# NT-1.4：共享 C++ 四帧历史

2026-10-14。实现并验收通过；S1 review 在子任务提交后单独执行。

历史：原生环形缓存保存四帧，每帧至多 11×115 个 float。reset 填满初始观测，
每次实际 API transition 写入一帧，oldest→newest 沿特征轴排列为 460。
checkpoint 与物理状态不受堆叠影响；terminal 前缀与 repeated reset 保留合同。

输出：ObservationBuffer 保存连续 float32 数据及宽度，单步/批量均按真实
columns 分配并复制。未堆叠维持 115 stride；indexed C++ rows 改为 span，
size() 仍表示行数。限定 115/460 列及最多 2816 行，copy assignment 保持形状
异常安全。新 header 已登记 sources.cmake；尚未发布稳定二进制 ABI。

验收：

- 16 组合（两布局×左右×单/双人×scoring/checkpoints）逐值与 Python
  FrameStack 对照，包含 reset 填充、shift、scalar/batch、无效 suffix 与奖励。
- 两布局 joint terminal prefix、官方 Gym checker、后续 step/reset 不覆盖旧数组。
- 纯 C++ 将 stacked 的最新帧与未堆叠输出对照；shift、reset、batch/terminal
  rows 和引擎 hash 相等。既有默认 115、checkpoint 和原有 Gym 合约保持通过。

正式命令：

```bash
/tmp/football-native-training-venv/bin/python .project/native-training/validate.py \
  --python /tmp/football-native-training-venv/bin/python \
  --build-root /tmp/football-native-assessment-20261014 \
  --output .project/native-training/evidence/nt-1.4-integration-20261014-a
```

结果：**30 项通过**（21 原生 + 9 原有 Gym），29.369 秒；bindings OFF 的纯
C++ 合约与无 Python 依赖检查通过，Python/native core artifact 相同。
1188 个 source/resource 文件前后 hash 相同：
`cb141796f17d4eb9f70df49cd091743b3420f05cca43a2a8809bb2a478b950e7`。
[完整证据](nt-1.4-integration-20261014-a/report.json)。

外部 TimeLimit/hooks 仍只适用于标准 step；batch 不执行这些包装器。
快照尚未实现，S2 必须保存环形缓存和 cursor，不能只保存最新观测或 kernel。
