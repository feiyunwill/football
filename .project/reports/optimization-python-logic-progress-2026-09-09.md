# Python logic history and confirmation review — 2026-09-09

Milestone → plan → task: **ms-21.1 → plan-21.1.2 → task-21.1.2.1** (memory budgets).
This is implementation progress, not task acceptance. `memory_budget.ready` remains
false. The overall framework, architecture, performance, feel, network, rendering
and AI optimization goal remains active.

## Findings and implementation

The old `ClientLogicLoop` kept a single rollback snapshot while allowing multiple
predicted frames. Authority older than the immediately preceding prediction could
be marked confirmed without correcting the engine. The loop saved state even when
prediction was stalled, computed its cap with an off-by-one difference, did not use
the adaptive cap during execution, and did not consume/verify server state hashes.
It also sampled local input independently for transport and prediction.

`gfootball/frame_sync/client_logic.py` now implements the public logic class;
`client.py` imports it and retains the replaced class as dated comments.

- Frame IDs distinguish the next frame to execute from the last confirmed frame.
  Prediction depth is `next - confirmed - 1`; frame zero receives the full configured
  allowance. Adaptive RTT caps are used in execution as well as status reporting.
- Each speculative frame stores its immutable pre-state, exact packed whole-frame
  input and resulting canonical hash. A correction restores its pre-state and
  replays every later speculative frame. Matching predictions confirm without
  stepping them again. Missing history, malformed inputs and nonconsecutive
  authority terminate the logic/client instead of silently accepting a gap.
- Local input is sampled once per frame, normalized to wire float32 precision,
  and retained while unconfirmed. The new shared transport method
  `send_frame_entries(frame_id, entries)` sends this input without invoking another
  callback. The existing `send_frame_input(frame_id)` callback API is preserved.
  Both TCP transports inherit the bounded explicit-entry API.
- Existing Python/native server implementations collect only their current frame
  and can discard future inputs. The oldest unconfirmed cached input is therefore
  retried unchanged at most once per 100 ms by default. This is an application
  compatibility retry on top of TCP. No new input sampling occurs during a retry,
  and only one old frame is retried per tick. Forward input buffering and negotiated
  scheduling remain network-milestone work.
- Hashes arriving early wait for confirmation; late hashes compare with the stored
  hash of that confirmed frame, not the current predicted state. Hash calculation
  uses the canonical engine digest and SHA-256's first eight little-endian bytes,
  matching `protocol.py` and native `state_hash.hpp`. Mismatch, contradictory hashes
  or a hash outside the retained window closes the client.
- Prediction stops without stepping when a snapshot/history limit is exceeded.
  If corrected replay grows beyond the budget, the engine returns to the corrected
  authoritative boundary and later speculation is discarded. Already sampled
  future inputs remain available, so they are not changed when prediction resumes.
- Failed predicted steps/hashes restore the saved pre-state. A failed correction
  root restores its pre-state; a later replay-save failure attempts recovery to the
  corrected authoritative boundary, then stops. If engine restore itself fails,
  the loop still terminates; there is no general engine exception-transaction claim.
  An authority-only step deliberately needs no extra prediction snapshot and any
  engine failure is terminal.
- No rollback snapshots are saved while stalled. Presentation snapshots are
  published only after state/confirmation changes, with the per-snapshot cap checked
  before publication. The presentation holder's own count/byte policy remains
  separate work.
- Logic ticks reject concurrency/reentry. Loop lifetime has its own guard; stop
  interrupts the monotonic timed wait. Reentry into `run_loop` from a manual tick
  rejects before cleanup can deadlock on the active tick's lock. Terminal failure
  clears retained history, hash queues and sampled-input caches and closes transport.

## Bounds and limits

| Resource | Default | Configurable hard maximum / behavior |
| --- | --- | --- |
| Speculative frames | 3 | 8, also constrained by RTT and no-authority fallback |
| One serialized snapshot | 1 MiB | 1 MiB, actual `sys.getsizeof(bytes/str)` |
| Retained prediction snapshot + packed input bytes | 8 MiB | 8 MiB total |
| One canonical digest | 1 MiB | 1 MiB; only its 64-bit hash is retained |
| Confirmed hash history | 1,024 entries | 1,024 entries |
| Pending authority hashes | 1,024-frame window | 1,024 entries/window |
| Sampled local input and retry timestamps | At most prediction depth + one | 9 frames × at most 22 slots |
| Authority work per logic tick | 8 frames | 32 frames; backlog suppresses new prediction |
| Hash work per logic tick | 64 messages | 1,024; shared between both hash drains |
| Oldest-input retry | 100 ms | Valid interval 10 ms–1 s; monotonic time |

