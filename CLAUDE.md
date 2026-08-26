# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

**项目定位（2026-08-26 明确）**：学习型项目 —— 借这个真实代码库练习四条主线：游戏引擎架构、网络编程、AI（游戏 AI 与 RL）、Modern C++（C++23/C++26 实现改造）。技术选型和重构方向优先服务学习价值；确定性帧同步联机是当前的主线工程。

Google Research Football 的二次开发仓库：基于 GameplayFootball 引擎的强化学习足球环境。三部分组成：

- **`gfootball/`** — Python 包：Gym 环境（`env/`）、场景（`scenarios/`）、PPO 训练示例（`examples/`）、`play_game.py`
- **`third_party/gfootball_engine/`** — C++ 游戏引擎，编译为 Python 扩展模块 `_gameplayfootball.so`，供 Python 侧调用
- **帧同步联机（进行中）** — Python 侧 `gfootball/frame_sync/`（server/client/protocol/presentation）、引擎侧 `src/frame_sync/`、独立 C++ 网络实现 `frame_sync_asio/`

## 常用命令

### 构建引擎

```bash
python3 -m pip install .            # 完整安装（内部调用 gfootball/build_game_engine.sh 编译引擎）
gfootball/build_game_engine.sh      # 仅编译引擎：in-source cmake + make，并 symlink libgame.so → _gameplayfootball.so
GFOOTBALL_USE_PREBUILT_SO=1 python3 -m pip install .   # 使用预编译 so，不编译
```

- 开发安装（`pip install -e .`）会在仓库根创建 `gfootball_engine` → `third_party/gfootball_engine` 的 symlink。
- **编译一律单线程（2026-08-26 约定）**：`make -j 1`；`cmake --build` 显式加 `-j 1`，不要并行编译。
- **新增引擎源文件必须登记到 `sources.cmake`**（由根 CMakeLists.txt include），否则不参与编译。
- 独立帧同步 server/client（仅需 Boost.Asio，无引擎依赖）：在 `third_party/gfootball_engine` 下执行 `cmake -S frame_sync_asio -B build_fs_asio && cmake --build build_fs_asio`。
- 引擎构建已导出 `compile_commands.json` 供 clangd 使用；勿提交（.gitignore 已忽略）。
- 依赖：SDL2(image/ttf/gfx)、Boost(thread/system/filesystem)、OpenGL/EGL、Python 开发头文件；Linux apt 安装列表见 README。

### 运行

```bash
python3 -m gfootball.play_game --action_set=full                        # 玩游戏（键盘控制见 README 键位表）
python3 -m gfootball.examples.run_ppo2 --level=academy_empty_goal_close # PPO 训练示例
```

### 测试

```bash
python3 -m gfootball.frame_sync.run_e2e_test                # 帧同步端到端（1 server + 2 clients + state hash 校验）
python3 -m gfootball.env.wrappers_test                      # 运行一个 absltest 测试文件
python3 -m gfootball.env.wrappers_test SingleAgentWrapperTest.test_xxx   # 运行单个测试
```

Python 测试均为 absltest 风格（`gfootball/env/*_test.py`）。C++ 侧无单元测试框架，引擎改动靠 e2e 测试和 `play_game` 冒烟验证。Docker 方式见 `run_docker_test.sh` 与 `Dockerfile*`。

## 架构

### Python ↔ C++ 边界

- 调用链：`gfootball/env/football_env.py` → `football_env_core.py` → `import gfootball_engine as libgame`（pybind11 模块）。
- **绑定定义在 `third_party/gfootball_engine/ai.cpp`**（`PYBIND11_MODULE(_gameplayfootball, m)`）；引擎侧环境封装是 `src/game_env.cpp` 的 `GameEnv`（`step` / `get_state` / `set_state` / `SetControllerSetup` 等）。
- 观测与动作预处理都在 Python 侧（`env/observation_*.py`）；动作用 `SetDirection` / `SetButton` 写入控制器。

### 引擎内部（`third_party/gfootball_engine/src`）

