# 原生训练兼容性矩阵

2026-10-14。NT-1.1 建立合同，NT-1.2 扩展两种 115 布局；未来支持项只有
实现、验收并提交后才变为“支持”。实际调用使用 `backend='native'`。

| 项目 | 当前行为/支持 | 验收与后续任务 |
|---|---|---|
| 场景 | 使用现有 Python ScenarioConfig 生成；要求单侧 1..11 个受控玩家、headless、非 real_time、非 control_all_players | 已对照完整/稀疏阵容、second_half、near-goal 和 run-to-score 夹具；不宣称所有场景都已运行 |
| 玩家数量 | 单侧单人 Discrete，多人 MultiDiscrete；另一侧内置 AI | 左 1/2/11 人、右 2 人实际逐帧对照 |
| 动作集 | default=19，v2=20（最后一个 built-in AI），索引映射为对应 backend action | v2、sticky release、右侧方向旋转对照；full 不支持 |
| simple115v2 | float32；四个 team position/direction 块各固定 22 值、缺员 -1；末尾 ball/owner/active/mode | reset、scalar、batch 与 Python 逐值相等 |
| simple115 | 支持；四个 team 块紧密排列，只在 88 值块末尾补 -1，尾部 27 值与 v2 一致 | NT-1.2：full/sparse/asymmetric、左右视角、reset/scalar/batch 与 Python 对照；full 两布局相同，sparse 不同 |
| checkpoint rewards | 支持 scoring+checkpoints；每 agent 计数，持球且 active 对应 ball owner，十个距离阈值，进球补齐剩余 credit，reset 清零 | NT-1.3：左右单/多人真实密集奖励、部分 credit 后进球、batch 对照；C++ 阈值合约 |
| scoring | 左侧比分差变化；右侧取反；joint mean 与 info.agent_rewards 保留 | 实际进球、单/多人、右侧对照 |
| frame stack | 支持严格 bool stacked=True，四帧 oldest→newest，沿最后一维拼接为 460；reset 填满，terminal 追加一次，batch 每一步有自己的历史 | NT-1.4：两种布局×左右×单/多人×scoring/checkpoints 的 16 组合实际对照；invalid suffix 保持状态、输出寿命、终态与纯 C++ 合约 |
| 球队视角 | 右侧 team 交换、x/y 坐标与方向旋转、owner 和动作方向翻转；z 保留 | sparse/完整场景对照，active 每玩家独立 |
| 比赛时间结束 | native config.game_duration 按引擎 info.step 判断，作为 terminated | second_half 正常/批量终态对照 |
| 进球结束 | 场景 end_episode_on_score 独立生效 | 真实 near-goal 进球结束与 Python 相等 |
| 出界结束 | 前一返回 game_mode 为 normal，本次非 normal；场景开关生效 | NT-1.1 独立开启 out-of-play，边线 fixture 实际触发非 normal |
| 控球变更结束 | 记住最近非 -1 owner；从一方变为另一方，场景开关生效 | NT-1.1 独立 possession fixture，排除进球和时间结束 |
| truncated | 环境本身 False；标准单步外部 TimeLimit 可截断 | 实际 TimeLimit 对照；batch 只用于 raw env，不执行外部 wrapper hooks |
| batch | 预设 1..256 步；完整 admission；首个 terminal 前缀；不自动 reset | 非连续输入、非法 suffix、uint64/float/bool/shape/容量、返回数组寿命 |
| seed | Gymnasium RNG 生成引擎 seed；显式 seed 重置 episode；reverse processing 与配置一致 | 重复序列/digest、Python/NumPy global RNG 不变 |
| ownership | Native Python adapter 仅创建者 thread/process 操作；拒绝后公开 RNG/config/lifetime 不变 | 错误线程与 Unix fork 合约；C++ 接口仅串行化对象，不承诺跨 fork |
| failure | 构造/reset/step 输出处理失败，保留主异常并退款/关闭；非法 admission 保留活状态 | 真实资源 reservation、实际 native mutation 后错误注入、正常关闭/重复 close |
| render | native 不支持 human/rgb_array；render_mode=None 返回 None | 构造拒绝；原有 Python 图形回归保留 |
| 保存/恢复 | C++ 与 Python/Gym 支持版本化状态和原子文件；目标先 reset 相同场景/seed/cadence/选项，要求相同构建与实际仿真数据；wrapper-aware helper 支持 TimeLimit/OrderEnforcing/PassiveEnvChecker，其他 wrapper 明确拒绝 | NT-2.2/2.3：完整训练回放、PCG64/episode、标准 wrapper 截断/历史、故障回滚、旧文件保留、新进程恢复；digest 仍只代表 kernel |
| 像素/SMM/raw | native 尚不支持 | 不列入 S1 默认任务；原有 Python 路径可用 |
| 额外 player/录制 | native 不支持 extra_players、dump/video/recording factory options | 显式拒绝，无静默 fallback；后续独立定义范围 |

## 配置合同

当前允许的 `other_config_options`：`game_engine_random_seed`、`episode_number`、
`reverse_team_processing`、`physics_steps_per_frame`、`render_resolution_x/y`、
`action_set`、`display_game_stats`、`tracesdir`、`real_time`。

- `physics_steps_per_frame` 为整数 1..1000；默认为 10，测试包括 2。
- render dimensions 由 EngineKey 和 native constructor 检查；headless 无像素输出。
- `display_game_stats/tracesdir` 保留场景配置兼容，但原生后端没有显示/录制输出。
- real_time 必须 False；场景自带 real_time/control_all_players 同样拒绝。
- 未列出的 factory 参数或配置 key 显式 ValueError，不能当作实现了对应功能。

## 证据范围

`gfootball.test_native_training` 以维护中的 Python 实现为 oracle；独立 flags
测试验证真实触发原因，避免只靠两套实现同时返回 False。故障注入仅用于资源
与错误边界；上述数值和终止对照执行真实 GameEnv。

平台以当前 Linux/WSL 实际验收为准。Unix fork 合约在其他平台跳过并明确记录；
Windows/macOS、wheel/ABI 与长期训练在 S5/S4 验收。
