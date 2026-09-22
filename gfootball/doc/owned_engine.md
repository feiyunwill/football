# 比赛引擎的容量与所有权

2026-09-10。`server_runtime.native_engine()` 和 `match_identity.native_match_engine()` 使用与 `FootballEnvCore` 相同的 `gfootball.engine_pool.ENGINE_POOL`。通过这些默认工厂创建的权威比赛、玩家副本和独立回放共同占用最多 32 个实例名额。创建中、使用中、关闭中和池内空闲实例均计数；容量不足时在调用工厂前抛出 `EngineCapacityError`。

比赛通过 `create_owned_engine()` 调用 `EnginePool.acquire(..., reuse=False)`。即使存在配置相同的空闲 Core 引擎，也先关闭旧实例再创建新的比赛实例。比赛关闭时调用 `lease.release(reusable=False)`，不会进入训练环境的空闲缓存。[Core 复用规则](engine_pool.md)继续适用于 Core。

## 调用与释放

返回的 `OwnedEngine` 转发实际引擎的属性和方法，不改变公开的 `gfootball_engine.GameEnv` 绑定类。操作和显式关闭属于创建它的 Thread 对象及进程；跨线程、跨进程、操作期间重入和关闭后调用均报错。提前保存的方法引用在调用时仍检查所有权及关闭状态。普通属性对象按原样返回，这不是防止调用方访问内部对象的安全隔离。

```python
from gfootball.frame_sync.server_runtime import ServerSettings, native_engine

with native_engine(ServerSettings()) as engine:
    info = engine.get_info()
```

`close()` 可重复调用。资源关闭返回之前仍占用容量；初始化失败时原始引擎由初始化器关闭，池退还创建名额。所有权包装失败同样释放资源。主操作和清理同时失败时保留主异常，并在解释器支持时添加清理说明。自定义工厂必须清理抛错前尚未移交的部分资源；其 `close()` 必须释放资源，即使同时报告错误。

正常使用应显式关闭或使用上下文管理器。没有保留方法或其他引用时，包装对象销毁会触发现有 EngineLease 的非缓存清理；保留方法会有意保留其所有者。这不构成原生图形资源跨线程 GC 的验收。

## 原生工厂与存档身份

`_initialize_native_engine()` 是工厂内部的原始初始化器，仅应在取得名额后调用。它先构造场景，再创建、启动和 reset 实际 GameEnv；启动或 reset 失败会关闭原始实例。

带身份的工厂在同一次容量预留内完成资源指纹、原生初始化和初始化后的身份核对。因此满额请求不会先扫描约 91 MB 的资源，也不会嵌套占用两个名额。`engine_pool.py` 与 `owned_engine.py` 已进入存档实现身份；此前实现生成的原生存档可能因身份不同而被拒绝。没有提供跨实现版本的迁移保证。

## 验证范围

<!-- 2026-09-10: 自然终局及当前回归取代旧说明，保留历史。
Windows Python 3.14.6 已通过 17 项所有权检查及 5 项实际比赛路径检查：包括并发创建、关闭期间容量、失败回收、1000 次生命周期、真实 TCP/UDP Host 与 Join、实际保存继续和回放。资源采用明确的可关闭对象或独立状态归约器，未模拟导入 GameEnv。受影响完整回归为资源与录制 146 项、比赛与存档 201 项、共享网络 219 项。
-->
Windows Python 3.14.6 的所有权检查仍包含 17 项通用用例和 5 项实际比赛用例；自然终局另新增 27 项，见[比赛生命周期](match_lifecycle.md)。当前完整回归为资源与录制 146 项、比赛与存档 228 项、共享网络 219 项。资源采用明确的可关闭对象或独立状态归约器，未模拟导入 GameEnv。

<!-- 2026-09-10: 自然终局及当前回归取代旧说明，保留历史。
新增 3 项真实 Core/GameEnv 验证在 `gfootball/test_owned_engine_native.py`，尚未执行；录制探针增加 `--environment --native` 时强制包含它们。全部环境、原生和渲染组共 28 项，比赛探针另有 4 项真实原生用例，均保留待验收状态。
-->
共享准入新增的 3 项真实 Core/GameEnv 验证仍在 `gfootball/test_owned_engine_native.py`，录制探针增加 `--environment --native` 时强制包含它们。全部环境、原生和渲染组共 28 项，比赛探针另有 7 项真实原生用例，均保留待验收状态。

本限制衡量实例数量。直接调用公开 GameEnv 绑定、直接创建 C++ 上下文、每个引擎的原生字节数、整个进程 RSS、GPU 资源和长期增长仍需独立预算及实际引擎测量。当前结果不是完整内存或产品级验收。
