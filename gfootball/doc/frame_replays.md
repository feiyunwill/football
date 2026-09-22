# 比赛帧回放

`gfootball.frame_sync.replay` 提供比赛位置、输入和事件的记录、检索与文件保存。2026-09-10 起，记录对象不可变，活动录制与历史集合使用同一容量管理。它保存调用方提交的比赛帧数据；原生引擎状态和训练环境的 pickle 回放仍使用各自已有接口。

## 使用

```python
from gfootball.frame_sync.replay import (
    Replay, ReplayEvent, ReplayEventType, ReplayFrame, ReplayLimits, ReplayManager,
)

limits = ReplayLimits(frames=6000, events=1000)
with ReplayManager(limits=limits) as manager:
    active = manager.start_recording("match-001", "season-001", "Home", "Away", tick_hz=10)
    manager.record_frame(ReplayFrame(
        frame_id=0,
        ball_pos=(1, 2, 0.2),
        player_positions={"home-1": (0, 2, 0)},
        inputs={"home-1": {"direction": [1, 0], "buttons": 0}},
    ))
    manager.record_event(ReplayEvent(
        ReplayEventType.MATCH_START, timestamp_ms=0, frame_id=0,
        details={"competition": "Example"},
    ))
    manager.set_score(0, 0)
    completed = manager.stop_recording()
    completed.save("replays/match-001.jsonl")

loaded = Replay.load("replays/match-001.jsonl", limits=limits)
cursor = loaded.cursor()
cursor.seek(0)
for frame in cursor:
    print(frame.frame_id, frame.ball_pos, dict(frame.player_positions))
```

`ReplayFrame`、`ReplayEvent` 保留原来的构造参数和可读字段，并完整输出 `to_dict()`。它们现在是带显式 slots 的不可变值对象，不再是可写 dataclass；使用 `to_dict()` 取得可修改的导出副本。原始列表、字典的后续修改不会改变记录，也没有可写的实例 `__dict__`。

`Replay.frames` 和 `events` 是只读序列视图，支持长度、索引、切片和迭代。普通迭代只固定开始时的记录条数，不提前复制整场数据。`Replay.to_dict()` 继续返回原有列表摘要；完整持久化使用 `save()`。停止后 Replay 被封存，不能再写帧、事件、比分或时长；独立创建的 Replay 可调用 `seal()` 封存。

帧号允许从任意合法帧开始，此后必须连续。事件按帧号和时间非递减记录，同帧可有多个事件。时长至少覆盖已记录帧数除以 `tick_hz` 的时间以及最后事件的时间；不能手动缩到数据结束之前。游标之间进度独立，支持 rewind、seek 和重复 EOF；多个线程共用一个游标时，每次取帧与推进在同一锁内完成。

## 容量与所有权

| 对象 | 默认限制 |
| --- | --- |
| 单场帧/事件 | 100,000 帧、10,000 事件 |
| 单条记录 | 64 KiB；位置与输入各最多 22 名球员 |
| 单场拥有数据 | 128 MiB，包含固定索引及逐步分配的列表块 |
| 集合 | 活动录制与已保存回放合计最多 50 场、256 MiB |
| 导入暂存 | 每管理器最多一个，最多额外一份单场预算；`staging_limit_bytes` 单独报告 |
| JSON 文件/单行 | 128 MiB / 512 KiB |
| 嵌套详情/输入 | 最多 2,048 节点、8 层、每容器 128 项、每字符串 4 KiB UTF-8 |

球员 ID 最多 128 字节，队名最多 1,024 字节；方向和位置必须是有限数，详情只接受普通 JSON 值。布尔值不能充当帧号、时间或容量参数。各上界同时生效，因此带大量球员输入的记录可能先达到字节上界。按实际比赛规模配置预算，并处理 `ReplayCapacityError`。

列表按 64 个位置分块分配，索引长度固定，计量不依赖 Python 列表扩容公式。通过管理器返回的活动 Replay 直接调用 `add_frame()`/`add_event()`，仍使用同一集合预算。集合满时淘汰最早创建的已封存回放；活动回放不会被淘汰。所有候选都确认足够后才开始淘汰，非法、重复 ID 或无法容纳的录制不会提前停止当前录制或删除历史。

`start_recording()` 成功时会封存原活动录制。若容量不能同时容纳旧活动和新录制，它保持原录制并报错；可以先显式停止原录制，再开始新录制。`record_frame()`/`record_event()` 在没有活动录制时返回 False，成功返回 True。超限不丢弃已接受的帧，调用方可停止并保存已录部分。

`delete_replay()`、淘汰和 `close()` 只释放管理器的内存所有权，不删除用户文件。调用方仍持有的旧回放保持封存并受单场限制，但不计入管理器的 `retained_bytes`。临时编码/复制、调用方导出副本、文件缓冲、Python/原生/RSS/GPU 内存不属于集合的拥有数据字节统计；控制对象数量另有上界。

导入先在单独预算内完整验证，再加入集合；失败不会改变已有回放。`close()` 向进行中的同步导入发送取消请求，读取线程在下次读入前退出并关闭文件。正在阻塞的操作系统读入不能被这个请求强制中断，导入调用方仍需等待其调用结束。统计中 `loading` 会保持 True 直到该清理完成。

对象不支持跨 fork 复用。Python 3.9 语法已检查，当前实际执行环境为 Python 3.14.6；其他解释器版本的运行验收尚未执行。

## 文件与校验

文件使用 `football.frame_replay` 版本 1 的 UTF-8 JSONL：一条头部、声明数量的帧、声明数量的事件、一条结束记录。帧包含 `frame_id`、`ball_pos`、`player_positions`、`inputs`；事件包含类型、时间、帧号、球员、球队和完整 `details`。头部包含 ID、球队、比分、时长、创建时间和 tick 频率。

结束记录包含实际帧数、事件数以及之前所有原始行的 SHA256。读取拒绝缺尾、截断、额外尾部、未知字段、重复 JSON 键、无穷数、超长整数、记录顺序错误和文件读取过程中的变化。有效校验和不能代替记录结构和时序验证。

`ReplayFileReader(path)` 每次产出一条不可变帧或事件，直到完整消费并验证结束记录后，`stats()['verified']` 才为 True。提前 close 只表示文件已关闭。`Replay.load()` 完整验证成功后才返回封存对象。读取在实际独立进程中验证过，不导入 NumPy、OpenCV 或 GameEnv。

保存复用录制输出的跨进程目录配额与 `AtomicReplayFile`：写临时文件、flush/fsync、关闭，然后替换明确指定的目标；容量、编码或发布失败保留旧目标。默认目录配额为 4 GiB、256 个文件、4 个活动输出，可通过 `directory_limits` 设置。保存依赖现有 NumPy/OpenCV 输出基础设施。目录租约细节参见 [环境回放保存](saving_replays.md)。

## 验证

```text
python .project/checks/frame_replay_probe.py --output NEW_DIRECTORY
```

当前 64 项 Windows 检查通过，包括 10 万帧实际持久化与流式校验、完整球员/输入/事件往返、并发录制/游标、原有保存及产品辅助模块回归。已有名为 `TestEndToEndMatch` 的回归测试只运行 Python 辅助对象；本轮没有原生比赛或渲染验收，也尚未将这个数据录制入口接入比赛 UI。整体内存、网络、原生确定性与产品发布门禁仍待后续里程碑完成。
