# task-25.1.2.2 — AI 对照验收

2026-10-06 固定种子检查器已存在并重新通过完整 24 场、首尾复跑及 Release/Sanitizer 对照，919 项断言、零跳过。新增 `engine/data` 资源清单核对及篡改负例，结果与封存基线一致；渲染前置门禁仍未通过，本任务状态不提升。见[当前资源完整性与赛程证据](../reports/optimization-ai-input-manifest-2026-10-06.md)。

2026-10-03 仍缺固定种子 AI 对照检查器；现有训练可靠性预检不能替代胜率、传球、射门、犯规和无效动作的统计与退化验收。当前 task 与 AI 里程碑保持未完成，见[范围与证据](../reports/optimization-render-stage-training-2026-10-03.md)。

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 固定种子对照比赛记录胜率、传球/射门/犯规/无效动作，统计区间和退化检查

依赖：task-25.1.2.1

执行顺序：无

验收检查：ai_regression

执行：`python3 .project/quality.py run task-25.1.2.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
