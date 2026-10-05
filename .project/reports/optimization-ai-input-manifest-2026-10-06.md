# AI 比赛对照的资源完整性（2026-10-06）

归属 `ms-25.1 → plan-25.1.2 → task-25.1.2.2`。固定种子检查器原先在运行前后核对 C++ 源码、测试器和封存基线，但未核对传给比赛进程的 `engine/data`。现在将该目录的所有文件加入同一 SHA-256 清单，并在报告中记录文件数量与规范化清单摘要。资源在赛程期间发生变化会使现有运行前后比对失败；独立负例测试实际修改临时数据库文件，确认清单随之变化。统计门槛、封存基线和比赛采样器均未改动。

当前清单覆盖 826 个文件，其中资源 465 个；单次生成约 0.09 秒。使用现有 Release 与 ASan/UBSan 构建目录重新配置、构建并运行完整检查：

```sh
python3 .project/checks/ai_regression.py \
  --release-build /tmp/football-optimization-native \
  --sanitized-build /tmp/football-optimization-sanitized
```

种子 42–65 的 24 场、首尾种子复跑，以及 Release/ASan/UBSan 的 3000 帧对照全部通过；919 项断言、零跳过、34 条执行命令均成功。候选 24 场与封存基线逐项一致，左胜 5、右胜 4、平 15；实际传球 192、射门 143、犯规 20，未执行意图率 24.32%。[完整报告](../optimization/evidence/ai_regression_data_manifest_20261006.json) SHA-256 为 `30401de928a03cea7f01deb05e3b4864706581e083ef1dc3138b8fbe0d8651d9`，[34 份日志归档](../optimization/evidence/ai_regression_data_manifest_20261006.tar.gz) SHA-256 为 `ff8e36f3f3390db09c360e789fa47ae7c268b72d3694fb76ba881fa3c2982ce4`。报告中每份日志、两套二进制及当前资源清单的哈希已经重新核对。

这证明当前 AI 固定赛程的回归检查可复现，不证明所有战术或主观体验。`ms-24.1` 的 1080p 渲染预算仍未通过，因此 `task-25.1.2.2` 与 `ms-25.1` 的质量状态不提升。
