# 现代化阶段 3 实施说明

## 3.1 ai.cpp 迁移到 pybind11（已完成）

**状态**：pybind11 迁移已完成。CMake 使用 FetchContent 拉取 pybind11 v2.11.1，`ai.cpp` 已全部改为 pybind11 绑定，GIL 通过 `py::call_guard<py::gil_scoped_release>()` 释放。

**注意事项**：
- `env.config` / `env.game_config` 使用 `def_property` + `reference_internal`，保证 Python 侧 `reset(env.config)` 传入的是 C++ 引用语义，与 Boost.Python 行为一致。
- 枚举 `e_PlayerRole` 必须在 `FormationEntry` 之前绑定（`FormationEntry` 构造函数依赖该枚举）。
- 本地/CI 编译需具备 OpenGL、SDL2 等依赖；无图形环境时 CMake 可能报错，属环境限制非绑定代码问题。

**验证清单**（迁移后建议执行）：

| 步骤 | 操作 | 命令或检查 |
|------|------|------------|
| 1. 依赖 | 安装构建脚本所需（可选） | `pip install psutil` |
| 2. 编译 | 构建 C++ 扩展 | `bash gfootball/build_game_engine.sh` 或 `pip install -e .` |
| 3. 导入 | 确认模块与类型可导入 | `python -c "import gfootball_engine; from gfootball_engine import GameEnv, GameState, e_BackendAction; print('OK')"` |
| 4. 环境创建 | 创建 env 并读 config | `python -c "import gfootball_engine as libgame; env = libgame.GameEnv(); env.config.game_duration = 100; print(env.config.game_duration)"` 应输出 `100` |
| 5. reset(config) | 确认引用语义 | `python -c "import gfootball_engine as libgame; env = libgame.GameEnv(); env.config.game_duration = 200; env.reset(env.config, False); print(env.config.game_duration)"` 应输出 `200` |
| 6. step/get_frame | 基础步进与帧数据 | `python -c "import gfootball_engine as libgame; env = libgame.GameEnv(); env.start_game(); f = env.get_frame(); print(type(f), len(f))"` 确认返回 `bytes` 且长度合理 |
| 7. 集成 | 跑上层入口或场景 | `python -m gfootball.run_ppo --level=academy_empty_goal`（或其它 level）跑若干步无报错；或运行 `gfootball/scenarios/test_example_multiagent.py` 等现有脚本 |

**目标**：用 pybind11 替代 Boost.Python，使用 `py::call_guard<py::gil_scoped_release>()` 在 step/render/get_state 等调用时释放 GIL。

**步骤概要**：

1. **CMake**（`third_party/gfootball_engine/CMakeLists.txt`）  
   - 使用 `FetchContent_Declare(pybind11)` 或 `find_package(pybind11)` 引入 pybind11。  
   - 主库 `OUTPUT_LIB_NAME` 的 `target_link_libraries` 中移除 `Boost::${BOOST_PYTHON_VERSION}`，改为 `pybind11::module`。  
   - 若不再需要 Boost.Python，可移除 `FIND_PACKAGE(Boost ... python)`，保留 `Boost::system`、`Boost::thread`、`Boost::filesystem` 供其余代码使用。

2. **ai.cpp 重写**  
   - 头文件：`#include <pybind11/pybind11.h>`、`#include <pybind11/stl.h>`，移除 Boost.Python 与 `Python.h` 的手动 GIL 操作。  
   - 模块：`PYBIND11_MODULE(_gameplayfootball, m)` 替代 `BOOST_PYTHON_MODULE`。  
   - 类型绑定：`py::class_<>`、`py::enum_<>` 替代 `class_<>`、`enum_<>`；`std::vector` 用 `py::bind_vector` 或 `.def("__getitem__", ...)` 等实现序列协议。  
   - 需释放 GIL 的接口（如 `step`、`step_with_input`、`render`、`get_state`、`set_state`、`reset`、`get_frame`）：在 `.def()` 上添加 `py::call_guard<py::gil_scoped_release>()`。  
   - `step_with_input`：参数改为 `py::bytes`，在 C++ 内用 `PyBytes_AsStringAndSize` 或 pybind11 的 `.cast<std::string>()` 取缓冲区。  
   - 返回值：`get_frame`/`get_state`/`set_state` 返回 `py::bytes` 即可。

3. **验证**  
   - 在 Linux/macOS/Windows 上执行 `pip install -e .` 并运行 `python -c "import gfootball_engine; env = gfootball_engine.GameEnv(); ..."` 及现有测试，确认与 Boost.Python 行为一致。

<!-- 2026-09-10: 保留原说明；旧示例共用服务端引擎并未等待异步关闭。
## 3.2 帧同步可选 asyncio 实现（已完成）

