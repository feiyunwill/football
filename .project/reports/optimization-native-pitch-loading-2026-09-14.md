# 2026-09-14 球场加载性能候选与初始化期限审查

本轮推进 ms-23 / plan-23.1.1 / task-23.1.1.2 的图形启动问题。完成球场纹理计算优化及实际引擎验证，但 ASan 原生客户端仍未成功入场；加载与握手阶段尚未拆分，network_reconnect 和产品级状态不提升。正式源码与 74 个登记产物保持原样，优化仍为私有候选。

实现位于 [proceduralpitch.cpp](../optimization/benchmarks/native-pitch-loading-optimization-20260914-b/proceduralpitch.cpp)。逐像素的配置查询移到纹理块循环外；割草条纹的三角函数按行、列缓存；双线性采样按通道保持原有浮点运算顺序，减少临时向量。像素遍历顺序、每像素视觉随机抽样次数和纹理分辨率保持一致。候选继承上一轮草皮使用视觉 RNG 的修复，参考原文件完整保留；本轮没有放宽网络期限。

初始 ASan 分段采样记录球场准备约 7.69 秒，漫反射纹理约 21.19 秒，法线纹理约 4.90 秒，其余主要为高光、上传。它是定位样本，不能代表所有加载阶段。见[原始分段日志](../optimization/benchmarks/native-pitch-loading-profile-20260914-a/sanitized-x11/diagnostic.log)。

| 验证 | 实际结果 |
| --- | --- |
| 独立旧源码像素 oracle | Release / ASan 各 137,082 条断言，合计 274,164；各覆盖 24,576 个行列样本、32,768 个法线像素、12,288 个漫反射像素 |
| GPU 基础纹理全量读取 | 每次读取 12 张纹理、18,874,368 个 RGB 像素；两个构建各按旧→新→新→旧执行，共 8 次 |
| 完整纹理表 SHA256 | 所有运行均为 cd9a8710609803918126ae1ef3c30995b034d6b432aa52d9f313cc117ea65c37 |
| 视觉 RNG 序列 | 所有运行的引擎状态摘要均为 f7ac6aaa28734d78cbcedfd8fe1de1655dee930cfc916ffb8244277c349dc57e |
| 比赛状态 | 图形 / headless 初始哈希 1086847095508428874；首帧哈希 12693704928474537033；均与原 headless 状态一致 |
| 完整 ASan 原生客户端 | 实际 G 客户端、候选核心、正式 ASan 服务端；客户端退出 1，confirmed=0，服务端退出 0；映射已核对，仍报 reconnection deadline exceeded |

| 本机实际图形初始化 | 旧版本两次范围（秒） | 新版本两次范围（秒） | 旧 / 新中位数（秒） |
| --- | --- | --- | --- |
| Release | 6.750–13.537 | 3.351–3.393 | 10.144 / 3.372 |
| Debug + ASan / UBSan | 77.561–80.327 | 59.264–61.615 | 78.944 / 60.440 |

时间来自私有 X11 与 llvmpipe 环境下的实际 GameEnv::start_game，测试顺序交替，未清空系统缓存。每个版本每种构建只有两次样本，Release 基线存在明显波动；这些数据支持继续采用该候选验证，不构成稳定性能、硬件 GPU 或 50ms 输入延迟验收。GPU 对比覆盖基础纹理，未单独比对各级 mipmap。

[像素与初始状态结果](../optimization/benchmarks/native-pitch-loading-optimization-20260914-b/results.json)、[完整图形对比](../optimization/benchmarks/native-pitch-loading-comparison-20260914-a/report.json)、[真实客户端失败证据](../optimization/benchmarks/native-pitch-loading-client-window-20260914-a/x11/product/report.json)、[实际加载核心映射](../optimization/benchmarks/native-pitch-loading-client-window-20260914-a/x11/product/engine-mappings.json)。

真实客户端本轮运行 58.935 秒后报告原有连接期限已耗尽。ASan / UBSan / LSan 未报告错误，但启动功能失败。失败作为失败保留，未转换为通过结果。首次像素 oracle 编译曾因 main 签名与引擎声明冲突退出 1；B 阶段修正后两种构建通过。A 阶段启动器在 Popen 后缺失 json 导入，退出前未观察到包装器 PID/start；编译命令和包装器退出报告保留，此身份缺口明确记录，不虚构 PID。详见 [A 阶段记录](../optimization/benchmarks/native-pitch-loading-optimization-20260914-a/launch-observation.json)。

接下来的实现顺序：

1. 拆分运行时 / SDL 窗口初始化与比赛资源加载，使窗口创建线程持续处理事件，比赛和 GL 仍由同一工作线程持有；旧 start_game 接口保持完整生命周期。
2. 为初次加载定义独立阶段，同时保持多人开局屏障、同一场比赛的绑定及席位所有权。仅把加载移到一个无预留的配置查询之后，会让先加载完的玩家提前开赛，因此这条简化方案尚未采用。不能通过直接增大全局 Ready / 重连期限解决。
3. 为取消和初始化异常设置资源持有者负责的安全退出边界，并验证退出时没有泄漏；随后在真实慢加载、混合快慢客户端、断线和服务端重启中检查开局时序。
4. 加载问题通过后，合并候选客户端与核心改动，完成正式七个入口的串行构建及完整网络 / 输入 / 回放回归，再继续 UDP 恢复和完整弱网矩阵。

历史 UDP 第 200 / 201 帧缺口、旧 ASan legacy 首次失败原因、UDP 同局恢复、完整弱网和硬件延迟验收仍未解决。质量状态继续由 quality.py 计算。

本轮封存清单生成于 `.project/optimization/benchmarks/native-pitch-loading-evidence-20260914-a/verification.json`。
