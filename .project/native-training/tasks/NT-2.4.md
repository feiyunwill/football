# NT-2.4 — 长回放、资源与 sanitizer

完成日期：2026-10-14。Release 集成及完整 ASan/UBSan/LSan 验收通过。

已加入的验收入口：

- `engine_training_soak_contract`：六种 seed/左右队/1、2、11 人/阵容/cadence
  配置，累计 6144 个配对返回 transition；24 次在目标额外步进后恢复的快照，
  逐帧观测/奖励/终止对照，定期 kernel hash。当前 soak 的 12 次 reset 是六组
  双环境初始化；正常终态反复 reset 由原生短合约强制覆盖，Python 资源循环
  另强制执行 12×3 轮 reset/恢复。
- `gfootball.test_training_resources`：三种实际 scenario/seed 的独立进程长
  轨迹哈希；重复 reset/恢复/关闭后的 EnginePool、文件描述符和 RSS 采样。
- `validate_sanitized_training.py`：bindings OFF、完整 engine/core 库启用
  ASan/UBSan；运行原生、格式、恢复和 soak 四个 C++ 合约。

资源门禁：热身后 RSS 区间跨度最多 64 MiB，文件描述符与 EnginePool 预约
保持基线。RSS 只证明当前有界 workload 的行为，不作为无泄漏证明；LSan
另独立开启。sanitizer quarantine 限 16 MiB，避免工具的释放后保留掩盖资源
测量。外部 SDL/系统库不是此构建的源码 instrumentation 范围。

发现并修复的候选问题：C++ fatal rollback 关闭内核时，Python wrapper 可能
仍保留 engine reservation。新增 is_closed 查询，在恢复错误后释放已关闭
内核的预约并更新 Gym lifecycle；测试以实际 core close + 异常注入验证退款，
不声称已经直接制造了 C++ 内部回滚双重失败。

首轮 a 已结束且失败：LSan 记录 38 个未释放 PlayerData，共 9120 字节。
TeamData 原来构造十一人后直接缩小 raw-pointer vector，丢弃稀疏阵容尾部指针。
修复使用局部 unique_ptr 先拥有十一人，保留原 PlayerData 构造的 RNG 次序，
然后只释放所需玩家的所有权至 TeamData；未保留者自动销毁。
复验输出为 `evidence/nt-2.4-sanitized-20261014-b/`，四个合约均通过，
启用 detect_leaks=1，未使用 suppressions。修复前后证据均保留。

## 最终证据

- Release：[report.json](../evidence/nt-2.4-integration-20261014-a/report.json)。
  46 项 Python 测试通过（71.482 秒），四个 C++ 合约通过；bindings OFF
  依赖及 Python/native 使用相同 core artifact 的检查通过。
- ASan/UBSan/LSan：[report.json](../evidence/nt-2.4-sanitized-20261014-b/report.json)。
  core/游戏/base 库编译参数检查与 sanitizer linkage 检查通过，不仅 instrument 测试。
- 两轮均为 1198 个源码/资源的相同前后 fingerprint：
  `6dc1cf8cd185d96a5ed3b589c25dc8c616ca1a3e624c43bfbdc544a7e85a1948`。
- Release soak：6144 transitions、24 restores、384 hash 对照；RSS 区间
  123875328–137678848 bytes，4 个 fd。
- Sanitized soak：相同次数；RSS 区间 231129088–244494336 bytes，4 个 fd。
- Python 热身后九个资源采样均为 475430912 bytes / 6 个 fd；每轮 live/leased
  与基线相同。这是当前 allocator/workload 的测量，不承诺其他负载的固定 RSS。
- 三个跨进程 256-step 轨迹包括观测、agent reward 和每步 kernel digest；
  academy_empty_goal_close/seed7、academy_run_to_score/seed42、
  11_vs_11_easy_stochastic/seed101 均与父进程一致，日志保存实际 SHA256。

task 验收通过不等于 S2 整体 review；下一步审查整个阶段 diff、身份与格式、
恢复边界、所有权、默认 Python 路径和构建/交付影响，再决定是否进入 S3。