- `blunted.cpp/hpp` — SystemManager：系统链式注册（Directory / Graphics / Physics / Audio…），系统间经 SystemMessage 通信。
- `onthepitch/` — 比赛逻辑：Match、Team、Player、Ball、Referee、HumanGamer、TeamAIController 等。
- `scene/` + `systems/graphics` — 场景图与渲染。`render=false` 时用 `MockRenderer3D` 无头运行（见 `src/frame_sync/HEADLESS.md`），服务器进程因此不依赖 GPU/窗口。
- `base/math` 与 `base/geometry` — 高频调用的数学库，性能最敏感（见下方规则）。
- `ecs/` — 自研最小 ECS（World / Entity / ComponentPool），正在分阶段替换 onthepitch 的传统对象图（阶段1 已接入）；组件池按 Entity id 排序遍历以保证跨平台确定性。

### 帧同步联机

协议细节见 `src/frame_sync/PROTOCOL.md`，要点：

- 锁步 + 权威服务器：Connect → SessionStart(seed/scenario/slots) → Ready → 每帧客户端发 `FrameInput` → 服务器汇总（超时补默认输入）→ 广播 `AuthoritativeFrame` → 每 K 帧下发 StateHash 校验。
- 一网络帧 = 一次 env step = `physics_steps_per_frame`（默认 10）个内部 ProcessPhase tick。
- SlotInput 二进制布局：2×float 方向 + uint16 按钮位掩码；槽位顺序 = left_agents 在前、right_agents 在后，与 `SetControllerSetup` 一致。
- 客户端预测上限 `MAX_PREDICT_AHEAD_FRAMES=3`，连续 `MAX_FRAMES_WITHOUT_PACKET=5` 帧无包则停预测只等权威。
- ⚠️ **常量双份维护**：`gfootball/frame_sync/config.py` 与 `src/frame_sync/protocol.hpp` 必须保持一致，改动时两处同改。
- 服务器无头单步 API：`GameEnv::StepWithInput()` 直接解码输入缓冲区并推进一帧，不渲染。

**确定性是硬约束**：相同 seed + 相同输入序列必须产出一致 state hash。改比赛逻辑时注意浮点运算与容器遍历顺序的确定性（ECS 池按 id 排序即为此）。

## 编码规则（`.cursor/rules/` 全文适用）

- **修改流程（最重要）**：注释掉原代码并注明**日期**与**原因**，再写入新代码；不做占位实现，实现须真实可用。
- **Git 提交**：仅在用户明确回复「提交 git」或等价确认后才执行 add/commit/push。
- **C++ 标准**：目标 C++23（两处 CMakeLists 均 `set(CMAKE_CXX_STANDARD 23)`，见 `CXX_STANDARD.md`，主引擎与 frame_sync_asio 保持一致）。**工具链为 gcc-toolset-15（GCC 15.2，`/opt/rh/gcc-toolset-15/root/usr/bin/`）**，`build_game_engine.sh` 已自动置于 PATH；手动 cmake 时须导出 `CC/CXX` 指向 GTS-15（系统默认 gcc 11 不支持 C++23）。学习方向含 C++26 改造：GTS-15 已接受 `-std=c++26`，按特性可用性渐进采用。
- **风格**：Google C++ Style Guide —— 类型 PascalCase、函数/变量 snake_case、常量 kConstantName、类成员尾下划线 `name_`、2 空格缩进；同时参考 C++ Core Guidelines，冲突时以本仓库规则为准。
- **六大特殊成员函数**显式 `=default` / `=delete`，不依赖隐式生成；多态基类析构必须 `virtual`。
- **智能指针**：新代码优先 `std::unique_ptr` / `std::shared_ptr`；仅在与 RefCounted 体系交互时用 `boost::intrusive_ptr`（refCount 已改为 std::atomic）。
- **Boost → std 渐进迁移**：每次替换注明日期+原因，保持可编译可测；Boost 有明确性能/能力优势处保留。（Boost.Python 已被 pybind11 取代。）
- **`base/math`、`base/geometry` 性能优先**：热路径 `inline`、能用 `constexpr` 则用、小对象按值传递、避免堆分配与虚调用；性能敏感改动注释说明预期影响。
