# 加载重试缓存回滚与场景注册 — 2026-09-15

本轮沿里程碑 23 → plan-23.1.1 → task-23.1.1.2 推进。私有候选修复加载取消后视觉缓存与随机状态不一致，以及重复开局再次注册球门节点。Release / ASan 六个实际图形重试、十个新旧核心场景对照均通过；尚未正式接入，整体产品质量仍未完成。

## 实现与失败对照

reset 失败原先只恢复 RNG，却保留本次生成的草皮标志和已随机化广告的球场缓存。重试因此跳过原本应有的随机取样。旧核心四次实际 GPU 重试均出现视觉 RNG 差异，其中两次部分草皮取消还出现像素差异；比赛初始哈希不变。旧报告的 passed 只表示诊断执行结束，retry_contract_passed 明确为 false。

候选记录 reset 前缓存状态，回滚只释放本次新建的球场及球门，恢复草皮标志后再恢复两套 RNG；原有缓存继续保留。RandomizeAdboards 会改变材质标识，重试保留失败缓存会跳过视觉 RNG 消耗。太阳参数使用比赛 RNG，不能归因于视觉 RNG。

球门节点原已附着于场景，但每次 Match 构造又执行 AddNode。修复将注册放入首次创建分支。旧核心第二次开局出现 96 个几何条目、95 个独立对象；候选正常重复开局及取消后重试均为 95/95。没有据此宣称帧率提升。

代码：[缓存回滚](../optimization/benchmarks/native-loading-retry-20260915-b/game_env.cpp)、[场景注册](../optimization/benchmarks/native-loading-retry-20260915-b/match.cpp)。候选继承前轮生命周期、Tracker 和分段加载取消实现，公共接口及字段布局没有新增变化。

## 验证

- 两种构建分别在 pitch.diffuse、match.pitch、match.finalized 取消后重试。六个用例均核对完整 12 张纹理、18,874,368 像素、视觉 RNG、初始比赛哈希及新建缓存回滚。
- 十个场景覆盖每种构建的旧核心冷启动、旧核心重复开局、候选冷启动、候选重复开局及候选重复开局中取消后重试。广告材质、草皮纹理、对应正常路径的视觉 RNG、初始哈希和连续 20 帧状态摘要一致。
- 冷启动和重复开局原本有不同的视觉 RNG 终态；本次分别对照正常路径，没有强制统一。
- 原有生命周期、双线程 Tracker 及四个无渲染取消边界在两种构建中通过，取消边界共 144 条断言。
- Release 三个取消加重试采样为 5.523 / 6.254 / 17.197 秒；ASan 为 128.252 / 185.393 / 164.555 秒。每项只有一次采样，包含中断前加载和完整重试，不证明普通加载时长、p95 或 250ms 退出指标。320s / 350s 是诊断观察上限，产品期限未改。

证据：[旧实现失败](../optimization/benchmarks/native-loading-retry-contract-20260914-b/report.json)、[候选边界检查](../optimization/benchmarks/native-loading-retry-20260915-b/report.json)、[六次图形重试](../optimization/benchmarks/native-loading-retry-validation-20260915-a/report.json)、[十次场景对照](../optimization/benchmarks/native-loading-retry-scene-20260915-a/report.json)。

## 构建与证据限制

临时目录输入不再存在后，85 项输入按原摘要恢复，另 19 项重建结果逐字节相同；当前 74 个正式产物及 1073 项源码仍与原摘要一致。112 项可用输入已保存到持久目录。首次错误链接、首次缺少编译数据库和恢复扫描断开链接的失败均保留原目录及日志。

五份受保护基线中，四份源码/夹具可用且摘要一致；一份旧性能核心仍缺失，没有用当前或私有核心替换。历史链另外七项缺失文件已精确恢复。旧基线源码尚有 77 项缺少精确副本，不能声称可重建基线或性能门禁通过。

上一轮收集和独立验证均退出 0，验证 580 个当前文件、11762 条历史文件记录、9 个执行进程和 164 条命令。证据记录明确为 available_evidence_verified=true、evidence_verified=false、historical_chain_fully_available=false、product_acceptance=false；收集完成不等于整体验收通过。旧的两项未知子进程退出仍保留。

相关档案：[精确重建](../optimization/benchmarks/native-build-recovery-20260915-c/report.json)、[持久输入](../optimization/benchmarks/native-build-state-20260915-a/archives.json)、[上轮证据](../optimization/benchmarks/native-loading-retry-evidence-20260915-a/verification.json)。

图谱采用 Verify 层；新增私有路径覆盖不足的部分已直接读取源码，不作完整覆盖声明。

## 后续任务

继续实现带当前凭证与代际验证的加载取消和及时席位释放，定位 ASan 退出超过 250ms 及慢启动；正式接入已验证的加载和客户端恢复链。随后完成原生 UDP 恢复、完整弱网矩阵、旧 UDP 第 200/201 帧缺口、50ms p95、硬件与其他 AI 产品验收，并恢复旧性能基线。

2026-09-15 文档编码修复：本文件上一版通过命令管道写入时中文变成问号。旧版摘要档案已保留；现在通过 UTF-8 编码传输恢复可读文档。上轮运行数据未改，本次不提升质量状态。
