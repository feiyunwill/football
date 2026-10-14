# Training snapshot v1

NT-2.1 定义的格式见 `engine/src/training/training_snapshot.hpp`。此任务提供
独立编解码器；环境 get/set state 在 NT-2.2 接入，Python/文件在 NT-2.3 接入。

## 字节格式与容量

外层头固定 16 字节：`FTRN` magic、u32 version=1、u32 payload 字节数、
u32 payload CRC32。整数采用 little endian；signed i32 使用位表示，
浮点采用 IEEE754 binary32 原始位，包括保留负零。CRC32 与现有 FSTA 相同。
必须精确消费整个输入；不接受尾随数据、未知版本或 flags。

payload 顺序如下。blob 是 u32 长度后跟原始字节，允许内部 NUL。

| 字段 | 表示与限制 |
|---|---|
| flags | u32，bit0 builtin AI action、bit1 fixed positions、bit2 checkpoints、bit3 stacked、bit4 ready；其他 bit 必须为零 |
| left_agents / right_agents | 两个 u32，单队 1–11 人，另一队必须为零 |
| physics_steps | u32，1–1000 |
| previous_score_diff | i32，用于下一步 scoring 差分 |
| previous_game_mode | i32，-1 或 0–6，用于 out-of-play 结束判定 |
| previous_ball_owned_team | i32，-1/0/1，用于 possession-change 结束判定 |
| compatibility | 非空 blob，最多 128 字节 |
| scenario | 非空 canonical identity blob，最多 4096 字节 |
| checkpoints | u32 数量后跟 u8；启用时恰好 players 个，每值 0–10，否则零个 |
| history | u32 float 数量后跟 f32；启用时恰好 4×players×115 个，否则零个；所有值有限 |
| kernel | 非空 blob，完整 FSTA v2 快照（头与校验一起嵌入） |

kernel 最大 10,000,016 字节，外层总上限 **10,032,784 字节**。
最大 frame history 为 5060 个 float / 20,240 字节；checkpoint 最多 11 字节。
即使所有字段达到各自上限，仍小于总预算。输入总长度和每个集合数量均在
分配前验证；nested FSTA envelope 校验属于格式层，内核字段语义属于恢复层。

history 存储顺序为 `[oldest..newest frame, player, feature]`，每帧 115 列；
不存原 ring cursor。恢复时四个 vector 按此顺序构造，cursor=0，下一步替换
最旧帧。输出的 `[player, 460]` 与 wire 的顺序不同，不能直接 memcpy。

## 身份规则与恢复接口约束（NT-2.2 必须落实）

compatibility 由环境生成，为当前引擎构建/仿真数据资源/ABI 的 SHA256 标识，不能
仅使用 Git HEAD（未提交源码或资源会改变行为）。构建输入和资源采用有序
清单及内容哈希，加入工具链、编译选项与 ABI 标记。恢复前要求标识完全相等；
格式 version 和内核 FSTA version 都独立验证。v1 不承诺跨构建或跨平台迁移。
字体和显示设施不参与物理状态身份。导出/恢复时重新核对实际 data 文件清单和
内容是否符合构建 manifest；每文件最多 64 MiB、全数据集最多 512 MiB、
目录最多 16384 项。这些检查不出现在逐步采样热路径中。

scenario 为 reset 输入的值身份，按字段序列编码，禁止 memcpy C++ 结构体、
缓存或指针。首个 u32 为场景身份版本 1，然后编码：ball_position 三轴，
left/right team 的数量及各 FormationEntry 的 role、position 三轴、
start_position 三轴、lazy、controllable；接着依次为 left_agents、right_agents、
use_magnet、offsides、real_time、game_engine_random_seed、reverse_team_processing、
left_team_difficulty、right_team_difficulty、deterministic、end_episode_on_score、
end_episode_on_possession_change、end_episode_on_out_of_play、game_duration、
control_all_players、second_half。bool 为 u32 0/1，int 为 i32，seed 为 u32，
float 为 f32。输入球队最多 11 人。私有 derived cache 不属于身份。
身份在 reset 输入被内核修改前构造并拥有副本；不会用运行中的阵型重新计算。

恢复目标必须先 reset 相同的场景、seed、cadence 及不可变训练选项；新进程
使用相同的初始化步骤，再 set state。kernel 已包含仿真 RNG、等待计数、
sticky controls、比赛及玩家状态，不能使用 canonical digest 代替可恢复快照。
render dimensions/data 路径等当前内核兼容边界还须在恢复层核对。

只支持已成功 reset 或正常 terminal 的快照。未 reset、closed 或因 mutation
失败而失效的环境不允许导出。terminal 快照 ready=false；恢复后禁止继续
step，必须 reset。内核状态与 ready、agent count、cadence 的一致性也要验证。

set state 必须先完整解码、比较身份/选项并准备训练数据，再修改内核。
恢复成功后重建 SharedInfo，不执行任何物理 tick、不重新结算奖励或滚动 stack。
只在内核及派生信息成功后提交训练历史。后置校验失败须恢复完整旧内核；
回滚本身失败才关闭环境并明确报错，不能继续使用部分恢复的对象。

## 证据及后续验收

独立 `engine_training_snapshot_contract` 不链接 GameEnv/Python；覆盖 704 个
flags×球队×人数组合、最大合法内核/历史、每处单字节损坏及每个截断位置，
重新计算外层 CRC 后的非法字段/数组长度、嵌套损坏、NaN、超限及尾随数据。
ASan/UBSan 同一测试通过。命令、源文件哈希、产物哈希与原始日志见
`evidence/nt-2.1-format-20261014-a/report.json`。

本任务未证明真实环境恢复；NT-2.2 验证 scalar/batch、奖励及 stack 的完整
回放与失败不改变状态；NT-2.3 验证原子文件和新进程；NT-2.4 执行长期资源、
多 seed/scenario 和 sanitizer 集成检查。Python Gym 外部 wrapper（TimeLimit、
RNG/episode ledger）另由 Python 快照外层保存，不能把 kernel state 当完整 Gym。
