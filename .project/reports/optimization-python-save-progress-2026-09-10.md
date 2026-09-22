# task-21.1.2.1：有界存档与实际持久化进展（2026-09-10）

状态：进展。memory_budget.ready=false；task21.1.2.1、plan21.1.2、ms21 及全局优化目标未完成。

旧 SaveManager 只存于内存；虽然已有 deepcopy 修复，仍先无上限 json.dumps，返回可直接修改的内部 SaveSlot，导入缺少结构/大小/重复字段控制。GameProgress.get/set 仍与调用方共享引用，统计溢出和部分更新没有事务保证。ms-7.6 仍是 PENDING，其列出的 cloud_sync.py 在当前精确路径不存在；本轮没有把持久化实现计为该里程碑整体完成。

当前实现：

- save_system.py 保留旧实现注释并导出 save_data/save_runtime/save_store 的实际实现。不可变 SaveSlot 内部只持有规范化 bytes，默认 10 槽、每槽 1 MiB、槽对象及内容合计 8 MiB；复制图、节点、深度、容器、字符串和字段均有上限。导出/载入/槽属性不会泄漏内部可变引用。
- 普通 JSON 数据入库前复制并计费，不调用任意对象转换。导入解码前扫描大小/深度/token，拒绝重复 JSON 字段、非法版本、时间、数字和结构；旧单槽导出继续可读，实际大小重新计算。
- GameProgress 的 get/to_dict 返回独立副本，set/from_dict/update_stats/unlock_team 先校验完整候选再替换。必需 career/unlocks/stats 结构、int64 计数及胜场关系有校验，保留预算内扩展字段，公开操作加锁且拒绝 fork 后使用继承锁。
- 可选 path 启用真实完整集合 JSONL 持久化，头部版本/代数及 SHA256 页尾校验。使用已有跨进程 DirectoryReservations、实际大小预留、同目录临时文件、flush/fsync/os.replace。版本冲突要求 reload，错误或损坏不会覆盖已存数据。已经发布后若清理/同步报错，显式 save_committed=True 并同步 manager 内存，不能谎称旧版本保留。
- 默认目录 64 MiB / 32 文件 / 4 预留 / 256 扫描项，控制元数据固定有界。崩溃的 OS 锁可复用，遗留临时文件保留并继续计费。原文件与临时新版本同时占预算，不驱逐用户存档。
- 将 RecordingCapacityError 提取到 recording_errors.py，recording_buffers 保留同一个异常别名；目录层不再导入 NumPy。真实子进程只读存档未加载 NumPy/OpenCV/Gym/native。

使用方式、兼容性与具体限制见 [save_system.md](../../gfootball/doc/save_system.md)。

验证与证据：

| 归档 | 本轮执行 | 源码指纹数 |
| --- | --- | --- |
| python-save-windows-20260910-a | 35/35 | 21 |
| python-save-recording-windows-20260910-a | 129/129 | 28 |
| python-save-frame-replay-windows-20260910-a | 64/64 | 43 |
| python-reconnect-windows-20260910-d | 本轮未重跑；之前 201 项，仍匹配 | 36 |

所有当前源文件及各日志 SHA256 已核对。各批均无跳过、失败、错误、遗留工作线程、登记子进程或目录锁描述符，也没有 ResourceWarning/析构/异步线程错误。后三批重跑与以前的数量不能重复累加为新覆盖数。

专项 35 项中，实际验证了 16 线程竞争 10 槽、8 线程 800 次统计、1000 次覆盖旧槽弱引用释放、循环/异常对象/超深/超额拒绝、旧格式兼容，以及 15 项真实文件/子进程行为。两个独立进程从同版本写入只产生一个成功者；真实 os._exit(37/38) 分别发生于替换前/后，读者得到完整旧/新版本。大于 7.8 MB、10 槽完整集合在另一个真实 Python 进程校验，超额第九个大 payload 被拒且旧文件 SHA 不变。

初次直接运行的 30 项中有 11 项实际文件失败：Windows path.stat 与 fstat 的 ctime 不一致，被过严的跨 API 比较误判为竞争。已用独立真实临时文件探测确认，改为跨 API 比对 dev/inode/size/mtime，并分别对各自原始 ctime 复验；之后 30 项通过，扩展直接 51 项通过，最终归档 35 专项和全部受影响回归。未伪造原生模块或提取类体执行。

归档 SHA256：

- save/report：704aff524bac14384b8448cb07e7e0cc17d7c329c12aa7ad438dfef211c78b98；log：2d72c0a9bccf3cf6a9266a77e45d9c07de9cdcb6e6a5b296c93eb63aaf2833a6。
- recording/report：131be1fd3fcfb2bb5bc6e37c7d228447ee08b4bd8ff2512b4a6f2426779eff6a；log：4916bd512d742b72a913a575daffae91274359a6067bb6525ac7940ebf3688c4。
- frame-replay/report：a0766c1fce16c1392d38ca1cd0d0c06532fdd4ed941dea06fdbf9f7872a0730e；log：0f7335212e9b2f41579d9b43e4bcb7bd46d98d7b9c601f087cc352e9ec3570fd。
- 聚合 python-save-evidence-20260910.json：eae8d7ea495758684d430d3dd11670e928a885a07d1c09f48dab11dfac897e32。

当前机器为 Windows Python 3.14.6，6 个相关生产文件仅完成 Python 3.9 AST 语法检查。POSIX 锁/父目录 fsync/fork、真实断电、真实 GameEnv 与比赛界面保存、云同步尚未执行或实现。存档同步 API、暂存图和调用方保留的副本不代表整个进程内存/RSS或游戏帧延迟受控。本轮没有新 WSL 执行假设，未重复同样的超时探测或重置系统；未改动 C++、运行构建、执行 Git 或修改固定基线指针。

下一步继续 UDP 自动恢复及原生协议、实际比赛录制/回放/存档界面接入，恢复 Linux 后补齐全部原生与 POSIX 验收，再执行整体 memory_budget 和后续增长/性能、手感、网络、渲染、AI、发布里程碑。
