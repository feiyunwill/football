# 当前源码 AI 直接检查（2026-10-07）

手感输入修复及 ECS v12、长赛 v10 参考刷新后，重新运行 AI 的四项检查，结果如下。报告与 162 份命令日志、网络重放及来源清单封存在[原始归档](evidence/ai_current_source_direct_20261007.tar.gz)，每个文件的 SHA-256 见[归档清单](evidence/ai_current_source_direct_20261007_manifest.json)。

| 检查 | 结果 | 断言 | 跳过 |
| --- | --- | ---: | ---: |
| 战术接入与真实客户端接管 | 通过 | 161,036 | 0 |
| 决策、角色镜像与触球 | 通过 | 22,950 | 0 |
| 检查点与训练可靠性 | 通过 | 51 | 0 |
| 24 个固定种子的 AI 比赛对照 | 通过 | 919 | 0 |

AI 对照每个种子运行 6,000 帧，首尾种子重复运行；3,000 帧的 Release 与 ASan/UBSan 探针逐字段一致。当前候选与封存参考的胜负、传球、射门、犯规及无效动作统计相同：左方积分率为 0.5208，传球命中总数 192，射门命中总数 143，无效意图率 0.2432。该比较确认本次手感改动未改变这套 AI 固定赛程的指标，不代表对所有比赛场景的穷尽验证。

复现时在 Linux 工作树根目录依次执行：

```sh
python3 .project/checks/ai_tactics_contract.py --suite integration
python3 .project/checks/ai_tactics_contract.py --suite decisions
python3 .project/checks/training_reliability.py
python3 .project/checks/ai_regression.py
```

`program.json` 中 `training_reliability` 的验收文字曾被错误编码为问号，已按原始提交 `601678ee` 恢复，并通过 `python3 .project/quality.py validate`。这些是当前源码的**直接检查**。在正式验收使用的 Wayland/D3D12 环境中，框架、架构、性能、手感、网络五个里程碑已重新验证；`ms-25.1` 因依赖的 `ms-24.1` Linux 1080p 渲染门槛失败而处于 `failed`，见[当前里程碑状态](evidence/milestone_status_wayland_20261007.json)。归档中的默认环境状态快照为 `stale`，不能代替目标环境的判定；归档中的 `actual_product_acceptance=false` 也不应改写为完成状态。
