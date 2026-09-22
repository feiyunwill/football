# 有界存档与进度保存

`gfootball.frame_sync.save_system` 保留 SaveManager、SaveSlot、SaveType、GameProgress 入口，并新增 SaveLimits、SaveDiskLimits、SaveCapacityError、SaveFormatError、SaveConflictError。

SaveManager() 默认保持内存模式。提供 path 后，每次成功的创建、保存、删除和导入都会原子发布完整集合，重新创建 manager 即可读取。不需要显式 flush；close 释放内存，不删除文件。失败的保存不会留下半个新版本。API 同步执行，应由应用在保存点调用；当前尚未接入真实比赛界面或实现云同步。

```python
from gfootball.frame_sync.save_system import SaveManager, SaveType, GameProgress

progress = GameProgress()
progress.update_stats(match_played=True, won=True, playtime_seconds=90)
with SaveManager(path='saves/player.saves') as saves:
    if saves.get_slot('career') is None:
        saves.create_slot('career', '职业生涯', SaveType.PROGRESS)
    saves.save('career', progress.to_dict())

with SaveManager(path='saves/player.saves') as saves:
    restored = GameProgress()
    restored.from_dict(saves.load('career'))
```

默认限制如下，使用构造参数 limits=SaveLimits(...) 可在实现允许的硬上限内调整：

| 项目 | 默认上限 |
| --- | --- |
| 存档槽数量 | 10 |
| 单槽规范化 UTF-8 JSON 数据 | 1 MiB |
| manager 持有的槽对象及内容 | 8 MiB |
| 每次复制的对象图计费 | 4 MiB |
| 对象图节点 / 嵌套深度 | 16384 / 16 |
| 单容器成员 / 字符串 UTF-8 字节 | 4096 / 65536 |
| 槽 ID / 名称 UTF-8 字节 | 64 / 256 |

进度对象独立限制在一个 payload 预算内。集合的固定对象、锁和映射元数据另由数量上限限制；这些预算不是整个进程 RSS 的上限。编码、读取和更新会使用有界临时副本。调用方保留的历史 SaveSlot、导出字符串和 load/get 返回值属于调用方所有。

槽对象不可变，包含创建时或最近一次保存的快照。get_slot、list_slots、create_slot 的返回值不会随着之后的保存被修改；slot.data、load 和进度 get/to_dict 返回独立数据。请用 saves.save 更新槽，不能通过 slot.name 或 slot.data 修改内部记录。size_bytes 是规范化数据的实际 UTF-8 长度；get_storage_usage 的 retained_bytes 还包含槽对象、字段和 bytes 对象开销。

只接受普通 JSON 数据，tuple 会规范化为数组。拒绝自定义转换对象、循环引用、非字符串字段、非法 UTF-8、NaN/Infinity 和 int64 以外的整数。导入在 JSON 解码前检查字节数、深度和 token 数，再检查重复字段、版本、名称、时间和结构。旧版无 format/version 的单槽导出仍可导入，但不会信任其 size_bytes；未知字段和错误类型拒绝，返回 None。未知槽 save 返回 False、load 返回 None，容量或无效 save 数据明确抛错。

GameProgress 保留 career、unlocks、stats 必需结构，允许预算内的扩展字段。进度路径最多 8 段，不能跨越标量。统计数值为非负 int64，胜场不能多于已完成比赛，非法或溢出更新整体回退；解锁内容必须是无重复的字符串 ID。整个更新持有同一把锁，因此并发统计更新不会丢失。fork 后禁止沿用原 manager/progress/目录锁，使用 spawn 新建实例。

持久化格式为版本化 JSONL：集合头、按 ID 排序的完整槽记录、SHA256 页尾；校验包含头和所有记录。逐行读取受单行和集合预算约束，拒绝截断、额外记录、重复槽、未知版本或校验错误。没有使用 pickle。SHA256 用于损坏检测，不提供来源认证。

每次发布在共享目录的进程锁内校验当前版本，写入同目录临时文件，flush/fsync 后执行 os.replace。两个实例从同一版本写入时仅一个成功，另一个抛 SaveConflictError；调用 reload 检查最新存档后再决定更新。manager 不会自动合并或覆盖外部的新版本。文件状态按路径与描述符各自的时间字段比较，兼容 Windows 两个 API 返回不同 ctime 的行为。

如果已经完成原子替换，随后目录同步或锁释放报错，异常带 save_committed=True，manager 内存同时采用已发布版本；此时不能声称旧文件仍在。发布之前的写入、fsync、重命名和容量失败均保留原文件及内存状态。Windows 执行文件 fsync 和原子替换；POSIX 还实现父目录 fsync，但尚未运行 POSIX 验收。真实断电耐久性尚未验证。

磁盘默认目录预算为 64 MiB、32 个直接文件、最多 4 个同时预留写入，扫描最多 256 个目录项，可通过 disk_limits=SaveDiskLimits(...) 调整。所有协作写入者共用既有 DirectoryReservations，预留实际完整输出大小，旧目标文件在替换前仍占预算。控制目录 .football-recording-v1 最多 33 个固定元数据文件，每个最多 4096 字节，单独计限。正常失败清理自己的临时文件；进程崩溃释放 OS 锁，遗留临时文件保留并继续占磁盘预算。不会为腾出空间删除用户文件；不保证任意外部写入者或任意网络文件系统遵守协作配额。

2026-09-10 Windows 验证：35 项新存档检查通过，包含真实跨进程同版本竞争、重命名前后 os._exit、部分写入/fsync/替换失败、1000 次槽覆盖引用释放、16 线程槽准入、8 线程 800 次统计更新，以及大于 7.8 MB 的 10 槽集合重新启动校验。相关录制 129 项和帧回放 64 项亦通过复验。独立读取进程未导入 NumPy、OpenCV、Gym 或 GameEnv。实际运行是 Python 3.14.6；Python 3.9 仅检查语法。真实比赛/原生环境、POSIX、云同步及整体验收仍未完成。

运行专项检查：

```sh
python .project/checks/python_save_probe.py --output NEW_OUTPUT_DIRECTORY
```