These are application retention/work bounds. Python/native serialization allocates
its result before the returned object's size can be inspected. Temporary serialization,
container metadata (count bounded), native engine allocations, kernel buffers, RSS,
presentation storage and execution time inside a callback are not covered by the
history-byte number. Correction work is additionally bounded by at most eight
speculative records. A tick is not a hard real-time deadline.

## Reproducible evidence

```text
python .project/checks/python_logic_probe.py --output NEW_OUTPUT_DIRECTORY
```

Latest result: **61/61 passed**, no skips, no owned transport/fixture/logic threads
remaining, and no resource warnings, pending-task warnings or unobserved task
exceptions in the captured log.

- 26 logic tests, including independent deterministic state-machine oracles under
  random authority/hash delays: 1,000 confirmed/hash-verified frames with 2 slots
  (seed 42), and 1,000 with 22 slots (seed 43). Every retained confirmed hash is
  checked against the reference and history/hash/input-cache bounds are asserted.
- Two actual synchronous TCP tests: fragmented multi-frame correction with three
  confirmed hashes; and a peer that deliberately discards early frame 1/2 inputs,
  requiring their exact cached retries before confirming them.
- One actual asynchronous TCP test uses the same logic API, exact input-byte
  contract and three confirmed hashes.
- All 32 existing shared-buffer/synchronous/asynchronous TCP regressions reran
  against the current implementation, including actual disconnect → no engine work.
- Additional logic cases cover exact/adaptive/zero prediction caps, 1,000 stalled
  ticks without repeated snapshots or resampling, float32 input identity, full
  rollback, snapshot and total-history rejection, correction-growth recovery,
  save/step/hash exceptions, late/early/conflicting hashes, bounded catchup/hash
  work, infinite input generators, callback stop/close/reentry, and stop/lifetime.

Artifacts under `.project/optimization/benchmarks/`:

- `python-logic-windows-20260909-e/report.json`:
  `1d1cf2a2121451e013f7f3cef8dc63cfa9e17459dd6ef81cfe1c4b3a84117d24`
- Its captured `tests.log`:
  `96be238bba113975152c0bfab8712405aaeb8f49ba55ea871e2c4c4c622ce133`
- `python-logic-evidence-20260909.json`:
  `77b6baeb8febba9f60c3668794a16c4466f4ea8de9cb4ddac5b5261425bba2ad`

The manifest preserves all five runs, including the failed `d` result. That test
reproduced the missing application retry: with early frame 1/2 discarded, the
client remained at confirmed frame 0 instead of reaching 2. Run `e` passes with
the unchanged 1.5-second test deadline and exact input identity checks. Runs
`a/b/c` passed 55/58/59 tests before this compatibility case was added. Reruns are
not counted as distinct coverage.

All latest report source hashes (11 files), five report/log hashes and changed-source
whitespace were verified. The earlier TCP-only 32-test artifact is historical after
the explicit-entry API/logic edits; the latest 61-test result contains its current
regression coverage. Index metadata reported no recorded issue for the operated
code paths; graph coverage remains best effort and direct source is authoritative.

## Environment and remaining acceptance

Tests ran on Windows 11 build 26200, CPython 3.14.6, through the existing UNC
workspace. No dependencies were installed. The deterministic test engine is not
GameEnv, and the scripted real sockets are not a deployed game server, WAN fault
test or latency benchmark. The new logic API has not been demonstrated in a native
GameEnv entrypoint in this run.

A fresh, uniquely tagged direct WSL `/usr/bin/true` launch exceeded 12 seconds.
Only the owned probe process was stopped; its child lookup found no matching
remaining process. No distro/VM/service was reset. The earlier Windows formal
validator explicitly rejected this platform because Windows Git misreports the
workspace. That guard was not bypassed. No current Linux formal acceptance,
GameEnv, C++ compiler, sanitizer, rendering or performance run is claimed here.

Next within task-21.1.2.1: bound the Python presentation holder and trace/dump/output
paths, then Python servers/UDP/reconnect lifecycle and actual maximum-length replay
persistence. Restore native validation when Linux execution is available; only then
connect and satisfy the full memory gate. The later long-growth/performance, feel,
network, rendering, AI and release gates remain required. Existing immutable
benchmark archives and C++ binaries were not changed by this Python work.
