# plan-20.1.2 — 模块契约

2026-09-24 提交时状态：正式 loading_regression.py 已接入 TCP/UDP 的 transport 字段校验及两种传输各 5 个取消场景，保留 250 毫秒上限并拒绝负值。新增 loading_acceptance_test.py 的 13 项永久回归通过；native_boundary 通过。正式框架检查为失败（711 项 C++ 通过；Python 780 项及 305 子测试通过，3 项图形测试因未提供 DISPLAY、无法获得 SDL 窗口而失败）；正式架构检查仍在运行，不能标为整体通过。以下较早记录保留为历史。

2026-09-24：加载门禁候选已完成全部私有验收：14 项反例、完整 Debug 架构 1,632,099 条断言及 Release 加载 32 个结果通过；172 个完整 Debug 编译单元与日志哈希已核验。正式接入和正式门禁尚待当前多席位串行链结束后执行。见[完整证据与边界](../reports/optimization-loading-transport-gate-2026-09-24.md)。

2026-09-24：架构门禁候选的 14 项验收器反例及完整 Debug TCP/UDP 各 5 个实际取消场景已通过，完整架构仍在执行，正式状态仍为失败。见[最新证据](../reports/optimization-loading-transport-gate-2026-09-24.md)。

2026-09-24 当前架构门禁失败：共享 TCP/UDP 取消契约的结果字段与门禁不一致。私有修复已排队，保留全部旧覆盖并新增 UDP 的 5 个真实取消场景，尚未接入。见[失败与候选验收](../reports/optimization-loading-transport-gate-2026-09-24.md)。历史通过不能替代当前验收。

类型：plan

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 子任务通过且本计划验收证据适用于当前源码

依赖：无

执行顺序：task-20.1.2.1、task-20.1.2.2

验收检查：simulation_contract、architecture_regression

执行：`python3 .project/quality.py run plan-20.1.2`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。
