# 原生产品 50Hz 链路实现与验收 — 2026-09-13

原生单机、TCP、UDP入口已接入明确的50Hz比赛契约，回放能够自行描述物理节拍和球队配置。实际测试同时修复了三个影响输入生效的问题：追帧结束才发送导致错过封帧、TCP小包延迟、可靠UDP重复交付握手数据。

最终G轮完整通过，输入门禁 **2419961条断言、零跳过**，耗时291.994秒；整组执行约419.776秒。此前所有失败轮次均保留。本轮没有向正式质量状态写入成功记录，整体优化目标仍未完成。

对应的工程层级是 **ms-22.1 → plan-22.1.1 → task-22.1.1.1／task-22.1.1.2**；网络输入窗口与图像证据同时关联task-23.1.1.1和task-24.1.2.1。完整前置验收、设备响应和弱网质量尚未通过，任务不手动提升状态。

## 具体实现

- [协议与时钟](../../engine/src/frame_sync/native_match_contract.hpp)：FNAT1独立协议系列，Hello声明50Hz／2个10ms物理步，Session及Ready包含种子、球队和场景预算。权威输入在绝对20ms截止点封存，引擎工作之后不再额外等待100ms。
- [产品场景](../../engine/src/frame_sync/native_match_scenario.hpp)：原默认场景保持不变，新场景将3000帧预算换算为15000帧；[接管AI](../../engine/src/frame_sync/bot_takeover.hpp)保留3／4模拟秒冷却。
- [输入提前发布](../../engine/src/frame_sync/native_input_publication.hpp)：网络接收及设备采样后先绑定、发送有界未来帧，再进行昂贵的追帧与渲染；[历史读取](../../engine/src/frame_sync/local_input_history.hpp)不再次消费短按边沿。TCP产品两端启用TCP_NODELAY。
- [可靠UDP](../../engine/src/frame_sync/reliable_udp.hpp)：确认、重传之外增加顺序交付和去重，缓存及回调中的数据都计入接收配额。重复分段Ready不会再次进入应用解析器；回调可以发送、关闭或重入接收。
- [UDP服务端](../../engine/src/frame_sync/asio_server_engine.cpp)：只有匹配的Hello才能预留槽位，开赛前失败的预留可以回收；GameEnv与IO线程由明确的所有者管理，信号退出和异常路径执行停止及回收。
- [原生回放](../../engine/src/frame_sync/native_match_replay.hpp)：新增40字节封装，仍通过原有原子发布／目录配额机制分块写入。载入时校验节拍、场景、种子、球队与连续帧号，失败不替换已载入状态。

完整字节布局和兼容范围见[原生比赛协议文档](../../engine/src/frame_sync/NATIVE_MATCH_PROTOCOL.md)。旧原生接口保留默认10Hz；Python FMATCH7属于另一协议系列，不能直接与FNAT1互联。

## 本轮实际验证

| 验证范围 | 结果 |
| --- | --- |
| 完整共享输入门禁 | 2419961条断言，零跳过 |
| 原生比赛契约 | Release／ASan各134012条断言；10000次截止时刻、10000次发布历史对照、143种控制槽组合、600次真实引擎推进／重放 |
| 实际网络窗口回放 | 两种引擎各400940条断言，重放同一批234个确认帧，全部哈希一致 |
| 两个独立套接字 | 1575条断言；TCP／UDP各50个权威帧、10个非零输入帧、5个对应状态哈希 |
| 可靠UDP与回放文件／目录 | Debug／ASan各18＋10＋16项，共88项测试，零跳过 |
| 旧TCP重连与慢观战者 | Release2857／ASan4037条断言；各40个确认帧、8个哈希、87132字节恢复快照 |
| 真实SDL设备采样 | Release／ASan各56条断言，包含XTEST键盘、虚拟手柄、焦点与断连 |

三种产品窗口实际结果：

| 入口 | 比赛渲染次数 | 确认帧 | 非零输入帧 | 短按射门帧 |
| --- | --- | --- | --- | --- |
| 单机 | 39 | 不适用 | 本地输入验证 | 本地短按验证 |
| TCP | 37 | 108 | 8 | 1 |
| UDP | 43 | 126 | 11 | 1 |

每次比赛渲染恰好一次交换，渲染前后的逻辑摘要不变。TCP／UDP途中保存的93／108帧前缀保持一致；客户端和本轮服务端均退出0。已查看本轮第24次交换的实际图像：[单机](../optimization/benchmarks/native-product-cadence-20260913-g/gate/x11/windows/standalone/trace/frame-24.png)、[TCP](../optimization/benchmarks/native-product-cadence-20260913-g/gate/x11/windows/tcp/trace/frame-24.png)、[UDP](../optimization/benchmarks/native-product-cadence-20260913-g/gate/x11/windows/udp/trace/frame-24.png)。

这些图像和输入测试覆盖启动期比赛流程，不能据此声称进行中比赛的球员响应时延或持续移动手感已达标。两个套接字的49个权威帧间隔合计约0.976至0.978秒，是本轮回环观察，也不是设备延迟或弱网性能结论。

## 保留的失败证据

- A：新增测试的main签名与引擎声明冲突，修正后继续构建。
- B：本地追帧／预测有移动输入，实际TCP回放132帧全部中性。该结果促使输入发布移到引擎工作之前。
- C：错误Ready后，UDP槽位0仍被永久预留；真实新客户端因此不能取得该槽。
- D：移动进入权威回放，但短按射门仍丢失。
- E：TCP_NODELAY改动后的三个窗口和269帧Release重放通过；双客户端UDP因重复分段Ready失败。
- F：有界UDP顺序交付后，两个协议的双客户端测试、Debug的44项测试和旧TCP回归通过；继承的ASan构建目录尚未注册回放文件目标，构建失败。
- G：显式从当前测试源目录重新配置构建，使用已有本地GoogleTest依赖；全部检查通过，没有修改验收门槛。

各轮的原始代码快照、命令、日志、回放和退出记录位于[阶段目录](../optimization/benchmarks/native-product-cadence-20260913-g/)及相邻A至F目录。

## 证据入口与后续任务

- [完整输入报告](../optimization/benchmarks/native-product-cadence-20260913-g/gate/report.json)：SHA-256 `fc1e9cc106250a2361bcc65d7a18d3edf4dbc90b730aacc7d29c7fa2cdb90b44`。
- [双客户端协议报告](../optimization/benchmarks/native-product-cadence-20260913-g/protocol/report.json)：SHA-256 `9c0e9ddae6ee0cecaa941223dd4b12cb66df80ccb2da0d5f9718f16ed214c11c`。
- [整组执行报告](../optimization/benchmarks/native-product-cadence-20260913-g/report.json)：SHA-256 `6fab04877ce6ec914ff1a8eac2e83796d400597aab145656bce30e598a758a46`。
- [文件校验清单](../optimization/benchmarks/native-product-cadence-20260913-g/verification.json)与[独立校验输出](../optimization/benchmarks/native-product-cadence-20260913-g/verification.log)。

实际Release／ASan核心保持此前的`2836c626…`／`24cccb16…`身份；原始性能基准、默认场景和冻结AI／帧模拟对照未更改。新的产品主程序及网络头文件已改变，旧质量证据不能当作当前完整验收。

下一步继续沿里程碑任务线执行：补齐固定节拍正式入口及旧产品套接字检查器的协议适配，测量比赛进行中的设备至球员响应和慢渲染下持续输入，完成丢包／乱序／重连矩阵，再处理渲染性能与异常所有权，并刷新完整前置质量链。FNAT1当前不提供中途重连或观战恢复。
