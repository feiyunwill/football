# Copyright 2026 Google LLC
# 2026-09-10: one bounded background attempt owner; restore on the logic thread.
from dataclasses import dataclass
import math
import sys
import threading
import time

from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.client_logic import ClientLogicLoop
from gfootball.frame_sync.client_tcp import FrameSyncClient
from gfootball.frame_sync.resume_protocol import validate_token


@dataclass(frozen=True)
class ReconnectLimits:
  base_seconds: float = 1.0
  max_seconds: float = 30.0
  recovery_seconds: float = 60.0
  max_attempts: int = 10

  def __post_init__(self):
    for name, low, high in (('base_seconds', .01, 30), ('max_seconds', .01, 30),
                            ('recovery_seconds', .05, 300)):
      value = getattr(self, name)
      if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid reconnect limit: ' + name)
    if self.base_seconds > self.max_seconds:
      raise ValueError('Reconnect base exceeds maximum delay')
    if type(self.max_attempts) is not int or not 0 <= self.max_attempts <= 1000:
      raise ValueError('Invalid reconnect attempt limit')


_RETRYABLE = frozenset(('closed', 'eof', 'io_error', 'connect_failed', 'connect_timeout',
                        'handshake_timeout', 'idle_timeout', 'write_timeout'))


class ReconnectingFrameSyncClient:
  """Automatic TCP capability/snapshot/Ready recovery for an attached logic loop.

  connect() establishes an initial session. Initialize the caller-owned engine,
  attach_logic(env), then run_one_tick() from that engine's owner thread. Only
  network IO/retries run on the background worker. tick() never connects, joins
  an attempt or sleeps; a completed snapshot is restored on its calling thread.
  Engine restore itself cannot be forcibly interrupted or made hard real-time.

  Default v3 obtains a random token through the wire. Legacy native mode needs
  the actual original token supplied by its host; it never guesses a token or
  substitutes a fresh session for a failed resume. close() is terminal.
  """
  # 2026-09-10: transport subclasses share the same lifecycle with explicit failure policy.
  _retryable = _RETRYABLE
  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None,
               resume_limits=None, reconnect_limits=None, handshake='versioned', session_token=None):
    if reconnect_limits is not None and not isinstance(reconnect_limits, ReconnectLimits):
      raise ValueError('Expected ReconnectLimits')
    if session_token is not None:
      validate_token(session_token)
    self.host, self.port = host, port
    self.controlled_slots_callback = controlled_slots_callback
    self.reconnect_limits = reconnect_limits or ReconnectLimits()
    self._client_options = dict(limits=limits, resume_limits=resume_limits, handshake=handshake,
                                enable_resume=handshake == 'versioned' and session_token is None)
    self._client = self._new_client()
    self._condition = threading.Condition(threading.RLock())
    self._tick_guard = threading.Lock()
    self._worker = None
    self._owner_thread = None
    self._state = 'new'
    self._candidate = None
    self._pending = None
    self._active_snapshot = None
    self._session = self._slots = None
    self._token = session_token
    self._attempts = self._total_attempts = self._restores = 0
    self._next_attempt = self._recovery_deadline = 0.0
    self._delay = self.reconnect_limits.base_seconds
    self._failure = self._last_error = None
    self._disconnect_notice = self._give_up_notice = False
    self._on_reconnect = self._on_disconnect = self._on_give_up = None
    self._env = self._logic = self._logic_options = None

  def _new_client(self):
    return FrameSyncClient(self.host, self.port, self.controlled_slots_callback, **self._client_options)

  def _owner(self):
    current = threading.current_thread()
    if self._owner_thread is None:
      self._owner_thread = current
    elif self._owner_thread is not current:
      raise RuntimeError('Reconnect callbacks and engine operations belong to the logic owner thread')

  def _callback(self, name, callback):
    if callback is not None and not callable(callback):
      raise ValueError('Expected a callback or None')
    with self._condition:
      setattr(self, name, callback)

  def set_on_reconnect(self, callback):
    self._callback('_on_reconnect', callback)

  def set_on_disconnect(self, callback):
    self._callback('_on_disconnect', callback)

  def set_on_give_up(self, callback):
    self._callback('_on_give_up', callback)

  def set_session_token(self, token):
    """Bind the actual host-issued capability for legacy initial handshakes."""
    validate_token(token)
    with self._condition:
      if self._state != 'connected':
        raise RuntimeError('Bind a token while the original session is connected')
      self._token = token

  def connect(self):
    self._owner()
    with self._condition:
      if self._state != 'new':
        raise ClientFailure('reconnect_already_started')
      self._state = 'connecting'
    try:
      session, slots = self._client.connect()
      with self._condition:
        if self._state == 'closed':
          raise ClientFailure('closed')
        self._session, self._slots = session, tuple(slots)
        self._token = self._client.session_token or self._token
        self._state = 'connected'
        self._worker = threading.Thread(target=self._work, name='football-reconnect-owner')
        self._worker.start()
      return session, slots
    except BaseException:
      self.close()
      raise

  def attach_logic(self, env, *, rate_hz=10, state_holder=None, limits=None):
    self._owner()
    with self._condition:
      if self._state != 'connected' or self._logic is not None:
        raise RuntimeError('Attach one initialized engine after the initial connect')
      options = dict(rate_hz=rate_hz, state_holder=state_holder, limits=limits)
      # 2026-09-10: protocol subclasses initialize negotiated controls before Ready.
      # loop = ClientLogicLoop(self._client, env, self._session[1] + self._session[2],
      #                        self.controlled_slots_callback or (lambda: []), **options)
      loop = self._make_logic(self._client, env, options)
      if not self._client.send_ready():
        raise ClientFailure(self._client.failure_reason or 'ready_failed')
      self._env, self._logic, self._logic_options = env, loop, options
      return loop

  def _make_logic(self, client, env, options, initial_frame_id=0):
    return ClientLogicLoop(client, env, self._session[1] + self._session[2],
        self.controlled_slots_callback or (lambda: []), initial_frame_id=initial_frame_id, **options)

  def _give_up_locked(self, reason):
    # 2026-09-10: even a throwing give-up callback must not rearm itself.
    # if self._state == 'closed':
    if self._state in ('closed', 'gave_up'):
      return
    self._state, self._failure = 'gave_up', reason
    self._give_up_notice = True
    self._pending = None
    self._condition.notify_all()

  def _retry_locked(self, reason, now):
    self._last_error = reason
    # if reason not in _RETRYABLE:
    if reason not in self._retryable:
      self._give_up_locked(reason)
    elif now >= self._recovery_deadline:
      self._give_up_locked('recovery_timeout')
    elif self.reconnect_limits.max_attempts and self._attempts >= self.reconnect_limits.max_attempts:
      self._give_up_locked('reconnect_exhausted')
    else:
      self._state = 'backoff'
      self._next_attempt = now + self._delay
      self._delay = min(self.reconnect_limits.max_seconds, self._delay * 2)

  def _work(self):
    try:
      while True:
        close_client = None
        attempt = False
        with self._condition:
          now = time.monotonic()
          if self._state in ('closed', 'gave_up'):
            return
          if self._state == 'connected' and self._client.is_disconnected():
            # 2026-09-10: logic failures close a transport but aren't network loss.
            # reason = self._client.failure_reason or 'io_error'
            reason = (self._logic.failure_reason if self._logic is not None else None) or self._client.failure_reason or 'io_error'
            self._disconnect_notice = True
            self._attempts = 0
            self._delay = self.reconnect_limits.base_seconds
            self._recovery_deadline = now + self.reconnect_limits.recovery_seconds
            close_client = self._client
            # if reason not in _RETRYABLE:
            if reason not in self._retryable:
              self._give_up_locked(reason)
            elif self._token is None:
              self._give_up_locked('resume_token_required')
            elif self._logic is None:
              self._give_up_locked('resume_logic_required')
            else:
              self._state, self._next_attempt = 'backoff', now
          # 2026-09-10: completed restoration still needs server handback.
          # if self._state == 'restoring' and (self._candidate.is_disconnected() or now >= self._recovery_deadline):
          if self._state in ('restoring', 'handback') and (self._candidate.is_disconnected() or now >= self._recovery_deadline):
            close_client = self._candidate
            self._pending = self._candidate = None
            self._retry_locked(close_client.failure_reason or 'handshake_timeout', now)
          if self._state == 'backoff':
            if now >= self._recovery_deadline:
              self._give_up_locked('recovery_timeout')
            elif now >= self._next_attempt:
              self._state = 'attempting'
              self._attempts += 1
              self._total_attempts = min(0xffffffffffffffff, self._total_attempts + 1)
              attempt = True
          if close_client is None and not attempt:
            self._condition.wait(.01)
            continue
        if close_client is not None:
          close_client.close()
        if not attempt:
          continue
        candidate = self._new_client()
        with self._condition:
          if self._state == 'closed':
            candidate.close()
            return
          self._candidate = candidate
        try:
          # 2026-09-10: absolute deadline and confirmed-frame bound cross attempts.
          # candidate.connect(resume_token=self._token, expected_session=self._session, expected_slots=self._slots)
          candidate.connect(resume_token=self._token, expected_session=self._session, expected_slots=self._slots,
                            minimum_frame=self._logic.get_last_confirmed_frame_id() + 1, deadline=self._recovery_deadline)
          snapshot = candidate.take_resume_snapshot()
          if snapshot is None:
            raise ClientFailure('missing_resume_snapshot')
          with self._condition:
            if self._state == 'closed':
              candidate.close()
              return
            if time.monotonic() >= self._recovery_deadline:
              raise ClientFailure('recovery_timeout')
            self._pending = snapshot
            self._state = 'restoring'
            self._condition.notify_all()
          del snapshot
        except Exception as error:
          reason = error.reason if isinstance(error, ClientFailure) else 'connect_failed'
          candidate.close()
          with self._condition:
            self._candidate = self._pending = None
            if self._state != 'closed':
              self._retry_locked(reason, time.monotonic())
        finally:
          del candidate
    except Exception:
      with self._condition:
        self._give_up_locked('reconnect_worker_error')
    finally:
      with self._condition:
        candidate = self._candidate
        if self._state in ('closed', 'gave_up'):
          self._candidate = self._pending = None
      if candidate is not None:
        candidate.close()

  def tick(self):
    self._owner()
    if not self._tick_guard.acquire(blocking=False):
      raise RuntimeError('Concurrent or reentrant reconnect tick')
    try:
      with self._condition:
        if self._state == 'closed':
          return
        disconnect, give_up = self._disconnect_notice, self._give_up_notice
        self._disconnect_notice = self._give_up_notice = False
        on_disconnect, on_give_up = self._on_disconnect, self._on_give_up
      if disconnect and self._logic is not None:
        self._logic.stop()
        self._logic.run_one_tick()  # Refund stopped prediction on its owner.
      if disconnect and on_disconnect is not None:
        on_disconnect()
      if give_up and on_give_up is not None:
        on_give_up()
      with self._condition:
        if self._state == 'handback' and self._candidate.resume_handback_complete:
          self._candidate = None
          self._state = 'connected'
          self._attempts = 0
          self._restores = min(0xffffffffffffffff, self._restores + 1)
          on_reconnect = self._on_reconnect
          self._condition.notify_all()
        else:
          on_reconnect = None
      if on_reconnect is not None:
        on_reconnect(self._session, list(self._slots))
      with self._condition:
        if self._state != 'restoring':
          return
        # 2026-09-10: expired recovery must not mutate the caller's engine.
        if time.monotonic() >= self._recovery_deadline:
          raise ClientFailure('recovery_timeout')
        snapshot, self._pending = self._pending, None
        self._active_snapshot = snapshot
        candidate = self._candidate
        self._state = 'applying'
      try:
        frame, payload = snapshot
        if frame <= self._logic.get_last_confirmed_frame_id():
          raise ClientFailure('stale_resume_snapshot')
        # 2026-09-10: Validate protocol-specific native origins on the logic owner before restore.
        # self._env.set_state(payload)
        self._restore_snapshot(payload)
        # 2026-09-10: resumed controls bind to this snapshot before sending Ready.
        # loop = ClientLogicLoop(candidate, self._env, self._session[1] + self._session[2],
        #                        self.controlled_slots_callback or (lambda: []), initial_frame_id=frame,
        #                        **self._logic_options)
        loop = self._make_logic(candidate, self._env, self._logic_options, frame)
        with self._condition:
          if self._state == 'closed':
            loop.stop()
            return
          if time.monotonic() >= self._recovery_deadline:
            raise ClientFailure('recovery_timeout')
          if not candidate.send_ready():
            raise ClientFailure(candidate.failure_reason or 'ready_failed')
          self._client, self._logic = candidate, loop
          # 2026-09-10: queued Ready is not proof of server handback.
          # self._candidate = None
          # self._state = 'connected'
          # self._attempts = 0
          # self._restores = min(0xffffffffffffffff, self._restores + 1)
          # on_reconnect = self._on_reconnect
          self._state = 'handback'
          self._condition.notify_all()
        # 2026-09-10: dispatch success on a later tick after wire handback.
        # if on_reconnect is not None:
        #   on_reconnect(self._session, list(self._slots))
      finally:
        with self._condition:
          self._active_snapshot = None
        del snapshot
    except Exception as error:
      with self._condition:
        self._give_up_locked(error.reason if isinstance(error, ClientFailure) else 'restore_or_callback_failed')
        candidate = self._candidate
      if candidate is not None:
        candidate.close()
      self._client.close()
      raise
    finally:
      self._tick_guard.release()

  def _restore_snapshot(self, payload):
    self._env.set_state(payload)

  def run_one_tick(self):
    self.tick()
    with self._condition:
      loop = self._logic if self._state == 'connected' else None
    if loop is not None:
      loop.run_one_tick()

  @property
  def client(self):
    with self._condition:
      return self._client

  @property
  def logic(self):
    return self._logic

  @property
  def is_reconnecting(self):
    with self._condition:
      # 2026-09-10: include server confirmation in recovery state.
      # return self._state in ('backoff', 'attempting', 'restoring', 'applying')
      return self._state in ('backoff', 'attempting', 'restoring', 'applying', 'handback')

  @property
  def reconnect_attempts(self):
    with self._condition:
      return self._attempts

  @property
  def failure_reason(self):
    with self._condition:
      return self._failure

  def stats(self):
    with self._condition:
      return dict(state=self._state, attempts=self._attempts, total_attempts=self._total_attempts,
                  restores=self._restores, failure=self._failure, last_error=self._last_error,
                  # 2026-09-10: active engine restoration remains charged through close.
                  # snapshot_bytes=sys.getsizeof(self._pending[1]) if self._pending is not None else 0,
                  snapshot_bytes=sum(sys.getsizeof(value[1]) for value in (self._pending, self._active_snapshot) if value is not None),
                  active_restore=self._active_snapshot is not None,
                  candidate=self._candidate is not None,
                  worker_alive=self._worker is not None and self._worker.is_alive())

  def close(self):
    with self._condition:
      self._state = 'closed'
      self._token = self._pending = None
      self._disconnect_notice = self._give_up_notice = False
      candidate, worker = self._candidate, self._worker
      self._condition.notify_all()
    if self._logic is not None:
      self._logic.stop()
    self._client.close()
    if candidate is not None:
      candidate.close()
    if worker is not None and worker is not threading.current_thread() and worker.ident is not None:
      worker.join(2)
      if worker.is_alive():
        raise RuntimeError('Reconnect owner has not stopped; its sole in-flight operation remains owned')

  def __enter__(self):
    return self

  def __exit__(self, *_):
    self.close()
