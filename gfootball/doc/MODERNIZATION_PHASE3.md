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
