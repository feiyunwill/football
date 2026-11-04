# 产品优化阶段（2026-09-09）

2026-10-15 新增 [下一阶段优化计划](next-optimization-plan-20261015.md) 与
[执行状态](next-optimization-state.json)，记录训练学习效果、性能实验与交付验证。
该路线不自动提升下列产品里程碑状态；GPU 暂停安排继续生效。

本阶段按里程碑 → 计划 → 任务执行。范围包含框架、架构、性能、手感、网络、渲染、AI 与整体验收。历史 Phase 1–18 的完成记录不作为本阶段通过依据；上一轮问题与修复见 [审查报告](../reports/milestone-review-2026-09-09.md)。

| 里程碑 | 内容 | 核心交付 |
|---|---|---|
| ms-19.1 | 框架 | 验收状态机、原生引擎/绑定边界、构建矩阵 |
| ms-20.1 | 架构 | 状态写入边界、环境生命周期、逻辑与表现契约 |
| ms-21.1 | 性能 | 真实比赛基准、ECS 热点、容量与内存预算 |
| ms-22.1 | 手感 | 输入闭环、固定步长、插值与动作延迟测量 |
| ms-23.1 | 网络 | 权威输入窗口、重连、大厅闭环、故障注入 |
| ms-24.1 | 渲染 | PBR/IBL/HDR/后处理接入、实际图像与帧时间 |
| ms-25.1 | AI | 真实战术接入、决策回归、检查点可靠性、对照比赛 |
| ms-26.1 | 产品验收 | 全流程、长时运行、可安装产物、最终证据审查 |

`program.json` 是优化阶段的计划来源，共 8 个里程碑、16 个计划、32 个任务。细分文档位于 `../milestones/`、`../plans/`、`../tasks/`。任务之间按依赖自动排序；后续验收尚未实现的条目明确为 `ready: false`，执行会报错，不能视为通过。

## 当前执行范围（2026-10-09）

暂缓 GPU 相关的 `task-24.1.2.2`（1080p 渲染性能验收）及依赖它的完整渲染里程碑 `ms-24.1`。已有 PBR、后处理和图像功能证据保留；不重跑 GPU 基准，也不放宽 16.67 ms 门槛。AI 的战术接入与里程碑改为依赖已通过的网络里程碑 `ms-23.1`，使 AI 和非 GPU 产品任务可以独立验收。`ms-24.1`、最终质量审查 `task-26.1.2.2` 和完整产品发布 `ms-26.1` 仍须等待 GPU 验收，不能标记完成；渲染阻断问题保持开放。

当前自动执行入口为 `python3 .project/scripts/run_non_gpu_scope.py`：按依赖顺序运行 AI 里程碑和产品全流程、长时、可安装产物任务，在执行前拒绝任何包含 `render_regression` 的目标依赖链。恢复 GPU 计划时，先通过原有 `task-24.1.2.2` 检查，再运行完整发布审查。通用的 `quality.py next` 仍会显示尚未通过的 GPU 任务；当前范围使用上述入口。

在 WSL/Linux 仓库根目录运行：

```bash
python3 .project/quality.py validate
python3 .project/quality.py status
python3 .project/quality.py next
python3 .project/quality.py run task-19.1.1.1
python3 .project/quality.py verify plan-19.1.1
python3 .project/quality.py docs
```

执行循环为：读取下一任务 → 实现代码及验收 → 执行任务 → 修复失败 → 验证计划 → 验证里程碑 → 推进依赖。代理负责实现和修复；验收工具负责调度检查与判断证据。整个本地过程不需要逐项人工确认，不自动提交或发布。

验收规则：

