# AI 球员处理坐标修复（2026-10-03）

## 问题与修复

ECS 迁移把所有球员的 `Controller::Process` 和 `Humanoid::Process` 移到战术处理之后统一执行，但没有保留原有的逐队镜像坐标上下文。右队控制器因此按错误的进攻方向决策。现在依照 `first_team`、`second_team` 顺序，分别在对应的镜像上下文中处理各队球员，并在帧末恢复坐标。

## 可复现对照

使用真实 headless 11v11 比赛、两队 AI 难度均为 1.0、每种子 3000 帧。固定种子 42–49 的 8 场比赛中，修复前右队 8 场均无射门意图且均未得分；修复后右队 7 场出现射门意图，多场完成射门，比分不再持续悬殊。独立原生合同测试固定种子 43、47、49，并重复 43 验证确定性：左队完成 6 次射门，右队完成 7 次，3 条断言通过。

运行：`cmake --build <engine-release-build> --target engine_ai_match_mirror_contract && <engine-release-build>/bin/engine_ai_match_mirror_contract`。

`ai_tactics_contract.py --suite decisions` 的 Release/Sanitizer 两种构建共 22,950 条断言通过；`simulation_contract.py` 的 3,976 条断言通过。战术状态合同在两种构建中各重复两次，均得到 27,450 条断言、960 帧、3,588 次非零球员选择和 98 次定位球帧，因此更新该合同固定预期。

完整战术集成仍未通过：TCP 断线接管通过，UDP 断线接管未在测试时限内发送接管通知。使用提交前的 `b0fcc2a` 独立构建重复同一 UDP 场景，也得到相同失败，故将其保留为独立网络问题，不能据此宣称 AI 里程碑通过。
