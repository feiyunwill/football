# task-21.1.2.1：Python 引擎池进展（2026-09-10）

状态：实施进展；memory_budget.ready 仍为 false，任务、计划和 ms21 未完成，整个优化目标继续 ACTIVE。

已修复的具体问题：

- 全局 _unused_engines 随环境数量无限增长，渲染名额由未加锁布尔值表示。现在采用共享有界池：默认 32 个总名额、2 个空闲无渲染引擎、1 个空闲渲染引擎，名额覆盖创建与关闭期间。
- 池复用忽略原生图形资源初始化尺寸。现在匹配尺寸、启动环境与 Thread 对象，淘汰时调用原生 close；物理步长在 NewScenario 后重新设置，保留同尺寸改变回放步长的复用能力。
- 旧 render 在取得渲染名额之前释放原引擎。现在候选渲染器完成快照恢复、绘制和观察生成后再提交；失败恢复原所有权和观察/统计/录制对象。
- 构造失败、失败状态和 GC 不再进入缓存。公开 Core 操作与 close 序列化，进程检查在加锁前执行，关闭同时释放观察引用。

实现：[engine_pool.py](../../gfootball/engine_pool.py)、[Core](../../gfootball/env/football_env_core.py)。使用说明与限制：[engine_pool.md](../../gfootball/doc/engine_pool.md)。原生源码确认 graphicsSystem/Scene2D 使用启动尺寸，GameEnv 提供 noexcept close，Python 绑定暴露该 close；这属于源码证据，未执行新原生验收。

当前独立归档：`.project/optimization/benchmarks/python-engine-pool-windows-20260910-b/`。

- 129/129 Windows 检查通过：21 个资源池用例 + 108 个录制、真实文件/NumPy/MJPG、跨进程目录配额及流式回放回归。
- 真实线程覆盖 32 个并发借用、容量过载、创建途中关闭、关闭期间保留名额、渲染互斥、并发归还只关闭一次。1000 个不同配置迭代保留数量稳定，清空后全部 oracle 弱引用释放。
- 无跳过、错误、失败、遗留工作线程、子进程或目录锁描述符；未出现 ResourceWarning 或异步/析构错误。
- 27 个源文件指纹和日志已核对；Core 公开类/构造签名/重复方法检查通过，2 个生产文件通过 Python 3.9 AST 语法检查。实际执行是 Windows Python 3.14.6，NumPy 2.5.1，OpenCV 5.0.0。
- report SHA256：`bf46c8caf4955a1f10b44f7e62e46619df99e09bb3dde12cc6e5154c2f2b0f8a`。
- tests.log SHA256：`c68aaecf1947cbdc7b63497e289985c1324d5199a4b2eeab28a1e7898af2d607`。

归档 a 的 128 个非原生测试通过后，源码复查发现本轮替换误将 Core 类边界注释掉并留下重复构造器。语法编译未能检测此入口损坏；已恢复 EnvState/Core 类边界，加入公开 API 的 AST 检查，并在 b 重新运行全部 129 项。a 保留为历史，已过期，不作为当前入口验收。全过程均未把通用资源测试计为 GameEnv 执行。

之前 TCP 恢复 201 项（python-reconnect-windows-20260910-d）的 36 个源文件、比赛帧回放 64 项（frame-replay-windows-20260910-b）的 39 个源文件与各自日志仍匹配，本轮未重复运行。之前环境回放 108 项的 Core/runner 指纹已过期；其全部用例已由当前 129 项重新执行。聚合证据为 `python-engine-pool-evidence-20260910.json`，不可把重跑数相加为独立覆盖数。

新增 `test_engine_pool_native.py` 含 6 个真实 Core/native 用例和 4 个 SDL/OpenGL 用例，均未执行。加上之前 13 个环境入口与 2 个 GameEnv 回放用例，当前还有 25 个计划中的环境/原生/渲染检查不能计为通过。WSL 启动问题本轮没有新的可检验假设，未重复执行同样的超时探测；未重置系统服务或发行版。

剩余：真实 GameEnv/图形线程与渲染回退、实际 RSS/显存和长期增长、POSIX 目录行为、原生 UDP 去重/排序与恢复协议、通用保存预算、比赛回放接入实际录制/UI。池限制只覆盖 FootballEnvCore 管理的引擎数量，不能证明全部应用内存或直接创建的原生引擎受限。全局 memory_budget、后续性能增长以及手感/网络/渲染/AI/发布里程碑仍待完成。未修改 C++、运行构建、执行 Git 或改动固定基线指针。