- 每个检查使用明确的参数数组、超时和源码范围，串行运行；内核锁防止重复执行与并行编译。
- 结果绑定检查定义、源码内容、执行路径、Python/平台信息和日志摘要。相关源码变化后状态变为 `stale`，必须重跑。
- 测试必须有足够断言且无跳过；外部服务测试必须由验收脚本主动启动服务，不能依靠默认跳过通过。
- 非零退出、超时、缺失程序、缺少结构化结果、运行期间修改源码均失败。超时会终止该检查启动的进程组。
- 完成状态由当前证据推导。任务、计划、里程碑还必须满足全部子项、依赖和集成检查。旧完成脚本对 Phase 19+ 已转入此规则。
- 本阶段目标为 Linux x86_64 原生服务端和客户端。每次性能/图形验收记录实际 CPU/GPU、驱动、分辨率、编译配置。WSL 软件渲染结果不能代替目标 GPU 的 60fps 数据。
- 50ms 输入响应、1080p 帧时间、真实网络故障矩阵与 AI 对照都必须实际测量。未测量项目保留未通过；不从单元测试推断整体产品质量。

基线文件 `baseline.json` 记录本阶段开始前已有改动的哈希，避免覆盖上一轮审查成果。每个检查的完整日志和机器可读结果保存在 `evidence/`。源码范围应覆盖该检查的实现、依赖和验收脚本；范围收窄必须有代码依赖依据。

Current PPO CPU follow-up: [report](ppo-optimization-report-20261015.md); current quality and audit receipts are linked there. Earlier learning and wheel receipts remain historical.

2026-10-17 current follow-up: [selective worker digests](selected-digests-report-20261017.md), including current full quality and audit receipts.

2026-10-17 sustained training: [long-term plan](sustained-training-plan-20261017.md) and [first completed 30-minute baseline](sustained-training-report-20261017.md). Matched single-worker/repeated scaling experiments remain open.

2026-10-17 fixed-workload follow-up: [matched single/four-worker comparison and CPU diagnosis](matched-workers-report-20261017.md). Observed ratio 1.9415; full scaling gate remains open.

- [Historical actual-worker native CPU diagnosis](native-hotspots-report-20261017.md):128-update learner/replay parity; profiling scope only.

- [Rejected LTO candidate](lto-report-20261017.md): primary fixed gate failed; original build retained.

- [Retained headless subtree invalidation](spatial-invalidation-report-20261017.md):20.54% isolated step CPU reduction; current pipeline follow-up below.

2026-10-17 current bounded performance acceptance: [actual PPO scaling, four-configuration costs and current 30-minute resource run](ppo-pipeline-report-20261017.md). Primary four/one-worker median 2.2102x; primary engine pipeline median 1.0902x. Long-run throughput was observed under external build contention; learning and current-source delivery remain open.

2026-10-18：约定的学习泛化、当前源码 30 分钟运行与安装后模型复现目标已完成，见 [最终报告](generalization-delivery-report-20261018.md).

后续已启动 [2v1 配合进攻计划](two-on-one-plan-20261018.md)，其学习与交付验收独立于前一阶段；当前状态见 next-optimization-state.json。

2v1 配合进攻目标已通过学习、持续运行与交付复现验收，见 [最终报告](two-on-one-report-20261018.md)。

冻结五模型的 200 个新起点泛化与交付复现验证通过，见[报告](two-on-one-broad-report-20261018.md)；原质量、安装与时长收据按同源码复用。

2026-10-19：O20 确定性 balanced 推理通过新起点确认、状态恢复与归档复现，平均进球率 89.3%，见[验收报告](two-on-one-inference-report-20261019.md)。

2026-10-19：O21 已将 balanced 接入正式 CLI，完成版本化推理恢复、3000回合一致性回归、当前源码质量与独立安装测试，以及两次1000回合交付复现，见[验收报告](two-on-one-cli-report-20261019.md)。

2026-10-20: [Eight-week AI training and delivery roadmap](football-ai-roadmap-20261020.md). O22 historical integrity verified; persistent runtime recovery pending.

2026-10-20：O22持久环境、79项集成测试、失败分类与精确训练恢复已完成，见[报告](o22-baseline-report-20261020.md)。O23已登记[唯一候选与预算](o23-broad-start-protocol-20261020.md)，候选源码质量验证运行中，尚未进行完整训练或新确认。
