# task-20.1.1.2 — 环境生命周期隔离

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 重复创建/销毁及独立环境无悬空引用、静态状态串扰和资源泄漏

依赖：task-20.1.1.1

执行顺序：无

验收检查：environment_lifetime

执行：`python3 .project/quality.py run task-20.1.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-10: Gymnasium、真实安装包和当前回归已完成，保留上一轮记录。
2026-09-10 实施记录：[真实 GameEnv 与引擎池验收](../reports/optimization-native-recovery-progress-2026-09-10.md)。174 项录制与资源回归通过，包含 28 项此前待执行的环境／原生／渲染检查；收尾时 live/leased/idle 均为 0。继续 tracker 嵌套计数、HUD surface 异常释放及长期原生资源检测，environment_lifetime 正式证据仍需刷新。
-->

<!-- 2026-09-10: 正式框架/架构依赖链与 d 包证据已刷新，保留上一轮记录。
2026-09-10 当前实施记录：[Gymnasium 与真实安装包报告](../reports/optimization-gymnasium-package-progress-2026-09-10.md)。新增工厂包装失败释放、Gymnasium 异常终止和种子隔离；最终已安装包 15 项原生接口测试含双环境、失败清理与旧工厂快照，当前录制/引擎池 174 项通过，最终池计数归零。合法 headless 空闲缓存按有界所有权验证。tracker 嵌套计数、HUD surface 异常及长期资源检测仍待完成，environment_lifetime 正式证据需刷新。
-->

2026-09-10 当前正式验收：修复无效原生 reset 提前修改帧号/tracker 和清除展示姿态；新增 34 条不变量，生命周期门禁由 390 提高至 424 条并通过普通构建及 LSan。全引擎 ASan/UBSan 也通过相关测试，详见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。HUD caption 任意分配失败路径及长期资源预算仍属于后续工作，不能用本轮周期替代长时验收。
