# Copyright 2026 Google LLC
# 2026-09-09: bounded whole-frame prediction and authority reconciliation.
"""Single-owner logic; the TCP transports own their concurrent receive queues.

Snapshots and canonical digests must be immutable bytes or strings. Limits
charge their actual Python object size, not just serialized length. The engine
allocates a serialization before its size can be inspected: these are retained
history limits, not an allocator, process RSS or presentation-store limit.
"""
from gfootball.frame_sync.frame_pacing import FramePacer
import collections
from dataclasses import dataclass
import itertools
import math
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.match_lifecycle import match_finished
from gfootball.frame_sync.match_control import MatchControl, RUNNING


@dataclass(frozen=True)
class LogicLimits:
  prediction_frames: int = wire.MAX_PREDICT_AHEAD_FRAMES
  snapshot_bytes: int = 1024 * 1024
  history_bytes: int = 8 * 1024 * 1024
  digest_bytes: int = 1024 * 1024
  hash_frames: int = 1024
  catchup_frames: int = 8
  hashes_per_tick: int = 64
  input_retry_seconds: float = 0.1

  def __post_init__(self):
    for name, minimum, maximum in (
        ('prediction_frames', 0, 8), ('snapshot_bytes', 64, 1024 * 1024),
        ('history_bytes', 64, 8 * 1024 * 1024), ('digest_bytes', 64, 1024 * 1024),
        ('hash_frames', 1, 1024), ('catchup_frames', 1, 32), ('hashes_per_tick', 1, 1024)):
      value = getattr(self, name)
      if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid logic limit: ' + name)
    if (type(self.input_retry_seconds) not in (int, float) or
        not math.isfinite(self.input_retry_seconds) or not 0.01 <= self.input_retry_seconds <= 1):
      raise ValueError('Invalid input retry interval')


@dataclass
class _Prediction:
  before: object
  inputs: bytes
  digest: int = 0

  @property
  def retained_bytes(self):
    return sys.getsizeof(self.before) + sys.getsizeof(self.inputs)


