# task-19.1.2.1 — 分离引擎与 Python 绑定

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 原生服务端、客户端、headless 不链接 Python 或绑定模块；Python 扩展保留兼容入口

依赖：task-19.1.1.2

执行顺序：无

验收检查：native_boundary

执行：`python3 .project/quality.py run task-19.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-10: Gymnasium、真实安装包和当前回归已完成，保留上一轮记录。
2026-09-10 实施记录：[原生绑定与运行恢复](../reports/optimization-native-recovery-progress-2026-09-10.md)。修复场景容器复制、原生启动占用 GIL 与可选依赖提前导入；真实比赛、恢复、录制及图形检查已执行。包依赖和公开 Gym 入口兼容仍待解决，native_boundary 的正式证据需按当前源码重跑。
-->

<!-- 2026-09-10: 正式框架/架构依赖链与 d 包证据已刷新，保留上一轮记录。
2026-09-10 当前实施记录：[Gymnasium 与真实安装包报告](../reports/optimization-gymnasium-package-progress-2026-09-10.md)。必需的 Python 扩展从 sdist 真实编译，包内相对导入与旧模块别名保持同一实例，修复重复注册 FloatVec。Gymnasium 及旧四返回值工厂均在最终安装包验证；质量状态机 42 项自测已刷新，下一项正式任务为本任务，native_boundary 仍需按当前源码执行。
-->

2026-09-10 当前正式验收：原生边界门禁通过，7 个原生程序与核心库无 Python 链接依赖；实际重定位当前包加载器，并验证进程映射的核心库路径。已替换退役打包函数的 AST 探针，保留旧代码注释；详见[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。
