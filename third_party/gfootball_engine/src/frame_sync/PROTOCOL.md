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

## Full action per slot

- **SlotInput** encodes full per-frame action: direction (dir_x, dir_y) + button bitmask for all `e_ButtonFunction` (0..11). Applied via SetDirection/SetButton; sticky behaviour is per-step (ResetNotSticky after step). Slot order matches `left_agents` then `right_agents` and `SetControllerSetup`.

## Prediction cap (client; tunable in protocol.hpp)

- **MAX_PREDICT_AHEAD_FRAMES** (default 3): If (current predicted frame − last confirmed authoritative frame) > N, client does not predict this frame; waits for next authoritative frame.
- **MAX_FRAMES_WITHOUT_PACKET** (default 5): If no server packet received for M consecutive frames, client enters wait-for-authority mode (stops predicting until packet received again).
- **STATE_HASH_INTERVAL_K** (default 10): Server sends state hash every K frames; client compares with local hash for verification.

## Binary layout (summary)

- **SlotInput**: 2 × float (dir_x, dir_y) + 1 × uint16 (button bitmask). Total `SLOT_INPUT_BYTES`.
- **AuthoritativeFrame**: MessageType (1) + frame_id (4) + num_slots (2) + num_slots × SlotInput.
- **Client FrameInput**: MessageType (1) + frame_id (4) + num_my_slots (2) + for each: slot_index (2) + SlotInput.