class ClientLogicLoop:
  """Execute authority in order and replay every affected speculative frame.

  current_frame_id is the NEXT frame to execute; confirmed_frame_id is the last
  executed authoritative frame (-1 initially). Prediction depth is their
  difference minus one. Input is sampled once per new frame and the same
  float32 bytes go to the transport and prediction. Use a transport providing
  send_frame_entries; the synchronous and asynchronous TCP clients provide it.
  Existing servers discard future input, so the oldest unconfirmed sampled
  input is retried unchanged at most once per input_retry_seconds (default .1s).

  All engine operations and run_one_tick calls belong to one logic thread.
  stop() may be called from another thread and interrupts run_loop's wait.
  A failed/stopped loop cannot resume a different session implicitly.
  """
  # 2026-09-09: monotonic retry clock is injectable for deterministic tests.
  # def __init__(self, client, env, num_slots, controlled_slots_callback,
  #              rate_hz=10, state_holder=None, *, limits=None):
  # 2026-09-10: a restored snapshot starts BEFORE its supplied next frame.
  # def __init__(self, client, env, num_slots, controlled_slots_callback,
  #              rate_hz=10, state_holder=None, *, limits=None, clock=None):
  # 2026-09-10: negotiated control barriers notify the input owner before ACK.
  # def __init__(self, client, env, num_slots, controlled_slots_callback,
  #              rate_hz=10, state_holder=None, *, limits=None, clock=None, initial_frame_id=0):
  def __init__(self, client, env, num_slots, controlled_slots_callback,
               rate_hz=10, state_holder=None, *, limits=None, clock=None, initial_frame_id=0,
               on_control=None):
    if type(initial_frame_id) is not int or not 0 <= initial_frame_id <= 0xfffffff7:
      raise ValueError('Invalid initial logic frame')
    if type(num_slots) is not int or not 1 <= num_slots <= 22:
      raise ValueError('Expected 1..22 controlled slots')
    if type(rate_hz) not in (int, float) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
      raise ValueError('Invalid logic rate')
    if not callable(controlled_slots_callback):
      raise ValueError('Input callback must be callable')
    if limits is not None and not isinstance(limits, LogicLimits):
      raise ValueError('Expected LogicLimits')
    for name in ('get_state', 'set_state', 'step_with_input', 'get_state_digest'):
      if not callable(getattr(env, name, None)):
        raise ValueError('Engine must implement ' + name)
    if not callable(getattr(client, 'send_frame_entries', None)):
      raise ValueError('Transport must implement send_frame_entries')
    if state_holder is not None and not callable(getattr(state_holder, 'write', None)):
      raise ValueError('State holder must implement write')
    if clock is not None and not callable(clock):
      raise ValueError('Clock must be callable')
    if on_control is not None and not callable(on_control):
      raise ValueError('Control callback must be callable')
    self._on_control = on_control
    self._control = self._pending_control = self._control_reader = None
    self._control_dirty = False
    self._clock = clock or time.monotonic
    self._client, self._env, self._num_slots = client, env, num_slots
    self._controlled_slots_callback = controlled_slots_callback
    self._rate_hz, self._state_holder = rate_hz, state_holder
    self.limits = limits or LogicLimits()
    # 2026-09-10: prior frames are represented by the restored engine state.
    # self._current_frame_id = 0
    # self._last_confirmed_frame_id = -1
    self._current_frame_id = initial_frame_id
    self._last_confirmed_frame_id = initial_frame_id - 1
    self._last_auth_inputs = b''.join(wire.pack_slot_input(wire.default_slot_input()) for _ in range(num_slots))
    self._history = collections.OrderedDict()
    self._history_bytes = 0
    self._confirmed_hashes = collections.OrderedDict()
    self._pending_hashes = {}
    self._sent_frame = None
    self._sent_entries = ()
    # Retain at most eight speculative inputs plus one waiting input. A memory
    # fallback may rewind the next frame, but must not resample an input already
    # accepted by the wire for that frame.
    self._sampled_inputs = {}
    self._input_sent_at = {}
    self._input_retries = 0
    self._rollback_count = 0
    self._published_rollback_count = 0
    self._verified_hashes = 0
    self._frames_without_packet = 0
    self._only_authority_mode = False
    self._prediction_limited = False
    self._failure = None
    self._running = False
    self._stop_event = threading.Event()
    self._tick_lock = threading.Lock()
    self._loop_lock = threading.Lock()

  def get_last_confirmed_frame_id(self):
    return self._last_confirmed_frame_id

  def get_current_frame_id(self):
    return self._current_frame_id

  def get_rollback_count(self):
    return self._rollback_count

  @property
  def control_state(self):
    """Last applied immutable control state; None for an unnegotiated session."""
    return self._control

  def initialize_control(self, control):
    # 2026-09-10: v6 transports now activate the previously isolated primitives.
    # The v5 match adapters do not enable this opt-in v6 execution contract.
    # 2026-09-10: latest-only delivery could skip a commit before another pause.
    # Only the logic owner calls this. The transport supplies one immutable latest
    # control state and queues ACKs; its IO worker never accesses the engine.
    """Bind a negotiated origin BEFORE sampling or predicting in this session.

    Only the logic owner calls this. get_match_control returns the first
    unapplied control (or last applied when empty), not the newest received one.
    acknowledge_control queues a wire ACK and consumes that pause/preparation;
    commit_control consumes a RUNNING commit locally, without a wire ACK.
    The bounded transport retains at most one commit plus one unacknowledged
    barrier. Its IO worker never accesses the engine.
    The v6 match adapters enable this contract; generic clients leave it unset.
    """
    if type(control) is not MatchControl:
      raise ValueError('Expected MatchControl')
    reader = getattr(self._client, 'get_match_control', None)
    acknowledge = getattr(self._client, 'acknowledge_control', None)
    # 2026-09-10: explicitly consume commits so a fast re-pause cannot erase one.
    # if not callable(reader) or not callable(acknowledge):
    commit = getattr(self._client, 'commit_control', None)
    if not callable(reader) or not callable(acknowledge) or not callable(commit):
      raise ValueError('Transport must implement match control barriers')
    if not self._tick_lock.acquire(blocking=False):
      raise RuntimeError('Concurrent or reentrant control initialization')
    try:
      if (self._control is not None or self._stop_event.is_set() or self._failure
          or self._history or self._sampled_inputs or self._confirmed_hashes
          or self._current_frame_id != self._last_confirmed_frame_id + 1):
        raise ClientFailure('control_initialization_order')
      if control.next_frame != self._current_frame_id or self._hash() != control.state_hash:
        raise ClientFailure('control_origin_mismatch')
      self._notify_control(control)
      self._control, self._control_reader = control, reader
      self._control_dirty = True
    except Exception as error:
      self._terminate(error.reason if isinstance(error, ClientFailure) else 'control_error')
      raise
    finally:
      self._tick_lock.release()

  def _notify_control(self, control):
    if self._on_control is not None:
      self._on_control(control)
    # 2026-09-10: transport EOF during a barrier remains retryable network loss.
    # if self._stop_event.is_set() or self._client.is_disconnected():
    if self._stop_event.is_set():
      raise ClientFailure('stopped_during_control')
    if self._client.is_disconnected():
      raise ClientFailure(self._client.failure_reason or 'disconnected')

  def _control_blocks_input(self):
    return self._pending_control is not None or (self._control is not None and self._control.phase != RUNNING)

  def _poll_control(self):
    if self._control_reader is None:
      return False
    if self._client.is_disconnected():
      return False  # failure cleanup has released the transport's control queue
    control = self._control_reader()
    if type(control) is not MatchControl:
      if self._client.is_disconnected():
        return False  # IO can close after the check preceding the locked read
      raise ClientFailure('invalid_control')
    if self._pending_control is not None:
      if control != self._pending_control:
        raise ClientFailure('control_before_ack')
      return False
    try:
      changed = control.validate_after(self._control)
    except ValueError as error:
      raise ClientFailure('invalid_control_sequence') from error
    if not changed:
      return False
    if control.next_frame < self._last_confirmed_frame_id + 1:
      raise ClientFailure('control_behind_authority')
    self._pending_control, self._control_dirty = control, True
    # Pause input immediately, even when bounded catch-up requires more ticks.
    # A RUNNING commit only unfreezes after the boundary hash is checked below.
    if control.phase != RUNNING:
      self._notify_control(control)
    return True

  def _apply_pending_control(self):
    control = self._pending_control
    if control is None or self._last_confirmed_frame_id + 1 < control.next_frame:
      return False
    if self._last_confirmed_frame_id + 1 != control.next_frame or self._current_frame_id < control.next_frame:
      raise ClientFailure('control_boundary_mismatch')
    if self._current_frame_id > control.next_frame:
      prediction = self._history.get(control.next_frame)
      if prediction is None:
        raise ClientFailure('missing_control_snapshot')
      self._env.set_state(prediction.before)
      self._current_frame_id = control.next_frame
      self._rollback_count += 1
    if self._hash() != control.state_hash:
      raise ClientFailure('control_hash_mismatch')
    self._clear_history()
    self._sampled_inputs.clear()
    self._input_sent_at.clear()
    self._sent_frame, self._sent_entries = None, ()
    self._last_auth_inputs = b''.join(wire.pack_slot_input(wire.default_slot_input()) for _ in range(self._num_slots))
    # Confirmed hashes remain bounded and available for delayed hash drains.
    self._control, self._pending_control = control, None
    if control.phase == RUNNING:
      self._notify_control(control)
      if not self._client.commit_control(control):
        # 2026-09-10: do not replace a retryable transport failure with a protocol error.
        # raise ClientFailure('control_commit_rejected')
        raise ClientFailure(self._client.failure_reason or 'control_commit_rejected')
      self._frames_without_packet = 0
      self._only_authority_mode = self._prediction_limited = False
    else:
      # if self._stop_event.is_set() or self._client.is_disconnected():
      if self._stop_event.is_set():
        raise ClientFailure('stopped_during_control')
      if self._client.is_disconnected():
        raise ClientFailure(self._client.failure_reason or 'disconnected')
      if not self._client.acknowledge_control(control):
        # raise ClientFailure('control_ack_rejected')
        raise ClientFailure(self._client.failure_reason or 'control_ack_rejected')
    return True

  @property
  def failure_reason(self):
    return self._failure

  @property
  def _adaptive_predict_cap(self):
    rtt = self._client.get_avg_rtt_ms()
    if not math.isfinite(rtt) or rtt < 0:
      raise ClientFailure('invalid_timing')
    cap = 1 if rtt > 100 else 2 if rtt > 50 else 8
    return min(self.limits.prediction_frames, cap)

  def is_waiting_for_authority(self):
    # 2026-09-10: a speculative end awaits authority and remains rollbackable.
    # Stopped/failed logic may no longer inspect its released engine.
    if self._failure is not None or self._stop_event.is_set():
      return True
    if self._control_blocks_input():
      return True
    if match_finished(self._env):
      return True
    return (self._failure is not None or self._stop_event.is_set() or
            self._only_authority_mode or self._prediction_limited or
            self._current_frame_id - self._last_confirmed_frame_id - 1 >= self._adaptive_predict_cap)

  def stats(self):
    return dict(history_frames=len(self._history), history_bytes=self._history_bytes,
                confirmed_hashes=len(self._confirmed_hashes), pending_hashes=len(self._pending_hashes),
                sampled_input_frames=len(self._sampled_inputs),
                input_timestamps=len(self._input_sent_at), input_retries=self._input_retries,
                verified_hashes=self._verified_hashes, rollbacks=self._rollback_count,
                prediction_limited=self._prediction_limited)

  def _clear_history(self):
    self._history.clear()
    self._history_bytes = 0

  def _release_stopped_buffers(self):
    """Called with the tick lock; does not touch caller-owned engine state."""
    self._clear_history()
    self._confirmed_hashes.clear()
    self._pending_hashes.clear()
    self._sent_entries = ()
    self._sampled_inputs.clear()
    self._input_sent_at.clear()
    self._pending_control = None

  def _terminate(self, reason):
    if self._failure is None:
      self._failure = reason
    self._running = False
    self._only_authority_mode = True
    self._stop_event.set()
    self._clear_history()
    self._confirmed_hashes.clear()
    self._pending_hashes.clear()
    self._sent_entries = ()
    self._sampled_inputs.clear()
    self._input_sent_at.clear()
    self._client.close()

  @staticmethod
  def _immutable_size(value):
    if type(value) not in (bytes, str):
      raise ClientFailure('invalid_engine_state')
    return sys.getsizeof(value)

  def _hash(self):
    digest = self._env.get_state_digest()
    if self._immutable_size(digest) > self.limits.digest_bytes:
      raise ClientFailure('digest_capacity')
    return wire.compute_state_hash(digest)

  def _frame_bytes(self, inputs):
    values = list(itertools.islice(iter(inputs), 23))
    if len(values) != self._num_slots or not all(wire.is_valid_slot_input(value) for value in values):
      raise ClientFailure('invalid_authority')
    return b''.join(wire.pack_slot_input(value) for value in values)

  def _fits(self, before, inputs, retained):
    state_bytes = self._immutable_size(before)
    return (state_bytes <= self.limits.snapshot_bytes and
            state_bytes + sys.getsizeof(inputs) <= self.limits.history_bytes - retained)

  def _verify(self, frame, expected):
    actual = self._confirmed_hashes.get(frame)
    if actual is None:
      raise ClientFailure('hash_outside_window')
    if actual != expected:
      raise ClientFailure('hash_mismatch')
    self._verified_hashes += 1

  # 2026-09-09: share one per-tick allowance across the before/after drains.
  # def _drain_hashes(self):
  #   for _ in range(self.limits.hashes_per_tick):
  def _drain_hashes(self, allowance):
    consumed = 0
    for _ in range(allowance):
      message = self._client.pop_state_hash()
      if message is None:
        break
      consumed += 1
      frame, digest = message
      if (type(frame) is not int or not 0 <= frame <= 0xfffffff7 or
          type(digest) is not int or not 0 <= digest <= 0xffffffffffffffff):
        raise ClientFailure('invalid_hash')
      if frame <= self._last_confirmed_frame_id:
        self._verify(frame, digest)
      else:
        if frame - self._last_confirmed_frame_id - 1 >= self.limits.hash_frames:
          raise ClientFailure('hash_outside_window')
        previous = self._pending_hashes.get(frame)
        if previous is not None and previous != digest:
          raise ClientFailure('invalid_hash')
        if previous is None and len(self._pending_hashes) >= self.limits.hash_frames:
          raise ClientFailure('hash_capacity')
        self._pending_hashes[frame] = digest
    return consumed

  def _recover_correction(self, frame, before, inputs):
    self._env.set_state(before)
    self._env.step_with_input(inputs)
    digest = self._hash()
    self._clear_history()
    self._current_frame_id = frame + 1
    self._sent_frame = None
    self._sent_entries = ()
    return digest

  def _confirm(self, frame, inputs):
    if type(frame) is not int or frame != self._last_confirmed_frame_id + 1 or frame > 0xfffffff7:
      raise ClientFailure('authority_out_of_order')
    barrier = self._pending_control or (self._control if self._control_blocks_input() else None)
    if barrier is not None and frame >= barrier.next_frame:
      raise ClientFailure('authority_past_control')
    packed = self._frame_bytes(inputs)
    predicted = self._history.get(frame)
    if predicted is None:
      if frame != self._current_frame_id:
        raise ClientFailure('missing_prediction_history')
      self._env.step_with_input(packed)
      digest = self._hash()
      self._current_frame_id += 1
    elif predicted.inputs == packed:
      digest = predicted.digest
    else:
      # Keep the root snapshot until the corrected frame commits. If replay
      # grows beyond budget, discard speculation at this authoritative boundary.
      self._env.set_state(predicted.before)
      # 2026-09-09: a failed root step/hash must not leave a partially mutated
      # speculative engine available to its owner after the terminal exception.
      # self._env.step_with_input(packed)
      # digest = self._hash()
      try:
        self._env.step_with_input(packed)
        digest = self._hash()
      except Exception:
        self._env.set_state(predicted.before)
        raise
      try:
        for later, record in list(self._history.items()):
          if later <= frame:
            continue
          if match_finished(self._env):
            # A correction can end earlier than the old speculative timeline.
            for discarded in list(self._history):
              if discarded >= later:
                self._history_bytes -= self._history.pop(discarded).retained_bytes
            for discarded in list(self._sampled_inputs):
              if discarded >= later:
                self._sampled_inputs.pop(discarded)
                self._input_sent_at.pop(discarded, None)
            self._current_frame_id = later
            self._sent_frame, self._sent_entries = None, ()
            break
          before = self._env.get_state('')
          retained = self._history_bytes - record.retained_bytes
          if not self._fits(before, record.inputs, retained):
            digest = self._recover_correction(frame, predicted.before, packed)
            self._prediction_limited = True
            break
          self._history_bytes = retained
          record.before = before
          self._history_bytes += record.retained_bytes
          self._env.step_with_input(record.inputs)
          record.digest = self._hash()
      except Exception:
        self._recover_correction(frame, predicted.before, packed)
        raise
      self._rollback_count += 1
    old = self._history.pop(frame, None)
    if old is not None:
      self._history_bytes -= old.retained_bytes
    self._last_auth_inputs = packed
    self._last_confirmed_frame_id = frame
    self._sampled_inputs.pop(frame, None)
    self._input_sent_at.pop(frame, None)
    self._confirmed_hashes[frame] = digest
    while len(self._confirmed_hashes) > self.limits.hash_frames:
      self._confirmed_hashes.popitem(last=False)
    expected = self._pending_hashes.pop(frame, None)
    if expected is not None:
      self._verify(frame, expected)

  def _input_time(self):
    now = self._clock()
    if type(now) not in (int, float) or not math.isfinite(now):
      raise ClientFailure('invalid_clock')
    return now

  def _resend_unconfirmed(self):
    self._poll_control()
    if self._control_blocks_input():
      return
    frame = self._last_confirmed_frame_id + 1
    entries = self._sampled_inputs.get(frame)
    if entries is None:
      return
    now = self._input_time()
    if now - self._input_sent_at[frame] < self.limits.input_retry_seconds:
      return
    # 2026-09-10: a control arrival may close transport admission during send.
    # if not self._client.send_frame_entries(frame, entries):
    #   raise ClientFailure(self._client.failure_reason or 'input_rejected')
    if not self._client.send_frame_entries(frame, entries):
      self._poll_control()
      if self._control_blocks_input():
        return
      raise ClientFailure(self._client.failure_reason or 'input_rejected')
    self._input_sent_at[frame] = now
    self._input_retries += 1

  def _sample_and_send(self):
    self._poll_control()
    # 2026-09-10: do not consume a UI edge after IO closed during control polling.
    # if self._control_blocks_input():
    if self._control_blocks_input() or self._client.is_disconnected():
      return False
    if self._current_frame_id in self._sampled_inputs:
      self._sent_frame = self._current_frame_id
      self._sent_entries = self._sampled_inputs[self._current_frame_id]
      return True
    entries = list(itertools.islice(iter(self._controlled_slots_callback()), 23))
    # A pause observed while the input owner runs invalidates these unsent edges.
    self._poll_control()
    if self._control_blocks_input():
      return False
    if self._stop_event.is_set() or self._client.is_disconnected():
      return False
    slots = set()
    canonical = []
    for slot, value in entries:
      if (type(slot) is not int or not 0 <= slot < self._num_slots or slot in slots or
          not wire.is_valid_slot_input(value)):
        raise ClientFailure('invalid_input')
      slots.add(slot)
      canonical.append((slot, wire.unpack_slot_input(wire.pack_slot_input(value))[0]))
    if not canonical:
      return False
    if len(self._sampled_inputs) >= 9:
      raise ClientFailure('sampled_input_capacity')
    if not self._client.send_frame_entries(self._current_frame_id, canonical):
      self._poll_control()
      if self._control_blocks_input():
        return False
      if self._client.is_disconnected():
        return False
      raise ClientFailure('input_rejected')
    self._sent_frame, self._sent_entries = self._current_frame_id, tuple(canonical)
    self._sampled_inputs[self._current_frame_id] = self._sent_entries
    self._input_sent_at[self._current_frame_id] = self._input_time()
    return True

  def _predict(self):
    inputs = bytearray(self._last_auth_inputs)
    for slot, value in self._sent_entries:
      offset = slot * wire.SLOT_INPUT_BYTES
      inputs[offset:offset + wire.SLOT_INPUT_BYTES] = wire.pack_slot_input(value)
    inputs = bytes(inputs)
    before = self._env.get_state('')
    if not self._fits(before, inputs, self._history_bytes):
      self._prediction_limited = True
      return False
    record = _Prediction(before, inputs)
    self._history[self._current_frame_id] = record
    self._history_bytes += record.retained_bytes
    try:
      self._env.step_with_input(inputs)
      record.digest = self._hash()
    except Exception:
      self._env.set_state(before)
      raise
    self._current_frame_id += 1
    return True

  def _publish(self):
    if self._state_holder is not None:
      state = self._env.get_state('')
      if self._immutable_size(state) > self.limits.snapshot_bytes:
        raise ClientFailure('presentation_state_capacity')
      # 2026-09-09: a replay can correct state while the displayed frame ID
      # keeps increasing. Explicitly invalidate presentation history in that case.
      # self._state_holder.write(state, self._current_frame_id - 1, self._last_confirmed_frame_id,
      #                          waiting_for_authority=self.is_waiting_for_authority())
      self._state_holder.write(state, self._current_frame_id - 1, self._last_confirmed_frame_id,
                               waiting_for_authority=self.is_waiting_for_authority(),
                               discontinuity=self._rollback_count != self._published_rollback_count)
      self._published_rollback_count = self._rollback_count

  # 2026-09-10: lobbies still process controls and send immutable frame-zero input.
  # def run_one_tick(self):
  def run_one_tick(self, *, allow_prediction=True):
    if type(allow_prediction) is not bool:
      raise ValueError('Prediction admission must be boolean')
    if not self._tick_lock.acquire(blocking=False):
      raise RuntimeError('Concurrent or reentrant logic tick')
    try:
      if self._stop_event.is_set():
        self._clear_history()
        self._sent_entries = ()
        self._sampled_inputs.clear()
        self._input_sent_at.clear()
        return
      self._client.tick_disconnect_detection()
      if self._client.is_disconnected():
        self._terminate(self._client.failure_reason or 'disconnected')
        return
      self._poll_control()
      # A commit and its first authority can arrive in the same receive batch.
      # Apply the already-confirmed boundary before draining that authority.
      self._apply_pending_control()
      # 2026-09-09: two drains must not double hashes_per_tick.
      # self._drain_hashes()
      hashes_used = self._drain_hashes(self.limits.hashes_per_tick)
      confirmed = 0
      for _ in range(self.limits.catchup_frames):
        if self._stop_event.is_set() or self._client.is_disconnected():
          self._terminate(self._client.failure_reason or 'stopped')
          return
        auth = self._client.pop_authoritative_frame()
        if auth is None:
          break
        self._poll_control()
        self._apply_pending_control()
        self._prediction_limited = False
        self._confirm(*auth)
        confirmed += 1
      self._frames_without_packet = 0 if confirmed else min(
          self._frames_without_packet + 1, wire.MAX_FRAMES_WITHOUT_PACKET)
      self._only_authority_mode = self._frames_without_packet >= wire.MAX_FRAMES_WITHOUT_PACKET
      # self._drain_hashes()
      self._drain_hashes(self.limits.hashes_per_tick - hashes_used)
      # 2026-09-10: quiesce at the verified boundary before admitting new input.
      # changed = bool(confirmed)
      # if not self._client.has_authoritative_frame():
      changed = self._apply_pending_control() or bool(confirmed)
      if not self._control_blocks_input() and not self._client.has_authoritative_frame():
        self._resend_unconfirmed()
        # 2026-09-10: keep retrying pre-end inputs but do not sample beyond end.
        # sent = self._sample_and_send()
        sent = False if match_finished(self._env) else self._sample_and_send()
        if self._stop_event.is_set() or self._client.is_disconnected():
          self._terminate(self._client.failure_reason or 'stopped')
          return
        # 2026-09-10: control may arrive after send but before prediction.
        # if sent and not self.is_waiting_for_authority():
        self._poll_control()
        # 2026-09-10: a ready lobby is not permission to simulate the first frame.
        # if sent and not self.is_waiting_for_authority():
        if allow_prediction and sent and not self.is_waiting_for_authority():
          changed = self._predict() or changed
      # 2026-09-10: late control arrivals in a send callback also settle this tick.
      # if changed:
      changed = self._apply_pending_control() or changed
      if changed or self._control_dirty:
        self._publish()
        self._control_dirty = False
    except Exception as error:
      self._terminate(error.reason if isinstance(error, ClientFailure) else 'logic_error')
      raise
    finally:
      # 2026-09-10: stop during an input/engine callback refunds on its exit.
      if self._stop_event.is_set():
        self._release_stopped_buffers()
      self._tick_lock.release()

  def finish_at(self, next_frame, expected_hash):
    """Reconcile the terminal authority and discard prediction beyond its end."""
    if (type(next_frame) is not int or not 0 <= next_frame <= 0xfffffff7
        # 2026-09-10: StateHash carries uint64, not uint32.
        # or type(expected_hash) is not int or not 0 <= expected_hash <= 0xffffffff):
        or type(expected_hash) is not int or not 0 <= expected_hash <= 0xffffffffffffffff):
      raise ValueError('Invalid match end')
    if not self._tick_lock.acquire(blocking=False):
      raise RuntimeError('Concurrent or reentrant logic finish')
    try:
      if self._failure or self._last_confirmed_frame_id != next_frame - 1 or self._current_frame_id < next_frame:
        raise ClientFailure('finish_before_authority')
      if self._current_frame_id > next_frame:
        prediction = self._history.get(next_frame)
        if prediction is None:
          raise ClientFailure('missing_finish_snapshot')
        self._env.set_state(prediction.before)
        self._current_frame_id = next_frame
      if self._hash() != expected_hash:
        raise ClientFailure('match_end_hash')
      self._running = False
      self._stop_event.set()
      self._release_stopped_buffers()
    except Exception as error:
      self._terminate(error.reason if isinstance(error, ClientFailure) else 'finish_error')
      raise
    finally:
      self._tick_lock.release()

  def run_loop(self):
    # 2026-09-09: an atomic lifetime guard also covers stop during a callback.
    # if self._running:
    if not self._loop_lock.acquire(blocking=False):
      raise RuntimeError('Logic loop is already running')
    if self._tick_lock.locked():
      self._loop_lock.release()
      raise RuntimeError('Cannot start logic loop during an active tick')
    self._running = True
    # 2026-09-10: absolute pacing discards wall-clock debt without extra prediction ticks.
    # period = 1.0 / self._rate_hz
    # try:
    #   while not self._stop_event.is_set():
    #     start = time.monotonic()
    #     self.run_one_tick()
    #     self._stop_event.wait(max(0.0, period - (time.monotonic() - start)))
    # 2026-09-10: scheduler allocation failure also releases the loop guard.
    # pacer = FramePacer(self._rate_hz)
    try:
      pacer = FramePacer(self._rate_hz)
      while not self._stop_event.is_set() and pacer.wait_next(self._stop_event.wait):
        self.run_one_tick()
    finally:
      self._running = False
      # 2026-09-09: never clear state while a separately dispatched tick owns it.
      # self._clear_history()
      # self._sent_entries = ()
      # self._sampled_inputs.clear()
      with self._tick_lock:
        self._clear_history()
        self._sent_entries = ()
        self._sampled_inputs.clear()
        self._input_sent_at.clear()
      self._loop_lock.release()

  def stop(self):
    self._running = False
    self._stop_event.set()
    # 2026-09-10: manually driven loops may never receive another tick after
    # close. Release immediately when idle; active work releases in finally.
    if self._tick_lock.acquire(blocking=False):
      try:
        self._release_stopped_buffers()
      finally:
        self._tick_lock.release()
