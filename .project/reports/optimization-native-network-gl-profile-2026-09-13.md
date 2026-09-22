# 原生网络接收与 GL 阻塞定位：诊断及原型结果

2026-09-13。本轮完成真实接收、GL 调用、着色器入口与 GPU 时间戳观测；保留一次 UDP 持续输入失败，并评估两个渲染原型。产品源码、资源、Release／ASan 二进制和既有验收阈值均未修改。没有新实现进入产品，也不提升任何里程碑状态。

## 里程碑 → 计划 → 任务

| 里程碑 | 计划 | 任务 | 本轮结果与下一步 |
| --- | --- | --- | --- |
| ms-23.1 网络 | plan-23.1.1 | task-23.1.1.1 权威输入窗口 | 捕获迟到的真实 UDP 输入；接下来补充解析／接纳时刻与网络故障矩阵，再选择迟到处理策略 |
| ms-24.1 渲染 | plan-24.1.2 | task-24.1.2.2 渲染性能验收 | 区分 CPU 绘制入口等待和 GPU 通道耗时；全屏分段原型不采用，SSAO 展开版本的收益尚未证明 |
| ms-22.1 手感 | 现有输入计划 | 实际设备响应验收 | 50ms 目标仍未达标；不能用采样机会间隔、发送完成或下一次呈现代替实际玩家响应 |

## 真实网络接收

[完整三入口执行](../optimization/benchmarks/native-network-gl-observe-20260913-a/x11/windows/report.json)中，standalone 与 TCP 通过原有严格条件，UDP 因持续持有区间出现空档而失败；[驱动退出记录](../optimization/benchmarks/native-network-gl-observe-20260913-a/exit.json)明确保留 exit 1。未重写失败结果，也没有放宽窗口或跳过 UDP。

[独立解码与对应关系](../optimization/benchmarks/native-network-gl-observe-20260913-a/transport-gl-analysis.json)：

- TCP 捕获 521 个不同输入帧的发送及接收；中央持有区间 70 帧无空档。这仅描述本轮样本。
- UDP 捕获 522 个不同输入帧的发送及接收；中央持有区间 69 帧中，第 203 帧为中性输入。
- 第 203 帧客户端发送完成在权威 Step 开始前 31.143739ms；服务器实际 recvfrom 完成在 Step 开始后 19.489815ms，两者相隔 50.633554ms。发送和接收的完整应用字节一致，可靠数据报序号为 223。
- 捕获中该数据报只有一次发送和一次接收；不能据此宣称重传、内核丢包或物理网络延迟。接收函数返回也不是解析或接纳完成，后两段仍须补证。
- 先前 latency-trace B 中的 TCP 第 197／198 帧异常没有被本次 UDP 样本解释，仍保留为未解决问题。

观测器调用原函数并保留返回值、数据和 errno，过滤本地 UNIX 套接字；按 TCP 流重组和 UDP 序号去重后解码。新窗口记录没有额外执行全引擎回放，因此不把此前 1030 个确认帧的重放结果算作本次网络样本的验证。

## GL 调用与 GPU 工作

[按着色器分类的真实窗口](../optimization/benchmarks/native-gl-shader-observe-20260913-a/report.json)在 1280×720 下完成 148 次比赛渲染。CPU 侧 glDrawArrays 平均累计：ambient 9.853ms／帧，postprocess 34.438ms／帧；postprocess 单次最长 72.133ms。这些入口时间包含驱动等待，不能直接称为着色器执行时间。

随后使用自有查询对象，在实际 GL 绘制前后记录 GPU 时间戳，在同一有效 SDL 上下文、完成呈现后读取并销毁查询。[有效 GPU 运行](../optimization/benchmarks/native-gl-gpu-query-20260913-b/report.json)完成 74 次渲染、148 个正耗时查询，读取时均已可用。实际渲染器是 llvmpipe（LLVM 22.1.8，256 bits），OpenGL 4.6 / Mesa 26.2.2-arch1.1；不是硬件 GPU 的性能验收。

