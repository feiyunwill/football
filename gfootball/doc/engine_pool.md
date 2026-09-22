# Python 引擎复用与释放

<!-- 2026-09-10: 比赛应用工厂现已接入同一池，保留先前范围说明。
`FootballEnvCore` 使用进程内共享的 `gfootball.engine_pool.ENGINE_POOL`。默认最多存在 32 个由该池负责的引擎，空闲缓存最多保留 2 个无渲染引擎和 1 个渲染引擎。创建、借出和正在关闭的对象都占用总名额；容量满时在调用工厂前抛出 `EngineCapacityError`。这是对象数量限制，不是每个原生引擎的字节预算或整个进程的 RSS 上限。直接创建原生 GameEnv 不受此池限制。
-->
`FootballEnvCore`、`server_runtime.native_engine()` 和 `match_identity.native_match_engine()` 使用进程内共享的 `gfootball.engine_pool.ENGINE_POOL`。默认最多存在 32 个由该池负责的引擎，空闲缓存最多保留 2 个无渲染引擎和 1 个渲染引擎。创建、借出、关闭中及空闲对象都占用总名额；容量满时在调用工厂前抛出 `EngineCapacityError`。这是对象数量限制，不是每个原生引擎的字节预算或整个进程的 RSS 上限。绕过这些应用工厂直接调用公开 GameEnv 绑定或创建 C++ 上下文，仍不受此池限制。

Core 默认复用匹配的空闲资源。比赛工厂经由 `acquire(..., reuse=False)` 创建新实例；相同配置的缓存也先关闭，比赛结束直接释放，不归还缓存。所有权、异常处理与身份检查顺序见[比赛引擎的容量与所有权](owned_engine.md)。

复用要求渲染类型、分辨率、启动环境和原 Thread 对象一致。启动环境记录当前目录及 GFOOTBALL_DATA_DIR、GFOOTBALL_FONT、DISPLAY、SDL_VIDEODRIVER、EGL_PLATFORM；每个字段最多 4096 字符。分辨率每边 1–8192，最多 16777216 像素。不同配置的空闲引擎在新分配前关闭，线程编号重用不能绕过匹配。跨线程归还会关闭引擎。Python 的池并发检查不构成 SDL/OpenGL 跨线程验收。

物理步长不进入复用键：每次 NewScenario 后重新验证和设置 physics_steps_per_frame（整数 1–1000），使同分辨率的回放仍能改变步长。无渲染环境 reset 时改变启动配置会更换引擎；已经启动的渲染环境改变启动配置则明确报错，需要关闭并重新创建，避免沿用旧尺寸的图形资源。

正常 `env.close()` 在录制成功关闭且环境没有失败的情况下归还缓存。`close(finalize=False)`、构造失败、发生过失败的 reset/step/set_state、录制关闭失败及 GC 都不会缓存该资源。关闭会清除 Core 的观察引用。重复关闭安全；池始终在归还前转移资源所有权，避免并发重复关闭。原生 `GameEnv.close()` 由当前 C++ 源码声明为 noexcept；通用池工厂必须在抛错时自行清理尚未转移的资源。

Core 的公开操作和 close 使用同一把可重入锁，关闭不会在另一个公开操作执行期间释放引擎。进程检查先于这把锁，fork 后禁止继续使用继承的 Core/池；使用 spawn 创建新的环境。此限制不等于已经验证 fork 后原生图形资源安全。

第一次 render 先取得独占渲染名额，保留旧引擎，随后完成新渲染器启动、原生快照恢复、相机预热和观察生成。全部成功后才归还旧引擎。失败时关闭候选渲染器并恢复原来的引擎、观察、步骤计数和录制对象；另一实例占用渲染器时抛出 `RendererBusyError`。disable_render 暂停绘制但保留渲染名额，直到该环境关闭。

可以查看或释放空闲缓存：

```python
from gfootball.engine_pool import ENGINE_POOL
print(ENGINE_POOL.stats())
ENGINE_POOL.clear_idle()
```

`clear_idle()` 不关闭仍在使用的环境。`ENGINE_POOL.close()` 为终止操作，禁止之后的创建，并在现有借用者归还时直接关闭；通常由退出钩子执行。用户保留的对象引用不由池清除。

验证命令（输出目录必须不存在）：

```sh
python .project/checks/python_recording_probe.py --replay --output NEW_OUTPUT_DIRECTORY
# 需要真实 native/Gym/absl/six 环境：
python .project/checks/python_recording_probe.py --replay --environment --native --output NEW_NATIVE_DIRECTORY
# 额外需要真实 SDL/OpenGL display：
python .project/checks/python_recording_probe.py --replay --environment --native --rendering --output NEW_RENDER_DIRECTORY
```

<!-- 2026-09-10: 共享比赛所有权新增 17 项并重跑，保留旧结果。
2026-09-10 当前 Windows 结果为 129/129：21 项通用资源池检查和此前 108 项录制/回放回归。21 项使用明确的可关闭资源 oracle，未替代或模拟导入 GameEnv。真实 Core/native 新增 6 项、渲染 4 项均尚未执行；原有 13 项环境入口与 2 项 GameEnv 回放检查也仍待执行。Core 仅完成源代码审查、公开类 AST 检查和 Python 3.9 语法检查；实际解释器为 Windows Python 3.14.6。这些结果不满足完整原生或产品级验收。
-->
2026-09-10 当前 Windows 结果为 146/146：21 项资源池、17 项比赛所有权及此前 108 项录制/回放回归。资源用例使用明确的可关闭对象，未替代或模拟导入 GameEnv。新增 3 项真实 Core/GameEnv 共享准入检查，加上此前 25 项环境/原生/渲染检查，共 28 项尚未执行。Core 仅完成源代码审查、公开类 AST 检查和 Python 3.9 语法检查；实际解释器为 Windows Python 3.14.6。这些结果不满足完整原生或产品级验收。
