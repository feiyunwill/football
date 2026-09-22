# 比赛状态写入与查询契约

2026-09-09，ms-20.1 的任务 `task-20.1.1.1`。

当前比赛逻辑的写入者仍然是 `Match`、`Ball`、`Player/Humanoid`、`Team`、`Referee/Officials` 和 `MentalImage`。ECS 保存身份、对象引用和查询数据；它目前不是完整替代 OOP 的模拟实现。历史文档中的“完全移除 OOP”不适用于当前代码。

| 状态 | 唯一逻辑写入路径 | ECS 数据 |
|---|---|---|
| 球运动与预测 | `Ball::Process`、碰撞和触球处理 | `BallComponent`、`BallPhysicsComponent`、`Transform` |
| 球员位置和动画 | `RunPlayerSystems` → Controller/Humanoid `Process` | `PlayerPhysicsComponent`、`PlayerStateComponent`、`HumanoidStateComponent` |
| 两队控球统计 | 各队 `Team::UpdatePossessionStats`，在该队的镜像坐标下执行一次 | `PossessionComponent`、`TeamStateComponent`、`TacticsComponent` |
| 裁判规则与裁判人物 | `Referee::Process`、`Officials::Process` | `RefereeStateComponent`、`OfficialsComponent` |
| 比赛时间和判定 | `Match::Process` | `MatchStateComponent` |
| 历史感知 | `Match::StepMentalImages` 中的真实 `MentalImage` | `MentalImageComponent` |

`Match::SyncEcsFromOop` 在初始化、每个模拟 tick 结束以及快照恢复后刷新这些查询数据。ECS 球员引用按稳定身份关联对象；组件池重新排序不能改变身份映射。无 Humanoid 的实体不保留运动、动画和控球缓存。

本任务修正的行为：

- 球员处理后把 OOP 的最新物理状态同步到 ECS，消除旧物理缓存反向覆盖当帧运动的问题。
- 裁判人物恢复实际 `Process()` 调用；复制几个标记不能替代人物逻辑和动画推进。
- 两队控球统计各执行一次实际计算，随后在帧结束统一提供查询数据。
- 快照恢复重新生成全部已接入的查询数据；外部读取无需等下一帧才获得一致状态。

`CollisionResultComponent` 目前只是清空的临时查询槽，没有接入真实碰撞事件；不能把这些标记用于 AI 或网络判罚。真实碰撞仍由比赛逻辑处理。完整事件数据将随使用方接入并增加验收，当前不把它计为已实现的碰撞事件接口。

验收使用真实 `football_engine` 动态库：修改 ECS 缓存后恢复快照，逐帧比较 22 名球员的物理、位置、动画与控球查询；验证裁判人物动画推进，并用变化的方向输入检查回滚重演一致。种子 42/43 分别在独立进程执行。

后续约束：新增系统需要明确声明它是逻辑写入者还是查询消费者。迁移某类逻辑到 ECS 时，必须在同一改动中移除相应旧写入路径，并保持独立进程确定性、快照恢复和输入结果验收通过。
