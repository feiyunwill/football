# 下一阶段优化执行报告

日期：2026-10-15。本轮本地实验与交付验证完成；远端CI、后续课程和GPU门禁仍待推进。
入口：[计划](next-optimization-plan-20261015.md)、[状态](next-optimization-state.json)、
[复现说明](../native-training/NEXT_OPTIMIZATION.md)。本报告不提升原产品里程碑。

## 当前版本基线

已运行完整质量门禁：72项Python集成测试、8个原生C++合约及相关训练/链接检查通过。
验收门禁自身的8项故障注入测试、学习统计/候选决策的6项测试通过。
恢复后的[当前质量报告](../native-training/evidence/o3-restored-quality-20261015-a/report.json)
绑定Python、依赖、编译工具和CI定义。

代码/资源manifest包含1,224项，SHA256为
`77856efdadd172e065bc9289b65deaa0339eddb5aa8b22f003f7f0759bb54c6c`。
撤回候选后，当前.so及core与原基线二进制SHA256相同。

[原始基线](../native-training/evidence/o1-baseline-20261015-a/report.json)
使用真实11v11、simple115v2、headless160×90；每配置256个joint transitions，8次轮换。
以下为关闭诊断计时的Gym scalar路径中位吞吐，单位joint transitions/s：

| 受控人数 | cadence | Python backend | Native backend |
|---|---:|---:|---:|
| 1 | 2 | 467.2 | 933.0 |
| 1 | 10 | 160.1 | 206.9 |
| 11 | 2 | 382.9 | 1009.7 |
| 11 | 10 | 155.2 | 266.1 |

这些是当前机器的基线，不是本轮新加速结果。11人的一次joint step仍计一个transition。
分阶段计时另行运行，开关计时的两类工作负载状态digest一致；native CLI的真实PPO
重复运行也得到相同完整状态hash。旧worker工具仍明确标为heuristic采样。

[逐步诊断](../native-training/evidence/o1-latency-20261015-a/report.json)
每组1024步，预设/反馈两类、1/11人×cadence2/10：step p99约1.53–7.00ms。
它包含逐步时钟的开销，不能替代正式长局或图形门禁。RSS前后采样不是内存泄漏证明。
当前WSL主机调度/频率未固定，历史吞吐和本轮数字不能直接用于宣称退化或提升。

## 引擎热点候选：撤回

当前源码的[gprofng样本](../native-training/evidence/o3-cpu-20261015-a/report.json)
采集16,384步，排除初始化/reset/快照IO；样本权重59.2秒。
空间递归更新exclusive约9.29%、inclusive约17.40%，Ball::Mirror约6.93%。
图索引只用于定位，相关源码已直接核对；图中的同名Mirror关系存在误关联，未用于调用链结论。

按[预登记协议](../native-training/O3_PROTOCOL.md)，试验Boost连续环形缓冲替换球历史链表，
保留序列化顺序、逆序求和和最多1000项快照历史；候选完整质量门禁通过。
容器边界probe验证6种恢复长度，各3000次push/pop/mirror；它不代替真实引擎快照合约。

主负载为1人/cadence10/预设动作，原版与候选1024步、8次交错配对：

- 逐步观测/奖励/内核轨迹对照和最终状态digest相同。
- CPU成本的配对中位数低约5.02%，未达到至少10%的保留门槛。
- CPU speedup的配对bootstrap95%区间为0.709–1.607，包含明显退化与提升，不能证明稳定收益。
- 主筛选失败后未继续其余七组性能测量，不能宣称通过完整性能矩阵或长局预算。

[决策与原始样本](../native-training/evidence/o3-primary-20261015-a/decision.json)
已保存，补丁位于同目录candidate.patch，仅作实验归档。三个候选生产文件已恢复，
[恢复记录](../native-training/evidence/o3-primary-20261015-a/restoration.json)
与当前质量报告均核对原manifest；没有保留该候选，也没有重复应用此前撤回的deque方案。

## 学习效果

[完整报告](../native-training/evidence/o2-learning-20261015-a/report.json)的协议执行与学习门槛均通过。
三个预登记配置各训练99,840 joint transitions，pilot seed7的32局调参成功率均为100%。
按预登记并列规则选择hidden16、scoring；没有用最终保留集选择网络或奖励。

随后五个独立训练种子各训练99,840 transitions，并在同一组200个保留episode seeds上评估：

| 训练种子 | 最终argmax真实进球成功率 |
|---|---:|
| 42 | 94% |
| 123 | 94% |
| 2026 | 100% |
| 31415 | 100% |
| 271828 | 100% |

均值97.6%，每种子均超过80%门槛。相对初始argmax模型的提升为97.6个百分点，
配对95%区间94.0–100.0个百分点；相对uniform random的提升为86.1个百分点，
区间80.30–91.20个百分点。bootstrap同时重采样训练种子和共享评估场景，
没有把1000局当作1000个独立训练重复。sample/argmax/random/builtin AI原始逐局结果均保留。