| 通道 | 当前查询实验的平均 GPU 区间 | 最大区间 |
| --- | ---: | ---: |
| ambient／SSAO | 58.240ms | 107.566ms |
| postprocess | 9.115ms | 27.745ms |

查询实验使平均整帧耗时由无查询样本的约 58.5ms 增至约 110.8ms，存在明显测量扰动，不能把这些数字用作原始吞吐或 1080p／16.67ms 预算证明。它支持继续检查 ambient／SSAO，避免仅根据 CPU 入口耗时误改后处理通道。[原始事件、查询和汇总](../optimization/benchmarks/native-network-gl-observe-20260913-a/diagnostic-summary.json)保留全部范围。

第一版 GPU 观测在 GameEnv 退出上下文后读取，得到 null 渲染器及零耗时；虽然窗口本身通过，[该版 GPU 证据被明确判为无效](../optimization/benchmarks/native-gl-gpu-query-20260913-a/gpu-invalid.json)。修正后的版本在 SDL 呈现函数内读取，并强制验证上下文和正耗时。不能引用无效版零值。

已查看[实际第 40 次呈现](../optimization/benchmarks/native-gl-gpu-query-20260913-b/x11/windows/standalone/trace/frame-40.png)，包含球场、运动员、比分 HUD 与小地图。它是运行图像证据，不能代替跨设备画质验收。

## 两个原型的取舍

1. **全屏按 32 行分段绘制**：[原型执行](../optimization/benchmarks/native-gl-tile-prototype-20260913-a/report.json)通过逻辑状态不变和原有输入条件。全流程采样最大间隔从对照样本的 72.527ms 变为 99.745ms；持有区间最大间隔分别为 50.394ms、44.793ms。两次运行未配对，不能认定普遍改善或下降；它没有证明能够控制最坏阻塞，因此不采用，也没有进入像素等价验收。
2. **展开固定 32 个 SSAO 采样**：保留原表达式与逐项累加顺序，用独立数据目录运行当前真实引擎。按 baseline → candidate → candidate → baseline 顺序，[四次执行及比较](../optimization/benchmarks/native-ssao-unroll-prototype-20260913-b/comparison.json)完成 644 个引擎帧、240 次实际渲染；每次 62 帧处于比赛中，排除每状态 4 次预热后计时 160 次渲染。5 个状态的三组对照共 15 次完整逻辑状态比较、41472000 字节 RGB 比较全部相同。平均整帧耗时依次为 52.173／52.503／49.600／71.588ms，对照自身波动明显；目前不足以证明稳定收益，仍作为未采用原型。

SSAO 初始夹具调用了尚未捕获姿态的插值渲染，真实引擎明确拒绝；[原失败](../optimization/benchmarks/native-ssao-unroll-prototype-20260913-a/exit.json)保留。后续夹具改为固定状态的普通端点渲染，没有修改产品的姿态前置条件。预检查曾在错误头文件查找 GameConfig 字段，图索引定位到 main.hpp 后、编译前纠正，记录在该原型目录。

## 后续执行顺序与边界

1. 网络：记录入站解析与权威接纳／封帧时刻，重现 TCP 旧异常；在延迟、抖动、丢失和线程停顿条件下验证，再决定输入提前量或有界补偿。禁止仅为 localhost 样本缩小提前量。
2. 渲染：基于固定真实状态，评估 SSAO 内循环计算与采样成本；候选必须先有像素／逻辑证据，再以稳定成对实验确认收益。若驱动提交等待仍阻塞 UI，转向明确的渲染所有权与输入时间线架构。
3. 最终仍需真实设备到玩家／呈现的响应、完整弱网、重连／旁观／权威暂停、当前源码的完整质量链与长时间运行验收。软件渲染诊断不替代硬件预算验收。

完整质量状态仍由检查器计算。源文件、二进制和依赖已在实验前后按 SHA-256 核验；所有进程均按驱动实际终态收尾。失败、无效测量与未采用候选也计入[独立证据清单](../optimization/benchmarks/native-network-gl-observe-20260913-a/verification.json)，清单完整性通过不代表产品验收通过。
