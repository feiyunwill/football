# 当前 11v11 基准与 ECS 旧查询参考复核

归属 ms-21.1 → plan-21.1.1 → task-21.1.1.1 / task-21.1.1.2。当前源码的正式 `match_benchmark` 已通过：两种子各 5 个独立进程、各 10,000 个稳态帧，状态哈希在同种子内一致；种子 42/43 的 p50 分别为 2.576/2.874ms、p95 为 3.987/4.404ms、p99 为 5.079/5.532ms。启动另计，RSS 最大观测增长均为 40KiB。完整硬件、编译参数、逐帧样本和 10 次运行见[当前基准原始归档](../optimization/evidence/ecs_query_legacy_reference_20260928_current_match.json.gz)及正式 `match_benchmark.json` / 对应日志。`task-21.1.1.1` 已由质量状态机判为 `verified`。

下一项 `ecs_performance` 在比较前失败：旧 `baseline.json` 指向 `/tmp/football-optimization-baselines/d5098f8b...`，其中的引擎二进制已不存在；[失败日志](../optimization/evidence/ecs_performance-1790585377931009804.log)保留。检索现存 134 份同名引擎库和 4 份基准程序，均不匹配旧清单哈希。历史源码恢复记录仍缺 37 份旧字节，不能把当前版自身重新登记为旧基线。

为评估当前查询实现，另在提交 `739d767` 的隔离 worktree 中仅把 `engine/src/ecs/query.hpp` 换为 Git 历史提交 `06668dc` 的版本，编译完整 Release 引擎并运行相同 11v11 基准。两份 1,145 文件的原始源码清单有 36 个哈希不同，其中 35 个仅是 Git 检出后的 CRLF/LF 字节差异，换行归一化后内容相同；唯一实际源码差异是查询头文件。参考版十次运行的比赛轨迹与当前版一致。参考版完整输入、编译参数与逐帧结果见[原始归档](../optimization/evidence/ecs_query_legacy_reference_20260928_legacy_match.json.gz)。这个参考版用于诊断，不冒充缺失的历史基线。

随后按每种子 15 对、交错顺序运行未插桩的旧查询参考版与当前版；每对的输入哈希、预热哈希、状态检查点、最终哈希和活跃帧标志完全一致。当前版/参考版的 CPU 几何均值比在种子 42 为 0.9653（95% bootstrap 区间 0.9180–1.0016），种子 43 为 1.0105（0.9814–1.0444）；墙钟区间也跨过 1。两种子均未满足“CPU 改善可信上界小于 1”的条件。当前实现对这个可追溯参考版没有稳定可证明的完整比赛收益，不能用它修补正式 ECS 门禁。完整 60 次运行与配对统计见[压缩原始记录](../optimization/evidence/ecs_query_legacy_reference_20260928_paired_runs.json.gz)、[可读摘要与哈希](../optimization/evidence/ecs_query_legacy_reference_20260928.json)和[执行脚本](../optimization/evidence/ecs_query_legacy_reference_20260928_probe.py)。

复现顺序：从 `739d767` 建立独立 worktree；将 `06668dc:engine/src/ecs/query.hpp` 写入该 worktree；在独立 Release 构建目录运行该 worktree 的 `match_benchmark.py`，对当前源码另运行正式 `match_benchmark`；用执行脚本按交错顺序采样并比对轨迹。脚本中的本机目录应指向对应的工作树、构建与归档路径。三个压缩归档均固定 gzip 时间戳为零，压缩与解压 SHA-256 记录在机器可读摘要中。

`task-21.1.1.2` 与 ms-21.1 当前为 `failed`。下一轮需定位当前比赛的真实分配/查询热区，提出能在同样完整比赛配对中稳定改善两个种子的实现；若参考基线设计变更，须在验收器中明确记录新旧语义并重跑上游质量链，不能静默替换指针或降低阈值。
