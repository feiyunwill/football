# task-26.1.2.1 — 可安装产物

类型：task

状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。

验收条件：

- 干净目录启动、资源定位和错误诊断；版本/协议/构建信息写入报告

依赖：task-26.1.1.2

执行顺序：无

验收检查：product_package

执行：`python3 .project/quality.py run task-26.1.2.1`

实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。

<!-- 2026-09-10: 正式框架/架构依赖链与 d 包证据已刷新，保留上一轮记录。
2026-09-10 实施记录：[Gymnasium 与真实安装包报告](../reports/optimization-gymnasium-package-progress-2026-09-10.md)。实际从 sdist 构建必需原生扩展，最终 wheel 在全新虚拟环境安装全部声明依赖，源码目录外的 15 项原生接口、29 条注册、8 条加载顺序和 4 条 SDL 断言均通过；随包资源和字体定位无需覆盖路径。仅接受本机 Linux CPython 3.14 安装；editable、支持版本矩阵、完整诊断/版本/协议/构建报告及上游里程碑尚未全部验收，product_package.ready=false。
-->

2026-09-10 当前实施记录：[框架、生命周期与当前安装包报告](../reports/optimization-framework-lifecycle-progress-2026-09-10.md)。包含原生 reset 修复的 d wheel 从当前 sdist 单并发 C++23 编译，在磁盘上的全新环境安装，15 项原生 API、29 条注册、8 条加载顺序、4 条 SDL 断言通过；已安装库另有 60 条无窗口和 9 条 EGL reset 断言通过。仅接受当前 Linux CPython 3.14 产物；editable、支持版本/发布矩阵及后续里程碑尚未完成，product_package.ready=false。
