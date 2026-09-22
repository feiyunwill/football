# 历史里程碑实现审查与优化（2026-09-09）

覆盖 **95 条里程碑记录**：86 份独立文档，加上 Phase17/18 仅在阶段文档定义的 9 条。Phase6 的 8 组重复 ID 按来源分别保留。

本次核对实现、实际调用和验收证据，并落实可回归的正确性与构建优化。旧文档的“完成”不等于已经验收；没有用占位实现补写未接通的大型子系统。

## 关键结论

- **P1 帧同步：**修复整帧槽位输入、帧 0、预测阻塞、连续回滚旧快照、TCP 双步推进及 hash 算法不一致。客户端和服务端共用初始场景；移除机器专属目录；TCP 广播实际已执行的输入，并使用客户端支持的全量消息。
- **P1 ECS：**修复组件排序丢失字符串、遍历与调度顺序不稳定、依赖漏写及触球数组越界。完全移除 OOP 的历史声明不成立。
- **P1 编码/大厅：**修复 0xFF 转义、全量 fallback、快照失败污染；大厅测试改为生产实现，修复 TCP 定界、收发争抢与断开清理。
- **P1 验收：**原 CTest 发现 0 项，CI 只跑 3 个目标并吞掉 E2E 失败。现已注册全量测试、编译生产目标，Python 外部服务测试明确跳过并以断言判断失败。
- **P2 未完成集成：**AI 战术、RL 多环境、IBL/后处理、观战、快照传输和大厅转接仍有剩余工作。未将它们标记为本轮完成。

## 验证记录

环境：Arch Linux / WSL，GCC 16.2.1，CMake 4.4.3。C++ 单测关闭 PCH，编译统一 `-j 1`。结构化结果见 [validation JSON](milestone-validation-2026-09-09.json)。

| 验证层次 | 实际结果 | 边界 |
|---|---|---|
| 生产编译 | UDP/TCP 客户端与服务端、大厅、headless 共 6 个目标通过 | 不等于运行或渲染通过 |
| CTest | **421 通过，0 失败** | 默认关闭计时门槛，保留结果正确性断言 |
| Python | **165 通过，10 跳过** | 10 项需要外部服务，通过参数显式启用 |
| 优化构建基准 | **8 通过**；DeltaCodecThroughput 12 ms | `-O3`，非整场 FPS 保证 |
| ASan + UBSan | **30 通过，无报告** | 覆盖 ECS/编码/共享模拟/PRNG 回归，未对全引擎做 sanitizer 验收 |
| 真实 GameEnv | 2v2 槽位、种子 42/43，各 2 个独立进程 × 1000 帧；各自快照恢复重放一致 | 相同平台/工具链，默认输入；非网络丢包证明 |
| TCP 运行冒烟 | 1 个服务端 + 2 个无窗口客户端，握手/Ready 后运行 5 秒，没有 hash mismatch 日志 | 未断言已确认帧数，不计为完整网络确定性 E2E |

真实引擎最终 hash：seed 42 为 `25f5d42974a8c79d`，seed 43 为 `ecbf4729db088aa3`。修复字体链接后，回归使用仓库字体重跑通过。

本轮初次 Debug 测试发现 `ECSBenchmarkTest.ConditionalQuery` 计时比例为 127.44，超过原 100 倍阈值，但处理结果一致。现默认配置验证结果，显式性能配置验证耗时；同一测试在优化构建中通过。没有宣称跨机器性能提升百分比。

可复现命令（仓库根目录）：

```bash
cmake -S engine/tests -B /tmp/football-tests -DCMAKE_BUILD_TYPE=Debug -DENABLE_PCH=OFF
cmake --build /tmp/football-tests -j 1
ctest --test-dir /tmp/football-tests --output-on-failure
python -m pytest gfootball/frame_sync/ -q
cmake -S engine -B /tmp/football-engine -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/football-engine -j 1 --target football_client football_server football_client_tcp football_server_tcp football_lobby headless_match
python3 engine/tests/run_headless_regression.py bin/headless_match --frames 1000
```

