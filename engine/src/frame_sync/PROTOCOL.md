# Frame Sync Protocol

## Frame semantics

- **One network frame** = one environment step = `physics_steps_per_frame` (default 10) internal `ProcessPhase()` ticks.
- **Frame ID**: Starts at 0 after session start; increments by 1 per env step. All clients and server advance the same frame_id when the server runs one `step()`.
- **Slot order**: Input slots follow `SetControllerSetup`: first `left_agents` slots (left team), then `right_agents` slots (right team). Total slots = `left_agents + right_agents`.

## Timeout and default input

- **Server**: Waits for each client to send `FrameInput` for the current frame_id. Wait time is at most `FRAME_INPUT_TIMEOUT_MS` (see `protocol.hpp`).
- **Default input**: If a client does not send input for a slot in time, the server uses `SlotInput::Default()` (direction 0,0; no buttons pressed) for that slot when building the authoritative frame.
- **Late input**: Input arriving for an already-executed frame is ignored (or logged); server does not re-run past frames.

## Message types

| Type | Direction | Description |
|------|-----------|-------------|
| Connect | Client -> Server | Join request; client reports which slot(s) it controls. |
| Disconnect | Either | Connection closed. |
| FrameInput | Client -> Server | This frame's input for the client's controlled slot(s). |
| AuthoritativeFrame | Server -> Client | frame_id + full input for all slots; clients apply and run one step. |
| StateHash | Server -> Client | Optional; every K frames for verification. |
| SessionStart | Server -> Client | Scenario params, seed, left_agents, right_agents; client applies setConfig + reset. |
| Ready | Client -> Server | Sent after client applied SessionStart; server starts frame 0 when all ready. |
| Heartbeat | Bidirectional | 2026-08-28: 保活包，载荷 frame_id(4B) + timestamp_ms(4B)。服务器每 HEARTBEAT_INTERVAL_MS(1000ms) 广播一次；客户端收到后重置超时计数器。连续 HEARTBEAT_MISS_LIMIT(5) 个间隔无心跳则判定断连。 |
| TakeoverNotify | Server -> Client | 2026-09-01: 通知客户端 slot 被 AI 接管。载荷 slot_index(2) + frame_id(4)。 |
| HandbackNotify | Server -> Client | 2026-09-01: 通知客户端控制权已归还。载荷 slot_index(2) + frame_id(4)。 |
| ReconnectRequest | Client -> Server | 2026-09-01: 重连请求，携带 session_token(8) 用于识别身份。 |
| StateSnapshot | Server -> Client | 2026-09-01: 完整游戏状态快照。载荷 frame_id(4) + state_len(4) + state_bytes。 |

## Full action per slot

- **SlotInput** encodes full per-frame action: direction (dir_x, dir_y) + button bitmask for all `e_ButtonFunction` (0..11). Applied via SetDirection/SetButton; sticky behaviour is per-step (ResetNotSticky after step). Slot order matches `left_agents` then `right_agents` and `SetControllerSetup`.

## Prediction cap (client; tunable in protocol.hpp)

- **MAX_PREDICT_AHEAD_FRAMES** (default 3): If (current predicted frame − last confirmed authoritative frame) > N, client does not predict this frame; waits for next authoritative frame.
- **MAX_FRAMES_WITHOUT_PACKET** (default 5): If no server packet received for M consecutive frames, client enters wait-for-authority mode (stops predicting until packet received again).
- **STATE_HASH_INTERVAL_K** (default 10): Server sends state hash every K frames; client compares with local hash for verification.
  - 2026-08-26: Hash 输入改为 **canonical state digest**（引擎 `GameEnv::get_state_digest()`）：序列化时跳过 `EnvState::setValidate(false)` 标记的不稳定区段（相机轨迹、球员颜色缓冲、边裁、HID 等）。这些区段含跨进程不定的字节（堆布局垃圾值），若用全量 `get_state('')` 计算 hash，即使比赛逻辑完全一致也必然误报不同步。客户端本地校验须传 `get_state_digest()` 返回值。
  - 2026-08-26: digest 启用后仍残留 ~77–400 字节/对的间歇性跨进程差异，根因是 `blunted::radian`（float angle_ + bool rotated_ + 3B padding）整体 memcpy 序列化把 padding 堆垃圾写进 state，而比较经 `operator real()` 只看角度值。已改为逐成员序列化（`EnvState::process(radian&)`，总长仍 8B、布局兼容）；定位工具为引擎 `GameEnv::compare_state_bitwise()`（memcmp 级差异日志）。

## Binary layout (summary)

- **SlotInput**: 2 × float (dir_x, dir_y) + 1 × uint16 (button bitmask). Total `SLOT_INPUT_BYTES`.
- **AuthoritativeFrame**: MessageType (1) + frame_id (4) + num_slots (2) + num_slots × SlotInput.
- **Client FrameInput**: MessageType (1) + frame_id (4) + num_my_slots (2) + for each: slot_index (2) + SlotInput.
- **TakeoverNotify**: MessageType (1) + slot_index (2) + frame_id (4). Total 7 bytes.
- **HandbackNotify**: MessageType (1) + slot_index (2) + frame_id (4). Total 7 bytes.
- **ReconnectRequest**: MessageType (1) + session_token (8). Total 9 bytes.
- **StateSnapshot**: MessageType (1) + frame_id (4) + state_len (4) + state_bytes (state_len). Total 9 + state_len bytes.

## Session Token

用于断线重连时识别客户端身份。

- **生成**: `token = FNV1a(slot_index | (seed << 16) | (session_id << 32))`
- **session_id**: 服务器在 Connect 时分配的唯一标识（`uint32_t`）
- **C++ API**: `MakeSessionToken(slot_index, seed, session_id)`
- **Python API**: `make_session_token(slot_index, seed, session_id)`
- C++ 和 Python 生成的 token 保证一致
