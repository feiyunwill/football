# 原生展示入口审查

2026-09-13。归属 ms-22.1 → plan-22.1.2 → task-22.1.2.1，并作为 ms-24.1 实际图像验收的输入。以下为当前源码调用链审查，尚未修复，也未用实际程序图像或呈现计数复现。当前保持正式 c 的源代码输入冻结；这些展示发现尚未进入实现或图像验收。

三个原生入口仍使用旧的展示调用方式：`standalone_game.cpp`、`integrated_client.cpp`、`integrated_client_udp.cpp`。它们先调用 `Match::PutInterpolated(t)`，再调用 `env.render()`。后者通过 `GameTask::PrepareRender()` 的默认参数 `-1` 调用 `Match::Put()`，重新发布当前球员、球和相机姿态。因此手动设置的中间姿态会在蒙皮和上传前被普通姿态覆盖。现有公共 `GameEnv::render_interpolated()` 已把插值放在正确阶段，后续应由这些入口接入公共所有者接口，并验证实际程序的中间帧。

`GameEnv::render()` 默认 `swap_buffer=true`，内部 `GraphicsTask::Render()` 调用 `OpenGLRenderer3D::SwapBuffers()`，在有 SDL 窗口时呈现一次。三个入口随后又直接调用 `SDL_GL_SwapWindow()`。这一调用链会在同一渲染循环内请求两次窗口交换；实际显示的闪烁、重复等待和帧时间影响仍需真实程序验证，不能由无头吞吐数据推断。应统一呈现所有权，并验证每个提交图像仅呈现一次。

独立本地入口的插值因子取 `render_elapsed / logic_period`，而不是距最后逻辑发布的时间；即使接通正确插值入口，这个时基仍会导致中间帧比例错误。TCP/UDP 入口已使用 `now - last_logic_time`，但三个入口的时刻更新、暂停恢复和延迟后的积压策略仍需与既有节拍契约统一。

附带复核的异常路径也仍待修复：`Gui2Caption::Redraw()` 没有检查两次 TTF 渲染和缩放的失败返回值，在空指针检查前读取 `textOutlineSurfTmp->h`；临时 surface 和 tracker 状态缺少异常保护。`Surface::Resize()` 在验证缩放及格式转换成功前释放旧 surface，并直接读取 `newSurf->format`。后续需要真实分配/字体/缩放失败注入，确认旧资源保留、所有临时资源释放和 tracker 恢复。

| 任务 | 具体实现与验证 |
| --- | --- |
| [task-22.1.2.1](../tasks/task-22.1.2.1.md) | 三个入口接入统一的姿态保存与插值渲染接口；以最后逻辑发布时刻计算比例；实际 SDL 程序验证暂停、恢复、回滚及中间帧 |
| [task-24.1.2.1](../tasks/task-24.1.2.1.md) | 真实可执行文件的呈现计数与图像证据；检查重复交换、中间姿态、非空图像和暂停恢复显示，不只测试公共 API |
| [task-24.1.1.1](../tasks/task-24.1.1.1.md) | 明确 surface 的异常所有权，逐阶段失败时保留旧资源并释放临时对象；验证后再讨论移除旧的额外 surface 拷贝 |

源码依据：[原生 TCP 入口](../../engine/src/frame_sync/integrated_client.cpp)、[原生 UDP 入口](../../engine/src/frame_sync/integrated_client_udp.cpp)、[本地入口](../../engine/src/frame_sync/standalone_game.cpp)、[GameEnv](../../engine/src/game_env.cpp)、[渲染准备](../../engine/src/gametask.cpp)、[普通与插值姿态](../../engine/src/onthepitch/match.cpp)、[窗口呈现](../../engine/src/systems/graphics/rendering/opengl_renderer3d.cpp)、[文字重绘](../../engine/src/utils/gui2/widgets/caption.cpp)、[surface 调整](../../engine/src/scene/resources/surface.cpp)。

当前容量场景中的原生 TCP/UDP 客户端为无头运行。Python 图形回归及公共原生 API 的通过结果，也不能替代这三个旧主循环的完整图形路径验收。