性能配置使用 `-DCMAKE_BUILD_TYPE=Release -DENABLE_PERFORMANCE_TESTS=ON`；外部 Python 网络测试用 `--run-network-integration`，须先按测试要求启动服务。新 [原生回归脚本](../../engine/tests/run_headless_regression.py) 已加入 CI；GitHub 远程 CI 本轮未触发。

## 每个里程碑

“模块验证”不表示真实网络、GPU 或跨平台验收完成。后续动作列出剩余优化与验收要求。

| 里程碑（来源） | 本轮结论 | 具体实现与发现 | 剩余优化 / 验收 |
|---|---|---|---|
| [ms-1.1: 基础协议稳定性](../milestones/ms-1.1-protocol.md) | 部分验证 | 协议、心跳有测试；历史“100 场 E2E”缺少本次可复现证据。 | 补多客户端真实引擎与丢包测试。 |
| [ms-1.2: 确定性基础](../milestones/ms-1.2-determinism.md) | 模块验证 | FixedPoint/CORDIC 与 PRNG 可测；单平台通过不代表跨平台确定性。 | 在 GCC/Clang、x86/ARM 重放相同输入，逐帧比较 hash。 |
| [ms-1.3: 客户端预测与回滚](../milestones/ms-1.3-prediction-rollback.md) | 已修复核心缺陷 | TCP/UDP 共用整帧模拟，修复槽位覆盖、帧 0、预测阻塞和连续回滚的旧快照。 | 继续对照旧 Asio/Python 客户端及真实网络回滚。 |
| [ms-1.4: 动态追帧与抖动平滑](../milestones/ms-1.4-dynamic-catchup.md) | 部分优化 | 先消费权威帧再限制预测，每 tick 最多追 3 帧，接收队列有界。 | 把实际抖动统计接入播放时序并验证延迟。 |
| [ms-1.5: 外挂校验](../milestones/ms-1.5-cheat-validation.md) | 部分验证 | 输入合法性校验存在；新模拟检查槽位数量与 SlotInput。 | 补生产服务器跨槽位注入、超前帧及速率限制测试。 |
| [ms-1.6: 逻辑渲染分离](../milestones/ms-1.6-logic-render-separation.md) | 已修复核心缺陷 | TCP 服务端 StepWithInput 后又 step 导致双步；已删除重复推进。 | 验证渲染不会修改确定性逻辑状态。 |
| [ms-1.7: 渲染平滑](../milestones/ms-1.7-render-smoothing.md) | 部分修复 | 插值 alpha 改为距最近逻辑步的时间，原实现使用渲染间隔。 | 在 GPU 上验证球员、裁判、旋转及高速运动。 |
| [ms-1.8: 性能优化](../milestones/ms-1.8-performance-optimization.md) | 验收不足 | Debug 时间阈值与正确性测试混用；已分离默认性能门槛。 | 固定 Release 环境测 p50/p95/p99，不能由微基准宣称 60fps。 |
| [ms-2.1: Team ECS 迁移](../milestones/ms-2.1-team-ecs.md) | 部分迁移 | TeamStateComponent 存在；Team 对象仍参与实际比赛。 | 按字段定义唯一权威来源并做迁移差分测试。 |
| [ms-2.2: Referee ECS 迁移](../milestones/ms-2.2-referee-ecs.md) | 部分迁移 | RefereeStateComponent 与旧 Referee 并存。 | 对犯规、越位、定位球进行规则对照。 |
| [ms-2.3: Match ECS 协调](../milestones/ms-2.3-match-ecs.md) | 已修复核心缺陷 | SystemGraph 使用稳定注册顺序，缺失依赖提前拒绝；players 显式依赖 physics 同步。 | 保留真实比赛 hash 基线，验证调度变更。 |
| [ms-2.4: 序列化完整性](../milestones/ms-2.4-serialization.md) | 已修复越界 | 触球源数组只有 4 项却读 8 项；按实际长度复制并初始化余项。 | 序列化仍从 OOP 同步，补全部 ECS/RNG 恢复验收。 |
| [ms-2.5: 性能验证](../milestones/ms-2.5-performance.md) | 已优化基础设施 | 组件池缓存有序实体 ID，避免为了顺序搬动组件。 | 在真实比赛规模测查询、复制与总帧成本。 |
| [ms-3.1: RL 基础训练框架](../milestones/ms-3.1-rl-framework.md) | 训练 POC | PPO 训练流程存在；checkpoint 写入结果和 tellg 缺少完整校验。 | 补坏文件、磁盘错误、往返测试及固定预算奖励曲线。 |
| [ms-3.2: RL 训练优化](../milestones/ms-3.2-rl-optimization.md) | 部分实现 | 真实包装 N_ENVIRONMENTS=1，不能宣称多环境训练优化完成。 | 统一 RLtools 路径，隔离实例后测吞吐与收敛。 |
| [ms-4.1: AI 战术系统](../milestones/ms-4.1-ai-tactics.md) | 未接通且有逻辑缺陷 | 未发现 TacticsController 比赛调用点；中心 50、球门 0/100 与实际坐标约定不符。 | 构造真实球员、攻防方向和比赛上下文，再接入控制器。 |
| [ms-4.2: AI 决策优化](../milestones/ms-4.2-ai-decision.md) | 未验收 | 权重跨帧残留；体力/控球写死；剩余时间实际为已过时间；传球目标可能选自身。 | 抽取纯决策函数，覆盖换边、末段领先、无球和按钮释放。 |
| [ms-5.1: 帧同步鲁棒性增强](../milestones/ms-5.1-framesync-robustness.md) | 部分修复 | 统一 SHA256 前 8 字节小端 hash，修复回滚、初始场景和输入广播一致性。 | 故障注入验证重连、快照重同步与机器人接管。 |
| [ms-6.1: 性能优化](../milestones/ms-6.1-performance.md) | 部分优化 | 修复编码与查询确定性缺陷，分离计时门槛。 | 根据 CPU profile 确定热点。 |
| [ms-6.1: UI 系统](../milestones/ms-6.1-ui-system.md) | 未完成 | 菜单含未调用且使用不存在 API 的 HandleInput，已归档死代码以恢复构建。 | 实现事件派发、跳转和设置持久化；未宣称菜单可交互。 |
| [ms-6.2: 音效系统](../milestones/ms-6.2-audio-system.md) | 未验收 | 音效模型与实际音频播放不同。 | 按 ms-7.3 接后端与资源验收。 |
| [ms-6.2: 网络优化](../milestones/ms-6.2-network.md) | 部分优化 | 统一整帧模拟、修正压缩边界；TCP 回退到客户端支持的全量权威消息。 | 可靠 UDP 和未来帧输入队列仍需生产故障测试。 |
| [ms-6.3: 内容系统](../milestones/ms-6.3-content-system.md) | 内容未达标 | 球队、球场样例数量有限。 | 按 ms-7.5 建资源验收清单。 |
| [ms-6.3: 体验优化](../milestones/ms-6.3-experience.md) | 部分实现 | 离线入口、接管和 UX 模块存在，菜单路径未完全接通。 | 验证断线/重连输入所有权切换。 |
| [ms-6.4: 代码质量](../milestones/ms-6.4-code-quality.md) | 已改进 | 无 PCH 构建发现隐藏 include 依赖，已补齐；修复 flat_map 代理引用迭代。 | 维持无 PCH CI，继续审查线程间所有权。 |
| [ms-6.4: 教程系统](../milestones/ms-6.4-tutorial-system.md) | 模型实现 | 教程与挑战有进度模型。 | 按 ms-7.4 绑定比赛事件。 |
| [ms-6.5: 语言现代化](../milestones/ms-6.5-language-modern.md) | 部分验证 | 主工程强制 C++23，GCC16 编译暴露旧未构建目标的错误。 | 用 GCC15 最低工具链持续验证。 |
| [ms-6.5: 统计系统](../milestones/ms-6.5-stats-system.md) | 模型实现 | 统计和赛季有 Python 测试。 | 验收比赛事件采集、归档和重算。 |
| [ms-6.6: 多语言支持](../milestones/ms-6.6-i18n.md) | 未充分验收 | 业务模块测试不能证明界面多语言完整。 | 验证资源覆盖、字体、编码与切换。 |
| [ms-6.6: 测试覆盖](../milestones/ms-6.6-test-coverage.md) | 已修复验收缺陷 | enable_testing 修复 CTest 0 项；CI 全量测试；Python 返回 False 不再假通过。 | 分开记录单测、服务依赖、性能和真实比赛测试。 |
| [ms-6.7: 文档完善](../milestones/ms-6.7-documentation.md) | 已整理 | 95 条实现复核，Phase6 重复 ID 按来源保留。 | 让历史状态与代码事实对齐。 |
| [ms-6.7: 平台适配](../milestones/ms-6.7-platform.md) | 未跨平台验收 | 本轮为 Arch Linux/WSL、GCC16，不等于 Windows/macOS/ARM 已通过。 | 建立平台矩阵及字节序测试。 |
| [ms-6.8: 构建优化](../milestones/ms-6.8-build-optimization.md) | 已改进 | 修复 CMake 最低版本、缓存类型、CTest 注册；新增 TCP/大厅目标，单线程编译。 | 先保证所有生产目标可构建，再比较 PCH/Unity 收益。 |
| [ms-6.8: 发布准备](../milestones/ms-6.8-release-prep.md) | 未达到发布验收 | 仍有主流程未接通及网络/GPU 验收缺口。 | 按本清单关闭阻塞项并保留干净构建产物。 |
| [ms-7.1: 大厅系统](../milestones/ms-7.1-lobby.md) | 部分修复 | 匹配曾忽略分差窗口；改为评分排序，在扩大中的窗口内比较相邻候选。 | 接通实际网络房间和持久化玩家档案。 |
| [ms-7.2: 排行榜系统](../milestones/ms-7.2-ranking.md) | 模块验证 | ranking/season 有测试；计划 elo.py 路径不存在，评分功能部分合并。 | 验收跨赛季结算、并列排名与持久化。 |
| [ms-7.3: 音效系统](../milestones/ms-7.3-audio.md) | 模型实现 | audio_manager/commentary 管理状态，不证明实际音频播放与混音。 | 接资源和音频后端，验证音量、静音、优先级与释放。 |
| [ms-7.4: 教程系统](../milestones/ms-7.4-tutorial.md) | 模型实现 | tutorial/training/challenges 有课程与进度逻辑。 | 绑定真实动作和比赛事件，验证推进与重试。 |
| [ms-7.5: 内容系统](../milestones/ms-7.5-content.md) | 内容未达标 | 内置约 5 支球队、3 个球场，与文档 50+/20+ 不符。 | 建立资源、许可、数量与加载验收清单。 |
| [ms-7.6: 存档系统](../milestones/ms-7.6-save-system.md) | 已修复数据缺陷 | 存档/读取/进度浅拷贝导致嵌套串改；已深拷贝并在导入前验证。 | 仍为内存槽位加 JSON 导入导出；磁盘落盘与云同步未实现。 |
| [ms-7.7: 集成测试](../milestones/ms-7.7-integration-test.md) | 部分验证 | 测试可独立于原生引擎收集；网络返回 False 现在通过显式断言判定。 | 10 项外部服务测试默认明确跳过；用 --run-network-integration 启用。 |
| [ms-8.1: Officials ECS 迁移](../milestones/ms-8.1-officials-ecs.md) | 部分迁移 | Officials 组件存在，比赛仍使用旧裁判对象。 | 对事件、动画和生命周期做差分验证。 |
| [ms-8.2: Player核心状态组件](../milestones/ms-8.2-player-state-ecs.md) | 部分迁移 | Player 核心状态映射 ECS，但保留 Player/Humanoid 引用。 | 逐字段验证换人、红牌和状态恢复。 |
| [ms-8.3: Humanoid动画状态组件](../milestones/ms-8.3-humanoid-state-ecs.md) | 部分迁移 | Humanoid 动画组件存在，旧动画对象仍驱动运行。 | 覆盖动作切换、触球帧和回滚重放。 |
| [ms-8.4: MentalImage ECS化](../milestones/ms-8.4-mentalimage-ecs.md) | 部分迁移 | MentalImage 组件与缓存同步存在，依赖比赛对象。 | 验证玩家增删的缓存失效和观察顺序。 |
| [ms-8.5: ECS系统性能优化](../milestones/ms-8.5-ecs-performance.md) | 已优化并回归 | 有序 ID 视图保留稠密存储，修复排序移动导致字符串组件丢失。 | 测相同负载下的分配、查询与缓存成本。 |
| [ms-8.6: 移除OOP双向同步](../milestones/ms-8.6-remove-bidirectional-sync.md) | 未完成声明目标 | Match 加载状态后仍调用 SyncEcsFromOop，双向同步没有完全移除。 | 完成 ECS 序列化并证明恢复等价后再删旧同步。 |
| [ms-9.1: 移除OOP包装层](../milestones/ms-9.1-remove-oop-wrapper.md) | 未完成声明目标 | ecs_direct_systems 存在；Match 仍创建 Team/Referee 等对象。 | 按实际调用链分模块验收，不以命名判断迁移。 |
| [ms-9.2: 优化ECS查询接口](../milestones/ms-9.2-optimize-ecs-query.md) | 已优化并回归 | Query 使用缓存实体视图，Contains 改二分，增加销毁后顺序回归。 | 评估最小组件池驱动交集查询的收益。 |
| [ms-9.3: 实现ECS系统批处理](../milestones/ms-9.3-ecs-system-batch.md) | 部分实现 | SystemBatch 包含 OOP 引用与调度包装，并非完全独立 ECS 批处理。 | 测批次局部性并计入同步成本。 |
| [ms-9.4: 性能测试验证](../milestones/ms-9.4-performance-test.md) | 验收失真 | perf_test.sh 主要计时语法检查，不能证明运行性能。 | 替换为固定输入 Release 基准和可比较基线。 |
| [ms-9.5: 功能完整性验证](../milestones/ms-9.5-functional-verify.md) | 验收失真 | verify_test.sh 的符号存在检查不是功能测试。 | 改为 CTest 行为断言与真实比赛恢复。 |
| [ms-10.1: Team系统ECS迁移](../milestones/ms-10.1-team-ecs-migration.md) | 部分实现 | TeamProcessSystemDirect 与旧 Team 并存，语法检查不能证明迁移完成。 | 对战术、控球和成员生命周期做差分测试。 |
| [ms-10.2: Referee系统ECS迁移](../milestones/ms-10.2-referee-ecs-migration.md) | 部分实现 | RefereeProcessSystemDirect 仍需旧 Referee 上下文。 | 以实际定位球、犯规、优势规则与结束状态验收。 |
| [ms-10.3: MentalImage系统ECS迁移](../milestones/ms-10.3-mentalimage-ecs-migration.md) | 部分实现 | MentalImageSyncSystemDirect 是同步入口，不代表独立数据计算。 | 明确更新时机并检查回滚后的缓存。 |
| [ms-10.4: 系统批处理优化](../milestones/ms-10.4-batch-optimize.md) | 部分优化 | 保留批处理模块，本轮修复其底层实体遍历与调度依赖。 | 根据实际 CPU profile 决定批次优化。 |
| [ms-10.5: 功能完整性验证](../milestones/ms-10.5-functional-verify.md) | 验收失真 | verify_phase10.sh 用 -fsyntax-only 和 grep 判定完整性。 | 用实际行为测试替代“符号存在即通过”。 |
| [ms-11.1: 分析剩余OOP包装层](../milestones/ms-11.1-analyze-oop-wrapper.md) | 文档需校正 | OOP 分析报告存在，源码仍保留旧对象创建与使用。 | 更新所有权、调用者和迁移阻塞依赖。 |
| [ms-11.2: 设计完全移除方案](../milestones/ms-11.2-design-removal-plan.md) | 方案未闭环 | 移除方案存在，序列化和动画生命周期仍依赖旧对象。 | 拆为可运行差分测试的小步迁移。 |
| [ms-11.3: 实现完全移除 OOP 包装层](../milestones/ms-11.3-remove-oop-wrapper.md) | 未完成声明目标 | “完全移除”与 Match/Team/Referee/Player 当前实现不符。 | 先补完整迁移验收，再删除兼容层。 |
| [ms-11.4: 性能测试验证](../milestones/ms-11.4-performance-test.md) | 证据不足 | 历史勾选缺少可复现性能基线，本轮测试不替代历史性能结论。 | 固定机器、工具链、种子、输入和测量窗口。 |
| [ms-11.5: 功能完整性验证](../milestones/ms-11.5-functional-verify.md) | 部分验证 | 本轮补真实引擎快照重放；完整多进程联网链仍需验收。 | 将模块、引擎重放和网络确定性分开记录。 |
| [ms-12.1: PBR 着色器实现](../milestones/ms-12.1-pbr-shader.md) | 部分接入 | PBR shader 被加载；GraphicsCamera 可通过环境变量进入 RenderViewPBR。 | 验证光源、材质通道和实际 GPU 输出。 |
| [ms-12.2: 材质系统升级](../milestones/ms-12.2-material-upgrade.md) | 部分实现 | 材质与加载路径有 metallic/roughness/ao。 | 以材质球验证参数进入 G-buffer 并改变画面。 |
| [ms-12.3: IBL 环境光](../milestones/ms-12.3-ibl.md) | 未完成集成 | IBL shader 存在，辐照/预滤波 cubemap 和 LUT 生成绑定没有闭环。 | 接入纹理生命周期，验证粗糙度与环境旋转。 |
| [ms-12.4: 集成测试](../milestones/ms-12.4-integration-test.md) | 未验收渲染 | C++ 编译不执行 GLSL，也不验证画面。 | 补 GL shader link、FBO 完整性及参考截图。 |
| [ms-13.1: HDR 渲染管线](../milestones/ms-13.1-hdr-pipeline.md) | 部分实现 | PBR 复用 accumBuffer，HDR 纹理格式与颜色空间仍需验证。 | 记录线性工作空间、FBO 格式和显示转换。 |
| [ms-13.2: 色调映射](../milestones/ms-13.2-tone-mapping.md) | 部分接入 | tonemapping shader 有多算子，PBR pass 调用了色调映射。 | 验证 gamma/sRGB 无重复转换及 HDR 梯度。 |
| [ms-13.3: 自动曝光](../milestones/ms-13.3-auto-exposure.md) | 未完成集成 | auto_exposure 加载并设默认值，但没有亮度归约与跨帧曝光更新链。 | 实现亮度统计、适应过程及明暗切换测试。 |
| [ms-14.1: 级联阴影贴图](../milestones/ms-14.1-csm.md) | 未完成集成 | CSM shader 存在，级联矩阵、深度数组绘制缺少实际链路验收。 | 实现分割、混合并验证移动镜头稳定性。 |
| [ms-14.2: 软阴影](../milestones/ms-14.2-soft-shadow.md) | 未验收 | PCF/VSM shader 不证明阴影资源与采样已生效。 | 分别测软化、漏光和精度，保存对照截图。 |
| [ms-15.1: Bloom 效果](../milestones/ms-15.1-bloom.md) | 未完成集成 | PBR 中 Bloom 明确 BindTexture(0)，默认强度为 0。 | 接亮部提取、双向模糊和合成纹理。 |
| [ms-15.2: SSR 屏幕空间反射](../milestones/ms-15.2-ssr.md) | 未完成集成 | SSR shader 被加载，PBR pass 未执行 SSR。 | 实现深度/法线输入、步进与边缘淡出。 |
| [ms-15.3: 运动模糊](../milestones/ms-15.3-motion-blur.md) | 未完成集成 | 运动模糊 shader 存在，速度纹理和后处理 pass 未闭环。 | 建立前后帧变换，覆盖回滚时的拖影。 |
| [ms-15.4: 抗锯齿](../milestones/ms-15.4-fxaa.md) | 未完成集成 | FXAA 被加载，当前 PBR 输出路径未调用该 pass。 | 在色调映射后接入，并比较边缘和文字。 |
| [ms-15.5: 集成测试](../milestones/ms-15.5-integration-test.md) | 未验收 | 没有完整后处理链 GPU 截图或运行测试证据。 | 分别验收单效果、组合和不同分辨率。 |
| [ms-16.1: 队伍/裁判插值](../milestones/ms-16.1-interpolation.md) | 部分修复 | 插值实现存在；修复客户端 alpha 与边界测试旧预期。 | 验证球员/裁判实际接入且不改写物理状态。 |
| [ms-16.2: 确定性 PRNG 模块](../milestones/ms-16.2-prng.md) | 部分修复 | PRNG 全 int 范围发生溢出/除零，已修复并补回归；引擎仍用 Boost RNG。 | 冻结既有序列，补跨编译器 golden vectors。 |
| [ms-16.3: 视觉外推](../milestones/ms-16.3-extrapolation.md) | 模块验证 | Interpolator 覆盖外推，真实球场边界与视觉纠正仍需联调。 | 测速度上限、位置钳制和远端跳变。 |
| [ms-16.4: 状态 Delta 压缩](../milestones/ms-16.4-state-delta.md) | 已修复编码缺陷 | 修复 0xFF 转义、全量 fallback、变长状态与截断/溢出拒绝。 | 测真实快照压缩率，编码调用方需同步升级。 |
| [ms-16.5: 预测准确率追踪](../milestones/ms-16.5-prediction-accuracy.md) | 已修复统计缺陷 | 原实现把服务端 hash 与自身比较；改为真实预测输入对权威输入的结果统计。 | 输入准确率与独立状态 hash 校验分开展示。 |
| [ms-16.6: 自适应预测上限](../milestones/ms-16.6-adaptive-predict.md) | 部分实现 | 自适应类有单测，接入准确率，但没有真实 RTT 测量链。 | 增加对应请求的回声时间戳，再启用 RTT 策略。 |
| [ms-16.7: 回放系统](../milestones/ms-16.7-replay.md) | 部分修复 | TCP 回放录制已确认整帧输入、真实 hash 和全局槽位数。 | 场景仍 unknown；压缩、seek 和完整播放链尚需接入。 |
| [ms-16.8: 自适应抖动缓冲](../milestones/ms-16.8-jitter-buffer.md) | 部分实现 | TCP 重新采集实际到达时间；抖动缓冲未控制播放延迟。 | 用扰动测缓冲深度、延迟和回滚率。 |
| [ms-16.9: 集成测试](../milestones/ms-16.9-integration-test.md) | 部分验证 | 模块集成测试可跑，默认正确性验收已分离 Debug 性能门槛。 | 补真实网络/GPU 联调，Release 单独测吞吐。 |
| [ms-17.1: 延迟补偿](../phases/phase17.md) | 未完成集成 | 删除心跳伪造的固定 50 ms RTT；单向时间戳不能推导往返延迟。 | 设计回声标识、环回时间戳和服务端输入调度。 |
| [ms-17.2: 状态快照压缩传输](../phases/phase17.md) | 已修复模块缺陷 | 快照变长回退、长度验证、失败不污染基线及统计已修复。 | 接实际关键帧/增量消息并测试关键帧丢失恢复。 |
| [ms-17.3: 观战模式](../milestones/ms-17.3.md) | 模块实现 | spectator 管理逻辑有测试；真实加入、只读权限与广播链仍需验收。 | 连接不发送输入的观众，验证不占用玩家槽位。 |
| [ms-17.4: 回放系统集成](../phases/phase17.md) | 部分修复 | TCP 回放接入与作用域已修正；播放界面、场景恢复和默认 UDP 接入未完整。 | 从录制重建 GameEnv 并逐帧比对 hash。 |
| [ms-17.5: 网络诊断工具](../phases/phase17.md) | 部分实现 | 诊断模块有测试，固定 RTT 假数据已移除。 | 缺失指标显示未知，补真实丢包分母与 overlay。 |
| [ms-18.1: 大厅协议与房间元数据](../phases/phase18.md) | 已修复定界 | StartGame 添加 uint16 地址长度，服务端验证端口，支持分片/粘包定界。 | 双方同时升级；RoomConfig/Metadata 的 sizeof 布局仍需跨平台协议治理。 |
| [ms-18.2: 房间管理器](../phases/phase18.md) | 部分修复 | 校验房间容量/名称/地址，阻止重复 StartGame。 | 补 Finished 回传、房间变更订阅及退出后的元数据同步。 |
| [ms-18.3: Lobby 服务器](../phases/phase18.md) | 已接入生产测试 | LobbyServer 纳入构建与测试；有界异步发送、断开清理、重名与聊天权限限制。 | 自动创建游戏进程与房间列表广播未闭环。 |
| [ms-18.4: 客户端大厅集成](../phases/phase18.md) | 部分修复 | 移除同步/异步争抢读取，修复分片聊天与 EOF，限制名字和聊天长度。 | 主客户端仍需接入大厅 UI 与 GameStarted 转接。 |
| [ms-18.5: 端到端测试](../phases/phase18.md) | 部分验证 | 实际 LobbyServer 测试覆盖创建、加入、聊天、准备、开局、重名和分片/EOF。 | 尚非多游戏进程与观战的完整 E2E。 |