**状态**：已提供 `FrameSyncServerAsync`（`server_async.py`）与 `FrameSyncClientAsync`（`client_async.py`），协议与线程版一致，可与现有 `ClientLogicLoop` 配合使用。

**入口与用法**：

- **服务端**：`from gfootball.frame_sync import FrameSyncServerAsync`。调用 `server.start()` 初始化 env，在事件循环中 `await server.start_server()` 启动监听，再 `await server.run_loop_async(rate_hz=10, wait_for_ready=True)` 跑帧循环；或单独 `await server.run_one_frame()` 配合自定义调度。
- **客户端**：`from gfootball.frame_sync import FrameSyncClientAsync`。在事件循环中 `session_start, slot_assignment = await client.connect_async()`，然后 `client.send_ready()`；逻辑层用同一 `ClientLogicLoop(client, env, num_slots, callback, rate_hz)`，在 async 中每 tick 调用 `await asyncio.sleep(1/rate_hz)` 再 `loop.run_one_tick()` 即可。
- **兼容**：`FrameSyncServer`、`FrameSyncClient`、`ClientLogicLoop` 未改；asyncio 版为可选入口。

**简单示例**（asyncio 主循环 + 单 client 逻辑 tick）：

```python
import asyncio
from gfootball.frame_sync import FrameSyncServerAsync, FrameSyncClientAsync
from gfootball.frame_sync.client import ClientLogicLoop
from gfootball.frame_sync.protocol import default_slot_input

async def main():
    server = FrameSyncServerAsync(listen_port=12346)
    server.start()
    async def run_server():
        await server.run_loop_async(rate_hz=10)
    srv_task = asyncio.create_task(run_server())
    await asyncio.sleep(0.5)
    client = FrameSyncClientAsync('127.0.0.1', 12346, controlled_slots_callback=lambda: [(0, default_slot_input())])
    session_start, slot_assignment = await client.connect_async()
    client.send_ready()
    env = server.get_env()
    loop = ClientLogicLoop(client, env, server.get_num_slots(), lambda: [(0, default_slot_input())], rate_hz=10)
    for _ in range(50):
        await asyncio.sleep(0.1)
        loop.run_one_tick()
    server.stop()
    srv_task.cancel()
    client.close()

asyncio.run(main())
```

**目标**（原设计）：在保留现有线程版的前提下，提供基于 asyncio 的版本，便于与其它 async 代码集成、减少线程数。

-->

## 3.2 帧同步 asyncio 与同步入口

**2026-09-10 更新**：`FrameSyncServer` 与 `FrameSyncServerAsync` 现在共用有界 TCP 运行时。同步入口在一个自有线程中运行事件循环；异步入口使用调用方事件循环。输入收集、连接状态和引擎调用各有唯一所有者。Windows 的真实 TCP 合约检查通过，实际 GameEnv 与 Linux 验收仍待执行，详见 [服务端使用与容量约定](frame_sync_server.md)。

- `await server.start_server()` 初始化引擎并监听；也可先调用兼容入口 `server.start()` 单独初始化引擎。
- `run_loop_async()` 提供连续调度，`run_one_frame()` 提供外部逐帧调度；同一服务端只运行一个帧调度者。
- `stop()` 立即禁止新帧并请求清理；`await close_async()` 等待套接字、任务和引擎关闭。推荐异步上下文管理器。
- `ClientLogicLoop` 必须使用独立的客户端引擎，并按服务端种子、场景、球员布局初始化；不能把 `server.get_env()` 交给预测逻辑再次推进。

下面演示单个真实客户端提交输入和接收权威帧。示例依赖已构建的原生引擎，不启动预测或渲染，也不固定等待监听启动时间。

```python
import asyncio
from gfootball.frame_sync import FrameSyncServerAsync, FrameSyncClientAsync
from gfootball.frame_sync.protocol import default_slot_input

async def wait_ready(server):
    while not await server.all_clients_ready():
        await asyncio.sleep(0.005)

async def receive_frame(client):
    while not client.has_authoritative_frame():
        if client.is_disconnected():
            raise ConnectionError("The server disconnected")
        await asyncio.sleep(0.005)
    return client.pop_authoritative_frame()

async def main():
    async with FrameSyncServerAsync(listen_host="127.0.0.1", listen_port=0) as server:
        client = FrameSyncClientAsync("127.0.0.1", server.listen_port)
        try:
            session_start, slots = await client.connect_async()
            client.send_ready()
            await asyncio.wait_for(wait_ready(server), timeout=2)
            for frame_id in range(50):
                client.send_frame_entries(frame_id, [(slots[0], default_slot_input())])
                await server.run_one_frame()
                received_id, inputs = await asyncio.wait_for(receive_frame(client), timeout=2)
                assert received_id == frame_id
        finally:
            await client.close_async()

asyncio.run(main())
```
