# NT-5.3 — 使用示例、迁移与回滚

2026-10-15。新增一键 reproduce_training.py 与 MIGRATION.md，补齐已验证的
平台、默认 Python backend、native opt-in/批量边界、FPPO/FTRN/legacy 格式
分离以及同构建恢复/回滚规则。gfootball/doc/native_training.md 添加入口，
COMPATIBILITY.md 更新 policy/learner ownership 和实际 S4/S5 状态；历史
PPO_DECISION.md 的首段链接当前完成证据，保留原审计决策。

一键脚本在迁移后的实际 native package 上执行 full2/prefix1/resume1/frozen0，
真实更新16样本；完整/续训 iteration、checkpoint 字节与冻结评估一致，各轮
评估 isolated，parameter_delta>0。证据在
`evidence/nt-5.3-reproduction-20261015-a/report.json`；四个 stdout JSON 与
stderr 日志逐个核验 SHA/退出码。checkpoint SHA256：
`16cabdc5152e03bff782773625b66727284feb0b71e1ece86e3c524c3b496653`。
三份生成的二进制移到 `/tmp/football-native-reproduction-20261015-a-checkpoints`
保留，不提交二进制；报告中的 argv 是实际原始执行路径，未改写历史日志。

使用示例沿用已验收的 native/Gym/snapshot 接口，没有改变默认 Python 路径，
没有承诺将 native checkpoint 恢复到旧 Python/Gaussian 路径。短功能复现不
代表收敛或学会足球；多 seed 指标及随机/内置 AI 基线仍按 S4 实验解释。

当前 quality verify NT-5.1 最终报告再次通过。生产代码/资源仍为原 1224 项
fingerprint；本任务增加的是 .project CLI 验证驱动和文档，不触发无关完整
重建或重复大规模测试。图谱 Verify tier，generation 2026-10-14T23:07:57Z，
脚本 main 唯一返回，material paths metadata_match，无记录缺口；精确脚本
与实际四进程输出为主要证据。交付平台范围见 PLATFORMS.md。

NT-5.3 完成后进入单独 S5 全局自审，不能提前宣称长期目标关闭。