八次训练合计798,720 joint transitions；全部更新非零，多个新进程加载评估后的
完整checkpoint hash保持不变，source/resources前后指纹相同。模型保存在外部work-root，
每个模型均有SHA256；尚未替换产品默认AI。

可下载[五个训练模型与匹配Linux运行时](../native-training/evidence/o2-learning-20261015-a/trained-models-linux.tar.gz)，
约1.55MB，包含LICENSE、使用说明和文件manifest。
[归档收据](../native-training/evidence/o2-learning-20261015-a/trained-models-linux.json)
记录了独立目录解包后的真实加载/冻结评估验证。运行时仍需要匹配的仓库资源和宿主系统库，
不承诺跨ABI迁移。

该结论仅针对固定起始位置的native empty_goal，不证明对新位置、主动门将或11v11的泛化。
长训练CLI已有loss/entropy/clip fraction/gradient norm/参数变化曲线，尚未输出单独KL与value loss；
后续真实PPO worker工具补充这些诊断，不能替代本轮长训练的缺失字段。

## 实际多进程PPO

[完整报告](../native-training/evidence/o4-ppo-workers-20261015-a/report.json)通过。
在仓库外构建诊断模块，复用生产C++分类策略及PPO数学代码；每次更新收齐四个
真实episode（最多32步），按episode/step排序后做4个epoch更新。1/2/4 worker各三轮，
同配置的全部轨迹、更新指标和完整模型状态一致。
从1 worker的两次更新检查点切换到新进程4 worker续训，结果与不中断训练逐字节一致。
诊断接口的6项合约检查也通过。

单位为joint transitions/s；包含reset、IPC、真实推理、回调、hash、PPO更新及诊断，
排除启动、预热、关闭和写checkpoint：

| 受控人数 | cadence | 1 worker | 4 workers | 观测加速 |
|---|---:|---:|---:|---:|
| 1 | 2 | 487.0 | 1145.4 | 2.35× |
| 1 | 10 | 213.4 | 589.7 | 2.76× |
| 11 | 2 | 447.8 | 886.9 | 1.98× |
| 11 | 10 | 199.2 | 501.8 | 2.52× |

全配置达到2×的目标仍未通过：11人/cadence2为1.9803，不能四舍五入标为达标。
该配置4 worker时，父进程原生PPO更新约占墙钟24.4%，策略推理2.1%、回调5.1%、
额外诊断3.1%；其余时间混合引擎、reset、IPC与调度，尚不能归因为纯IPC。
下一步应进一步采样父进程更新与分离等待成本；依照计划，不为追逐小样本差距改为异步采样。

同时保存精确categorical KL(old||new)、更新后value loss、entropy、clip fraction和梯度指标，
诊断时间与原生更新时间分开。以上是短episode、重reset诊断，不是长时11v11学习效率承诺。
诊断JSON checkpoint不同于FPPO，也没有替换公开原生训练入口。

## 平台与交付

GitHub工作流已配置Python3.11/3.14矩阵，并加入统计/性能决策测试。
本机仅有CPython3.14；没有本轮远端CI执行记录，3.11仍待验证。
GPU性能验收继续暂停，1080p 16.67ms与完整产品发布依赖保持原要求。

[本轮交付报告](../native-training/evidence/o5-delivery-20261015-b/report.json)通过：
核对原始干净构建日志与相同源码/wheel SHA后，重新创建独立安装环境；
实际安装cp314 Linux wheel、依赖检查、仓库外资源定位、原生包迁移、动态链接、真实训练、
跨进程续训和冻结评估全部通过，安装后72项集成测试无跳过。
这次复用了已审计的wheel构建，不宣称新做了一次wheel编译或远端CI。
A轮使用间接构建收据被门禁拒绝，失败记录保留；B轮引用原始构建收据后完成验证。

## 总体审计与未完成门槛

[本轮证据审计](../native-training/evidence/next-iteration-audit-20261015-a/report.json)通过：
核对当前源码/环境、原始命令退出码与日志hash、恢复的实际二进制、模型文件、学习区间、
候选决策、实验工具版本，并再次执行8项质量自测与6项统计/决策自测。
审计通过表示本地证据相符，不等于所有性能目标、远端CI或产品发布通过。

后续仍需：带主动门将/变起始位置课程及更复杂对抗；长训练CLI的KL/value loss输出；
更稳定环境下的热点优化及11人/cadence2扩展效率；实际远端3.11/3.14 CI；暂停中的GPU验收。
既有产品里程碑和发布状态均按原质量编排处理，没有依据本报告自动提升。

## Subsequent CPU optimization

This report describes the pre-optimization iteration. See [the retained PPO CPU optimization](ppo-optimization-report-20261015.md) for current production source, quality and worker replay evidence. Earlier learning and delivery receipts remain historical.