## 代码与测试入口

- [共享预测回滚](../../engine/src/frame_sync/frame_simulation.hpp)、[统一场景](../../engine/src/frame_sync/default_scenario.hpp)、[整帧回归](../../engine/tests/frame_simulation_test.cpp)。
- [ECS/编码回归](../../engine/tests/milestone_regression_test.cpp)、[生产大厅 E2E](../../engine/tests/lobby_e2e_test.cpp)。
- [存档/匹配回归](../../gfootball/frame_sync/milestone_regression_test.py)、[外部服务测试适配](../../gfootball/frame_sync/legacy_network_test.py)。
- [CMake](../../engine/tests/CMakeLists.txt)、[CI](../../.github/workflows/ci.yml)、[无窗口比赛/快照重放](../../engine/src/frame_sync/headless_match.cpp)。

## 兼容性与限制

- StartGame 请求改为 `type + room_id + uint16 地址长度 + 地址`，大厅两端必须同时更新。
- StateDeltaCodec 全量 fallback 使用长度高位标记。旧的无标记全量格式本身不能可靠解码，调用方需同步升级；普通 delta 仍使用长度加 RLE/XOR。
- TCP 当前发送全量权威输入，增量模式须在两端实现并协商后启用。网络未来帧调度、重连恢复与慢客户端回压仍需进一步验证。
- 字体原链接为 `/home/zuchangqu/project/football/engine/fonts/AlegreyaSansSC-ExtraBold.ttf`，已修为指向仓库内字体的相对链接。
- 没有 GPU 画面验收、完整多房间多游戏进程 E2E 或跨平台确定性证明；RL 本轮只做源码审查。
- 索引存在部分 C++23 解析缺口，关键结论以直接源码和编译/测试为依据。文件或符号存在不代表功能通过。
- 保留历史状态，没有提交 Git；旧代码注释按仓库要求保留日期和原因。
