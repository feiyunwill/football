# 存档兼容性与资源身份进展（2026-09-10）

归属 `ms-21.1 → plan-21.1.2 → task-21.1.2.1`。本轮是实施进展；整体 memory_budget.ready=false，目标保持 ACTIVE，任务、计划及 ms-21 至 ms-26 未标为完成。

## 发现与实现

原生 FSTA 已有格式版本、长度、CRC 和异常回滚，但这些机制不能识别完整快照来自不相容的核心库或资源。原先本地续玩和回放在调用 set_state 后才对比状态摘要，无法阻止不相容数据进入反序列化。

新增 match_identity.py，使用有界身份字段与流式文件指纹。match_archive.py 的载荷升级至 checkpoint v2；local_runtime.py 的续玩、副本初始化和 playback 都在 set_state 前比较身份。录制封存时再次检查，失败保留原文件并关闭已拥有资源。旧 v1 缺少身份，明确拒绝自动恢复或覆盖；没有旧文件迁移或安全来源认证声明。自定义引擎必须显式提供身份，测试 oracle 标明自己的格式。

原生适配器保留实际 GameEnv：构造前后检查实现与资源，之后只在存档/恢复边界重新计算，step 仍直接委托原引擎。Linux 原生路径识别实际映射的扩展和 libfootball_engine，校验设备号/inode 后哈希，不把 Python 包文件当作核心库版本。实现指纹包括场景、环境源码和初始化策略；资源指纹覆盖数据和显式配置字体。当前限定 Linux 64 位小端、headless、10 Hz。此原生路径尚未执行验证。

## 文件边界与实测发现

单次读取 64 KiB，单文件 256 MiB，单集合 512 MiB，8192 遍历条目、512 目录、深度 16；元数据与读取前后检查可拒绝中途替换、增长、缩短和目录增删。没有在逐帧路径计算资源指纹。Windows 的 path stat 与 fstat 可能使用不同 ctime，跨 API 只比较共同身份字段，每个 API 独立检查自己的完整时间戳。

实际资源预检发现数据目录的 Alegreya 字体回退链接无法通过 Windows/WSL UNC 读取。直接检查 game_env.cpp 的初始化分支确认，设置 GFOOTBALL_FONT 后只使用显式字体。现在仅排除该精确的未使用回退入口，并哈希实际字体；其他链接或 reparse 仍拒绝。第一次资源预检失败，目录 a 保留；修正后的 b 成功。该发现没有通过改动资源或绕过任意链接检查处理。

## 自动证据

最终 frame_replay_probe.py --match：143 项通过，0 失败/错误/跳过/资源告警，0 测试拥有的线程、进程或锁描述符残留。组成：身份兼容性 9、文件指纹 10、proc-maps 解析夹具 4、本地比赛 21、帧/辅助 64、存档 35。Python 3.9 仅做 9 个生产路径 AST 检查，没有运行 3.9。

新检查验证所有身份字段不匹配时零次 set_state、损坏身份在 Base64 解码前拒绝、旧存档/回放在工厂前拒绝、副本不相容关闭双端、录制资源漂移不替换旧文件；文件内容、改名、增删、读取中变化、容量拒绝、显式字体选择和有界读取；映射解析覆盖核心库、扩展、路径空格、已删除映射、非法 inode/device 和记录长度。符号链接拒绝测试是明确的 scandir 条目夹具，不能作为真实 POSIX 链接验收。

资源测量在 Windows Python 3.14.6、实际 UNC 仓库文件、tracemalloc 开启条件下执行。资源 90,974,146 字节、5.927862 秒、Python 分配峰值 1,147,201 字节，最大请求 65,536 字节；源码策略 352,220 字节、1.136546 秒、峰值 149,252 字节。只测 Python 分配及当前边界 I/O，不是整个进程 RSS 或 Linux 性能通过。

| 证据 | 项目数 | 本轮执行 |
| --- | ---: | --- |
| python-match-identity-windows-20260910-b | 143 | 是 |
| python-match-identity-files-windows-20260910-b | 两组实际文件测量 | 是 |
| python-udp-resume-windows-20260910-b | 219 | 否，41 个源文件及日志指纹仍匹配 |
| python-save-recording-windows-20260910-a | 129 | 否，28 个源文件及日志指纹仍匹配 |

当前 143 项归档含 53 个源文件。旧 local-match b120、identity a142 已因源码变化过期，保留历史文件；不可用其指纹声明当前通过。

- .project/optimization/benchmarks/python-match-identity-windows-20260910-b/report.json：报告 SHA256 `9b1146813b99b5a4238d3a56588be1c6ab0532bae20ab81ed301a6221800858b`；日志 `df765ae03c1cb4f16f74fdbfbe153e2576dcc37d8dec2b945cbdc0e30d3e31b6`。
- .project/optimization/benchmarks/python-udp-resume-windows-20260910-b/report.json：报告 SHA256 `4c7efda9d4a07468467fd5bab387ed631377879a99aaf80a5c6fd3eeebea3dba`；日志 `ff0dbbc6c0d775f08bf4f6f0c4c3af7b8edba55713cb5645f2a934e72aae714e`。
- .project/optimization/benchmarks/python-save-recording-windows-20260910-a/report.json：报告 SHA256 `131be1fd3fcfb2bb5bc6e37c7d228447ee08b4bd8ff2512b4a6f2426779eff6a`；日志 `4916bd512d742b72a913a575daffae91274359a6067bb6525ac7940ebf3688c4`。
- 资源测量报告 SHA256 `b29ec0a01a882a7920d8e0cfce208ffe46ef9e325590a47fea570f3e02a4ddc0`。
- 聚合证据 python-match-identity-evidence-20260910.json SHA256 `f2caca19cd5a5c5c91971068f158f8d851a3425cbb6f6d44086ca8807344ed30`。

## 后续任务

继续替换 Host/Join/Settings 的旧占位流程，连接真实比赛推进与客户端引擎。原生执行环境恢复后，先执行新增的 2 项实际库身份/GameEnv 存档回放检查，再推进 C++ 网络、POSIX 文件、图形输入与长时内存/性能验收。二进制/资源身份机制已实施，Linux 原生端尚未验证；跨版本迁移、来源认证与任意原生载荷安全不在本轮通过范围。

本轮没有 Git 操作、C++ 修改或构建、包安装、WSL 重试/重置、正式门禁绕过或子代理。main_menu 的 Host/Join/Settings 本轮未改，不将整个产品流程标为完成。
