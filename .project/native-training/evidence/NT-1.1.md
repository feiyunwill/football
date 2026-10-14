# NT-1.1 兼容性矩阵与边界合同

2026-10-14。验收基线为 `1582471`，本任务仅增加矩阵、测试及文档入口。

执行命令：

```bash
PYTHONPATH=/tmp/football-native-assessment-20261014/validation-stage:$PWD \
  /tmp/football-native-training-venv/bin/python -m unittest gfootball.test_native_training -v
```

结果：**16 项通过**，12.912 秒，当前 Linux/WSL 执行了 Unix fork 检查。

- child 的公开 step/reset/render/close/batch 均在访问继承资源前拒绝，公开
  RNG/lifetime 不变；parent hash 不变且可继续真实 native step。
- 构造 reset 失败、一次实际 native mutation 后 reset 失败均保留主异常，
  引擎 admission 数恢复，已失败环境不可继续使用。
- out-of-play 独立开关：固定边线场景真实产生 normal → throw-in，进球和
  possession flags 关闭，匹配 Python 的观测、终止、奖励和状态 hash。
- possession 独立开关：固定 run-to-score 变体真实产生 owner 0 → 1，进球和
  out-of-play flags 关闭，早于 600-step 比赛时间结束，逐帧匹配 Python。
- 其余原生基线合约保持通过；git diff --check 通过。

未将所有场景、保存/恢复、训练算法或跨平台宣称通过。当前/计划支持范围明确
见 COMPATIBILITY.md；后续功能必须通过相应任务后再变更支持状态。
