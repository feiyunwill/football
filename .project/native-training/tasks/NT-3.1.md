# NT-3.1 — 采样阶段计时与闭环 profile

2026-10-15。S2 review 已通过，开始 S3 测量任务。

实现候选：NativeTrainingEnv 默认关闭的诊断计时器。分离 action、engine step、
get_info、transition/termination、encoding、reward 和 NumPy binding output。
同一阶段累计纳秒数并记录实际 engine call / returned transition；计时不属于
snapshot 或 simulation digest。关闭时不调用时钟，保留少量 flag/branch 成本。
enable_profiling 每次清零，get_profile 获取受 mutex 保护的计数副本。

`gfootball.profile_native_training` 测量 1/11 人×cadence 2/10，六种路径：
Python scalar、raw native binding、native Gym scalar、native predetermined batch、
Python feedback 和 native feedback。每组重复并轮换顺序；启用/关闭计时分别
执行相同序列，要求对应 workload 的最终 kernel digest 相等。

policy 是读取当前观测的确定性轻量 heuristic，不宣称 PPO/model inference。
predetermined batch 不代替 closed-loop 策略；二者分别报告。绑定 output 是
实际 NumPy 分配/复制/tuple 构造计时，其余墙钟差额明确为未细分的 adapter、
参数转换、C++ admission/allocation、锁及计时本身等开销，不直接命名为绑定。

当前主机 /tmp 已清理，重新创建虚拟环境并按 requirements 安装；使用新的
隔离目录 `/tmp/football-native-assessment-20261015`。旧 S2 日志保留，新测量
须使用当前构建与库版本（本次 Gymnasium 1.4.0、NumPy 2.5.4）。

验证入口：`validate.py`（包含 profiling on/off 的 scalar/batch 数值及 digest
对照）；测量入口：`validate_profile.py --python ... --build-root ... --output ...`。
当前构建与集成验收通过：47 项 Python 测试（62.590 秒）及四个 C++ 合约；
计时 on/off 对照未改变 scalar/batch 数值和 digest。证据为
`evidence/nt-3.1-integration-20261015-a/report.json`，1200 个源码/资源前后
fingerprint 为 `60835581fbebff949f465f011adb7953c90f0997f8af5d0728b15ecaa9b3c603`。
独立测量 `evidence/nt-3.1-profile-20261015-a/` 已完成，report.passed=true，
instrumented/uninstrumented 与同 workload 的所有路径 digest 对照通过。
完成日期为 2026-10-15；结果及限制见 [PERFORMANCE.md](../PERFORMANCE.md)。
engine step 为 native scalar 墙钟的约 93%–98%，内部函数 CPU 采样留给
下一任务选择优化前完成；不将层级定位声称为已经找到某个引擎函数热点。
图 coverage generation 2026-10-14T19:52:54Z，材料路径 metadata_match，
无记录缺口；时间按用户 Asia/Shanghai 日期说明，coverage 不证明穷尽。
