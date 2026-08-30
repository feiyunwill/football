# Headless 服务器可运行性

## 无渲染路径

- 启动时使用 `render=false`（例如 `main.cpp` 中 `run_game(..., false)`）。
- `GraphicsSystem::Initialize(false, ...)` 会使用 `MockRenderer3D`，不创建 OpenGL/EGL/SDL 窗口，`CreateContext` 直接返回 true。
- `GameEnv::step()` 中当 `GetGameConfig().render` 为 false 时只执行 `do_step(physics_steps_per_frame)`，不调用 `render()`。
- 服务器进程因此不依赖 GPU/显示器，可稳定执行 `step()`、`get_state()`、`set_state()`。

## 服务器专用单步 API

- `GameEnv::StepWithInput(const void* frame_input_buffer, size_t buffer_size)`：解码本帧权威输入、写入控制器、执行一次 env step（等价于一步 `step()` 的逻辑与步进，但不渲染）。
- 输入缓冲区格式见 [PROTOCOL.md](PROTOCOL.md)，槽位顺序与 `left_agents`/`right_agents` 一致。
- 服务器每帧：收齐或超时补默认输入 → 调用 `StepWithInput` → 可选下发权威帧/state hash。
