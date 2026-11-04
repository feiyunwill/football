# O23 schema8 midl：冻结验收拒绝（2026-10-27）

## 结论

`midl_mean4` 完成了五种子恢复研究和独立汇总审计，但没有通过已冻结的候选验收；不得创建独立确认，也不得启动 O24 或 O25。

## 可复核证据

- 剩余研究：`/root/work_space/football-artifacts/work-o23-midl-remaining-study-20261027-a/report.json`
- 汇总：`/root/work_space/football-artifacts/work-o23-midl-assembled-20261027-a/report.json`
- 独立审计：`/root/work_space/football-artifacts/work-o23-midl-assembled-audit-20261027-a/report.json`
- 源码指纹：`7acb9960b08e41f0d8d375172253f241e6bbb0f6a87152899c2a41e0f5b8d239`

## 冻结门槛与结果

- 总进球：952/1000（95.2%），低于 970/1000（97.0%）。
- 每组：196、196、194、190、176 / 200；第五组 88.0%，低于 180/200（90.0%）。
- 每种子进球门槛与传球/联合回合门槛通过。
- 汇总审计保持 `passed: true`，但 `validation_passed: false`、`candidate_accepted: false`。

监督器的确认准备脚本因此断言失败并退出；该退出是预期的门槛执行，非可重试的基础设施故障。保留该失败，后续候选必须使用新的预注册训练与独立确认数据；不得放宽门槛或复用本候选的确认资格。
