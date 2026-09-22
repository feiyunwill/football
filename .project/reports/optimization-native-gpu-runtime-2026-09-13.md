# 实际 GPU 运行、驱动修复与 RGB 回读优化实验（2026-09-13）

本轮完成私有 Mesa 26.2.2 两文件修复验证，以及未修改产品程序的 GPU 窗口和取帧对照。产品验收仍未通过；源码、基线、阈值与系统驱动保持不变。

## ms-24.1 → plan-24.1.1 → task-24.1.1.1：驱动启动可靠性

同配置原始 Mesa（D3D12 + softpipe 提供 EGL 设备枚举）复现 90 秒死锁。真实堆栈为纹理上传 → slab 管理器分配 → d3d12_bo_new → reclaim_completed → pb_slab_buffer_destroy → 同锁再次加锁。私有修复将已完成资源回收及分配失败重试移到管理器锁外。

[修复验证](../optimization/benchmarks/native-mesa-patch-validation-20260913-c/report.json)通过三轮各 5,000 次纹理操作和六次实际 1080p GameEnv 启动：966 逻辑帧、360 次渲染、240 个计时样本。30 组 RGB 与原驱动成功样本逐字节一致，五个检查状态也一致。源码前后清单确认仅预定两文件变化。尚未做真实 OOM 注入、广泛驱动压力认证或正式运行时打包。私有 child 环境成功不代表用户入口已经自动使用该驱动。

原始复现和修复之间的脚本参数错误完整保留：[失败记录](../optimization/benchmarks/native-mesa-patch-validation-20260913-b/execution/commands.json)。candidate-configure 的 environment 被错误传入整数，进程未启动（returncode:null）；修正为关键字参数后在新阶段恢复，未伪装为一次成功执行。X11 探针生成时的缩进匹配错误也保留在 preflight.json。

## ms-22.1 / ms-23.1：真实窗口、输入与权威回放

[GPU 窗口结果](../optimization/benchmarks/native-patched-gpu-windows-20260913-a/report.json)使用实际 standalone/TCP/UDP 程序、私有 X11 与真实 XTEST 输入，GL 明确为 Intel Arc 140T / D3D12 / Mesa 26.2.2。聚焦、松键、暂停恢复、再次按键、保存与逻辑状态检查通过。分辨率 1280×720；私有 Xvfb 路径不是物理显示延迟验收。

| 模式 | 持续按键中性帧 | 单次观察输入完成 ms | 渲染 p95 ms |
|---|---:|---:|---:|
| 单机 | 0 / 69 | 16.793 | 41.044 |
| TCP | 0 / 70 | 41.139 | 33.545 |
| UDP | 0 / 72（权威 0 / 70） | 61.243 | 34.672 |

[实际权威回放](../optimization/benchmarks/native-patched-gpu-windows-20260913-a/replay-report.json)共 1,029 帧，Release 与 ASan/UBSan/LeakSanitizer 各通过 452,553 断言、40,000 时钟事件、零跳过。这只验收该次保存的真实输入序列。

另一次 [GL 分段计时](../optimization/benchmarks/native-patched-gpu-gl-profile-20260913-a/cpu-profile-analysis.json)运行在 TCP 持续按键中央出现真实权威第 203 帧中性输入；最终回放字节独立解码确认，见 [失败证据](../optimization/benchmarks/native-patched-gpu-gl-profile-20260913-a/held-input-failure.json)。该轮失败、UDP 未运行，不能用先前成功轮次覆盖。缺少同步发布/收包证据，尚不归因于 GPU、计时开销或网络。

## ms-24.1 → plan-24.1.2 → task-24.1.2.1 / task-24.1.2.2：回读开销

实际 glReadPixels CPU 时间包括先前排队的 GPU 工作。分段计时显示它占据大量等待，不能将全部时长归为数据拷贝。随后使用同一个观察器进行单机 ABBA 对照，仅在实验分支省略产品缓存 RGB 回读；GL 呈现与服务轮询保留。四轮功能检查均通过，实际产品每渲染回读次数在基线为 1、实验为 0。

| 顺序 | 渲染平均 ms | 渲染 p95 ms | 回读平均 ms | 交换平均 ms |
|---|---:|---:|---:|---:|
| 原始 A | 19.705 | 38.569 | 12.263 | 4.286 |
| 实验 A | 14.602 | 27.504 | 0 | 11.706 |
| 实验 B | 14.987 | 24.542 | 0 | 12.214 |
| 原始 B | 18.966 | 43.744 | 12.084 | 4.341 |

[ABBA 原始分析](../optimization/benchmarks/native-gpu-readback-prototype-20260913-a/abba-analysis.json)表明等待部分转移到 SDL 交换，平均仍改善约 4–5 ms。两轮实验 p95 均未达到 16.67 ms。实验通过 LD_PRELOAD 替换交换函数，刻意不更新缓存 RGB；它不是可交付实现，不能用于承诺 Python get_frame 兼容。

下一任务实现默认保持捕获的显式策略，原生显示入口关闭未消费的 CPU 图像；以真实渲染验证默认像素、禁用取帧语义、重新启用、逻辑/回放不变。之后重新跑原生窗口和输入检查，再继续 1080p 帧时间、50ms 响应、弱网和 AI 验收。所有失败、运行时身份与命令日志进入本轮证据清单；不手动提升任何里程碑状态。
