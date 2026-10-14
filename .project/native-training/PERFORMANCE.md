# 采样成本基线 — NT-3.1

日期：2026-10-15。构建为当前隔离 Release，Python 3.14.7 / NumPy 2.5.4 /
Gymnasium 1.4.0 / pybind11 3.1.0。原始证据：
[profile report](evidence/nt-3.1-profile-20261015-a/report.json) 与
[全部样本](evidence/nt-3.1-profile-20261015-a/profiles.json)。

每组 256 个返回 transition，固定 seed 42、20 步 warmup，6 次重复、轮换
六条路径的顺序；reset/warmup、profile 查询和最终 digest 不计入墙钟。
默认 scoring、unstacked simple115v2、headless 160×90。数值是本机实测，
不是 PPO 训练吞吐或跨硬件承诺。

## 未启用计时的吞吐

单位：返回 transition/s；11 人的一次 joint step 仍算一个 transition。

| 玩家 | cadence | Python scalar | raw native | native Gym scalar | native batch32 | Python feedback | native feedback |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 750.3 | 1392.4 | 1298.7 | 1328.3 | 748.2 | 1246.1 |
| 1 | 10 | 226.9 | 275.2 | 269.5 | 283.0 | 244.6 | 287.9 |
| 11 | 2 | 402.7 | 1208.6 | 1135.2 | 1260.9 | 430.4 | 1204.5 |
| 11 | 10 | 190.7 | 319.9 | 301.7 | 324.1 | 188.9 | 279.1 |

native Gym 相对 Python scalar 的中位吞吐比为 1.731、1.188、2.819、1.582；
batch 相对 native scalar 为 1.023、1.050、1.111、1.074。它们只对本次配置/
动作序列成立。feedback 使用读取当前观测的确定性小 heuristic，两种 backend
执行相同策略；不是预置动作 batch，也不是模型训练/推理成本。
该策略本身平均占 native feedback 墙钟约 2.37%、0.79%、2.39%、0.78%。

## native Gym scalar 阶段成本

下表为开启诊断计时后的阶段中位数 / 墙钟中位数；阶段分布与吞吐分开看，
不要将其直接套到未启用计时的吞吐上。

| 玩家/cadence | engine step | get_info | action | encoding | binding output |
|---|---:|---:|---:|---:|---:|
| 1/2 | 93.94% | 0.42% | 0.04% | 0.06% | 0.22% |
| 1/10 | 97.91% | 0.14% | 0.01% | 0.02% | 0.09% |
| 11/2 | 92.97% | 0.41% | 0.10% | 0.08% | 0.23% |
| 11/10 | 96.97% | 0.16% | 0.03% | 0.03% | 0.12% |

transition/termination、reward 和未细分残差保存在完整 JSON。
binding output 只测 NumPy allocation/copy/tuple 构造。残差含 Python adapter、
输入转换、C++ admission/output allocation、锁、计时调用等，不能全部解释为
pybind 开销。计时关闭时不调用 clock，但仍有 flag/branch 成本。

## 证据与限制

- 各重复、Python/native/raw/batch 的预设动作最终 kernel digest 一致；
  两条 feedback 路径也一致，计时开启/关闭的两个 workload digest 相等。
  集成另外逐值测试 scalar/batch 的 profiling on/off，不能只靠计时结果宣称语义相同。
- 47 项 Python 测试和四个 C++ 合约通过，原有默认 Python 回归保留。
- 测量和集成的 1200 个源文件/资源前后 fingerprint 一致：
  `60835581fbebff949f465f011adb7953c90f0997f8af5d0728b15ecaa9b3c603`。
- 原始样本存在明显波动。未计时 native scalar 的 256 步 min–max 分别为
  186–232ms、876–992ms、213–241ms、785–968ms。11 人/cadence10 的后半
  计时组总体更慢约一成，不能据此单独估算 instrumentation 的精确开销。
  环境为 WSL，主机调度/频率未固定，不能把几个百分点当成可靠优化收益。
- 当前 profile 定位到 engine step 这一层，尚未完成内部函数的 CPU 采样。
  perf 未安装，GNU gprofng 2.47 可用；下一任务先取引擎内部样本再选择实现。

## NT-3.2 入口

本次主要成本在 engine step。先进一步定位其中的实际热点，再选择一个有
语义/hash 对照的候选优化；不优先改不到 0.5% 的观测编码或 output copy。
同 seed/scenario/actions 的原实现和候选交错测量，记录波动；无稳定收益则
记录并停止扩展。进程隔离与闭环 worker 另属 NT-3.3/3.4。
