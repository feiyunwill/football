# NT-1.3 原生 checkpoint 奖励

2026-10-14。已实现并通过子任务验收；S1 整体 review 等待 NT-1.4。

实现：无 Python 依赖的 CheckpointRewards 组件，保存每 agent 的 0..10 计数；
reward=+1 时补齐剩余 credit，否则仅 active 对应 ball owner 时按距离领取。
右侧使用自己的进攻方向，reset 清空，scalar/batch 共用同一实现。

数值：距离/阈值使用 double，对应 Python 原始 float64 观测；奖励在 float32
中逐次累加，剩余进球 bonus 先计算 double 再转换为 float32。score_reward
保持未塑形的 left-minus-right 分数变化。

真实场景对照：

- 左右单/多人、两种布局获得初始五个 checkpoint，之后重复持球不重复奖励。
- invalid batch suffix 保留已领取状态，合法后续奖励继续与 Python 相等。
- 重置后 scalar 序列与 native batch 奖励和观测逐值一致。
- 左右双人先领取部分 credit，再真实进球；各 agent 余量补齐不同，奖励/终态
  和 root engine digest 均与 Python 对照一致，支持两种 rewards token 顺序。
- C++ 合约检查全部十个阈值的前后、重复领取、每个余量的 goal bonus，以及
  零已领取状态下 losing goal 不获得 checkpoint credit。

正式验收命令：

```bash
/tmp/football-native-training-venv/bin/python .project/native-training/validate.py \
  --python /tmp/football-native-training-venv/bin/python \
  --build-root /tmp/football-native-assessment-20261014 \
  --output .project/native-training/evidence/nt-1.3-integration-20261014-c
```

结果：**28 项通过**（19 原生 + 9 原有 Gym），23.441 秒；pure C++ 合约通过，
bindings OFF，无 Python/adapter 或缺失依赖，两条接口的 core artifact 相同。
1187 个 source/resource 文件前后 fingerprint 相同：
`bc8aa059df1ad59f3dcc287ee17d811251a726f674ef532efdcd0b36bf4ecf53`。

[最终证据](nt-1.3-integration-20261014-c/report.json)。诊断 a 版记录过 goal
夹具尚未获得球就检查 partial credit 的失败；改为等待实际持球后，仍严格要求
已有五个而非全部十个 credit，奖励实现不因此改变。b 版完整测试通过后，补强
负向进球与全部 goal 余量的纯 C++ 合约，再生成当前 c 版正式证据。

当前测试环境的 NumPy/编译器版本记录在 report 中；未声称全部版本矩阵已
通过。训练 checkpoint 文件与环境状态恢复属于 S2/S4，不能与 checkpoint
**奖励**混淆。