进一步只读核对：三个入口均在 `step()`／`tick()` 之后调用姿态保存，这不能提供上一逻辑状态。接入公共接口时须在实际逻辑变更之前保存，并在首个渲染 tick 前建立初始历史；否则 `render_interpolated()` 会因公共保存标志未设置而拒绝执行。网络等待期间也不能把每次调度时刻当成新状态发布时间，回滚连续性应保留实际已显示姿态并单独验证。

另一个接入约束是 `ContextHolder` 退出时会解绑当前图形上下文。原窗口标题更新依赖外层上下文，因此替换为公共渲染调用时仍需为窗口操作保留明确的所有者作用域。`set_state()` 本身保留显示历史；`reset()` 清空公共保存／呈现标志。后续实现按这些实际接口语义处理初始帧、普通步进、等待、回滚、暂停和重置，不采用简单的函数名替换。


2026-09-13 补充输入路径审查（尚未实际键盘复现）：独立本地入口的 `get_action()` 在无方向键时返回 `game_idle`，而 `GameEnv::action(game_idle)` 不清除方向；它也只提交 `get_button_action()` 返回的第一个动作，不提交释放动作。`AIControlledKeyboard::ResetNotSticky()` 仅清除传球、射门、铲球和切人，保留冲刺、压迫、盘带及方向。因此当前源码会在松开方向／冲刺等键后继续保留这些输入；同时按下冲刺和射门时只选择优先级靠前的射门。暂停本身不清输入，暂停期间 action 和 step 直接返回，后续恢复同样需要完整输入发布。该结论来自确定的调用语义，后续必须通过实际 SDL 事件、控制器状态与球员响应验证修复。

此外，独立本地入口调用的 `GameEnv::step()` 在非实时模式、render=true 时还会自动执行一次普通渲染，然后主循环继续执行独立的 60 Hz 渲染。统一展示时需同时消除这个逻辑步呈现旁路，而不改变公开 step 的既有语义；可通过已解码完整输入的 `StepWithInput()` 接口推进逻辑，但需保持名单／槽位配置、时间推进、暂停和结束条件。

Python 的 `poll_input` 实际定义于 [GameEnv_Python 绑定](../../engine/ai.cpp)中的 `poll_input_python()`，持有 `PythonWindowInput`，并非 GameEnv 的 C++ 公共成员。原生入口不能直接调用一个不存在的 GameEnv::poll_input；后续复用原生事件采样器或抽出共有所有者接口，再由各绑定封装。图索引对 engine/ai.cpp 的第 212 行报告局部解析缺口，本次所用第 43 行输入方法已直接读源核对。

上述输入发现对应 [task-22.1.1.1](../tasks/task-22.1.1.1.md) 与 [task-22.1.1.2](../tasks/task-22.1.1.2.md)；不作为这些任务已经修复或通过的证据。源码另见 [控制器状态实现](../../engine/src/ai/ai_keyboard.cpp)。

2026-09-13 接入复核：本地入口逐项构造 [FormationEntry](../../engine/src/gamedefines.hpp)，其末参数是 controllable，仅两队守门员为 true，其余场上球员为 false；[共享默认场景](../../engine/src/frame_sync/default_scenario.hpp)则在构造后显式把所有球员设为可控制。本地产品入口需明确处理这一名单差异并验证切人及场上球员响应，不能为了输入接入而默默替换不可变基准场景。

命令和异常清理还需一起验证：TCP 的 save_replay() 是退出时保存接口，会先停止录制；若将 P 映射为比赛中保存，必须处理后续录制连续性。UDP 主循环持有可连接的 std::thread，SDL／渲染异常路径尚缺异常安全的停止与回收；后续入口改造需覆盖此路径。

独立目录已准备 [TCP／UDP 缓存发送入口](../optimization/benchmarks/native-network-input-20260913-a/README.md)：通过处理权威帧后的供应回调，把发送、预测和输入历史绑定到同一实际帧。源码尚未编译，主循环仍未替换，不能视为输入或网络门禁通过。
