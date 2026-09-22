# Copyright 2026 Google LLC
# 2026-09-09: one bounded, nonblocking IO worker for the synchronous Python API.
import collections
import errno
import math
import select
import socket
import sys
import threading
import time

from gfootball.frame_sync.client_buffers import BufferedClientAPI, ClientBuffers, ClientFailure
from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.resume_protocol import ResumeBuffers, ResumeLimits, RESUME_VERSION, validate_token


class FrameSyncClient(BufferedClientAPI):
  """Thread-safe TCP API; explicit close joins the single owned IO worker.

  The default versioned hello matches the Python server. handshake='native'
  sends Connect for EngineTCPServer/FrameSyncServer. No protocol guessing or
  fresh-session substitution is performed after a failed handshake.

  Socket establishment has a timeout; OS name resolution remains synchronous.
  Ready is explicit so callers can initialize the engine before gameplay.
  """
  # 2026-09-10: opt-in automatic capability issuance, legacy handshakes unchanged.
  # def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, handshake='versioned'):
  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, handshake='versioned',
               enable_resume=False, resume_limits=None):
    self._init_buffers(host, port, controlled_slots_callback, limits, handshake)
    if type(enable_resume) is not bool or (enable_resume and handshake != 'versioned'):
      raise ValueError('Token issuance requires the versioned handshake')
    if resume_limits is not None and not isinstance(resume_limits, ResumeLimits):
      raise ValueError('Expected ResumeLimits')
    self.enable_resume = enable_resume
    self.resume_limits = resume_limits or ResumeLimits()
    self._lifecycle = threading.RLock()
    self._sock = None
    self._recv_thread = None
    self._running = False
    self._generation = 0
    self._handshake_done = threading.Event()
    self._send_queue = collections.deque()
    self._send_bytes = 0
    self._send_offset = 0

  # 2026-09-10: preserve blocking establishment; use cancelable IO and bounded bootstrap.
  #   def connect(self):
  #     with self._lifecycle:
  #       self.close()
  #       with self._lock:
  #         self._generation += 1
  #         generation = self._generation
  #         self._buffers = ClientBuffers(self.limits)
  #         self._handshake_done = threading.Event()
  #       try:
  #         sock = socket.create_connection((self.host, self.port), timeout=self.limits.connect_timeout)
  #       except OSError:
  #         with self._lock:
  #           self._fail_locked('connect_failed')
  #         raise
  #       try:
  #         sock.setblocking(False)
  #         with self._lock:
  #           # 2026-09-09: Close can cancel while OS connection setup is in flight.
  #           if generation != self._generation or self._buffers.phase == 'closed':
  #             raise ClientFailure('closed')
  #           self._sock = sock
  #           self._running = True
  #           hello = wire.pack_version_negotiate() if self.handshake == 'versioned' else bytes([wire.MessageType.Connect])
  #           # 2026-09-09: server-first mode sends nothing until explicit Ready.
  #           # if not self._enqueue_locked(hello):
  #           if self.handshake != "server_first" and not self._enqueue_locked(hello):
  #             raise ClientFailure(self._buffers.failure)
  #           worker = threading.Thread(target=self._recv_loop, args=(sock, self._generation),
  #                                     name='football-tcp-client', daemon=True)
  #           self._recv_thread = worker
  #           worker.start()
  #         if not self._handshake_done.wait(self.limits.handshake_timeout):
  #           with self._lock:
  #             self._fail_locked('handshake_timeout')
  #         with self._lock:
  #           if self._buffers.phase != 'ready':
  #             raise ClientFailure(self._buffers.failure or 'invalid_handshake')
  #           return self._buffers.session, list(self._buffers.slots)
  #       except BaseException:
  #         sock.close()
  #         self.close()
  #         raise
  # 

  # 2026-09-10: one absolute recovery deadline covers connect and bootstrap.
  # def connect(self, *, resume_token=None, expected_session=None, expected_slots=None):
  def connect(self, *, resume_token=None, expected_session=None, expected_slots=None, minimum_frame=0, deadline=None):
    if type(minimum_frame) is not int or not 0 <= minimum_frame <= 0xfffffff7:
      raise ValueError('Invalid minimum resume frame')
    if deadline is not None and (type(deadline) not in (float, int) or not math.isfinite(deadline)):
      raise ValueError('Invalid absolute connection deadline')
    if resume_token is not None:
      validate_token(resume_token)
      if (type(expected_session) is not tuple or len(expected_session) != 3 or
          type(expected_slots) is not tuple or not 1 <= len(expected_slots) <= 22):
        raise ValueError('Resume requires the original session and slot assignment')
    elif expected_session is not None or expected_slots is not None:
      raise ValueError('Expected identity is only valid for resume')
    with self._lifecycle:
      self.close()
      with self._lock:
        if self._generation == 0xffffffffffffffff:
          raise ClientFailure('generation_exhausted')
        self._generation += 1
        generation = self._generation
        # 2026-09-10: Protocol-specific bootstrap reuses the same bounded TCP owner.
        # self._buffers = (ResumeBuffers(self.limits, self.resume_limits,
        #                  restoring=resume_token is not None, expected_session=expected_session,
        #                  # 2026-09-10: pass the confirmed lower frame bound.
        #                  # expected_slots=expected_slots) if self.enable_resume or resume_token is not None
        #                  expected_slots=expected_slots, minimum_frame=minimum_frame) if self.enable_resume or resume_token is not None
        #                  else ClientBuffers(self.limits))
        self._buffers = self._make_buffers(resume_token, expected_session, expected_slots, minimum_frame)
        done = self._handshake_done = threading.Event()
      sock = None
      started = False
      try:
        # 2026-09-10: apply the controller's total deadline to both IO phases.
        # sock = self._establish(generation)
        sock = self._establish(generation, deadline)
        with self._lock:
          if generation != self._generation or not self._running:
            raise ClientFailure('closed')
          # 2026-09-10: Allow explicitly negotiated match bootstrap without duplicating TCP IO.
          # if resume_token is not None:
          #   hello = wire.pack_reconnect_request(resume_token)
          # elif self.enable_resume:
          #   hello = wire.pack_version_negotiate(RESUME_VERSION, RESUME_VERSION)
          # else:
          #   hello = wire.pack_version_negotiate() if self.handshake == 'versioned' else bytes([wire.MessageType.Connect])
          hello = self._hello_packet(resume_token)
          if (resume_token is not None or self.handshake != 'server_first') and not self._enqueue_locked(hello):
            raise ClientFailure(self._buffers.failure)
          worker = threading.Thread(target=self._recv_loop, args=(sock, generation), name='football-tcp-client')
          self._recv_thread = worker
          worker.start()
          started = True
        # 2026-09-10: don't restart a full handshake timeout after slow connect.
        # if not done.wait(self.limits.handshake_timeout):
        # 2026-09-10: classify by the deadline that bounded the wait. Windows
        # timed waits and monotonic sampling can differ at the final boundary.
        # remaining = self.limits.handshake_timeout if deadline is None else min(self.limits.handshake_timeout, max(0, deadline - time.monotonic()))
        remaining, timeout_reason = self.limits.handshake_timeout, 'handshake_timeout'
        if deadline is not None:
          outer_remaining = max(0, deadline - time.monotonic())
          if outer_remaining <= remaining:
            remaining, timeout_reason = outer_remaining, 'recovery_timeout'
        if not done.wait(remaining):
          with self._lock:
            if generation == self._generation:
              # 2026-09-10: distinguish recovery's absolute deadline.
              # self._fail_locked('handshake_timeout')
              # 2026-09-10: retain the selected deadline reason after wait expiry.
              # self._fail_locked('recovery_timeout' if deadline is not None and time.monotonic() >= deadline else 'handshake_timeout')
              self._fail_locked(timeout_reason)
        with self._lock:
          if generation != self._generation:
            raise ClientFailure('closed')
          if self._buffers.phase != 'ready':
            raise ClientFailure(self._buffers.failure or 'invalid_handshake')
          return self._buffers.session, list(self._buffers.slots)
      except BaseException as error:
        with self._lock:
          if generation == self._generation:
            self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'connect_failed')
        if started:
          self.close()
        elif sock is not None:
          with self._lock:
            sock.close()
            if self._sock is sock:
              self._sock = None
        raise

  def _make_buffers(self, resume_token, expected_session, expected_slots, minimum_frame):
    if self.enable_resume or resume_token is not None:
      return ResumeBuffers(self.limits, self.resume_limits, restoring=resume_token is not None,
          expected_session=expected_session, expected_slots=expected_slots, minimum_frame=minimum_frame)
    return ClientBuffers(self.limits)

  def _hello_packet(self, resume_token):
    if resume_token is not None:
      return wire.pack_reconnect_request(resume_token)
    if self.enable_resume:
      return wire.pack_version_negotiate(RESUME_VERSION, RESUME_VERSION)
    return wire.pack_version_negotiate() if self.handshake == 'versioned' else bytes([wire.MessageType.Connect])

  # 2026-09-10: socket timeout is capped by the enclosing recovery.
  # def _establish(self, generation):
  def _establish(self, generation, outer_deadline=None):
    # OS DNS remains synchronous. No helper/thread is spawned for an abandoned
    # resolver; a reconnect controller retains its sole attempt until it returns.
    addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
    deadline = time.monotonic() + self.limits.connect_timeout
    if outer_deadline is not None:
      deadline = min(deadline, outer_deadline)
    last_error = OSError('No usable TCP address')
    for family, kind, proto, _, address in addresses[:8]:
      # 2026-09-10: DNS may return after cancellation's absolute deadline;
      # don't open or send a new connection after that deadline has expired.
      if time.monotonic() >= deadline:
        raise ClientFailure('recovery_timeout' if outer_deadline is not None and time.monotonic() >= outer_deadline else 'connect_timeout')
      sock = socket.socket(family, kind, proto)
      try:
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._lock:
          if generation != self._generation or self._buffers.phase == 'closed':
            raise ClientFailure('closed')
          self._sock = sock
          self._running = True
        code = sock.connect_ex(address)
        if code not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037):
          raise OSError(code, 'TCP connect failed')
        while code:
          with self._lock:
            if generation != self._generation or not self._running:
              raise ClientFailure('closed')
          remaining = deadline - time.monotonic()
          if remaining <= 0:
            raise ClientFailure('connect_timeout')
          _, writable, errors = select.select([], [sock], [sock], min(.01, remaining))
          if writable or errors:
            code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if code:
              raise OSError(code, 'TCP connect failed')
        return sock
      except BaseException as error:
        with self._lock:
          sock.close()
          if self._sock is sock:
            self._sock = None
        if not isinstance(error, OSError):
          raise
        last_error = error
        if time.monotonic() >= deadline:
          break
    raise last_error

  @property
  def session_token(self):
    with self._lock:
      return getattr(self._buffers, 'session_token', None)

  def take_resume_snapshot(self):
    with self._lock:
      snapshot = getattr(self._buffers, 'snapshot', None)
      if snapshot is not None:
        self._buffers.snapshot = None
      return snapshot

  @property
  def resume_handback_complete(self):
    with self._lock:
      return (isinstance(self._buffers, ResumeBuffers) and self._buffers.restoring
              and self._buffers.phase == 'streaming' and bool(self._buffers.slots)
              and all(slot in self._buffers.handed_back for slot in self._buffers.slots))

  def stats(self):
    with self._lock:
      result = super().stats()
      result.update(snapshot_bytes=getattr(self._buffers, 'retained_snapshot_bytes', 0),
                    worker_alive=self._recv_thread is not None and self._recv_thread.is_alive())
      return result

  def _enqueue_locked(self, packet):
    if not self._running:
      return False
    retained = sys.getsizeof(packet)
    if (len(self._send_queue) >= self.limits.send_messages or
        retained > self.limits.send_bytes - self._send_bytes):
      self._fail_locked('send_capacity')
      return False
    self._send_queue.append((packet, time.monotonic()))
    self._send_bytes += retained
    return True

  def _fail_locked(self, reason):
    self._buffers.fail(reason)
    self._running = False
    self._send_queue.clear()
    self._send_bytes = 0
    self._send_offset = 0
    self._handshake_done.set()
    if self._sock is not None:
      try:
        self._sock.shutdown(socket.SHUT_RDWR)
      except OSError:
        pass
      # 2026-09-10: actual close belongs to the IO owner after select/recv exit.
      # self._sock.close()
      # self._sock = None

  def _recv_loop(self, sock, generation):
    try:
      while True:
        with self._lock:
          if not self._running or generation != self._generation:
            return
          now = time.monotonic()
          reason = self._buffers.timeout(now)
          if reason:
            self._fail_locked(reason)
            return
          if not self._heartbeat_locked(now):
            return
          if self._send_queue and now - self._send_queue[0][1] >= self.limits.write_timeout:
            self._fail_locked('write_timeout')
            return
          writing = bool(self._send_queue)
        readable, writable, _ = select.select([sock], [sock] if writing else [], [], 0.01)
        if readable:
          with self._lock:
            if not self._running or generation != self._generation:
              return
            free = min(4096, self.limits.receive_bytes - sys.getsizeof(self._buffers.receive))
            if free <= 0:
              raise ClientFailure('receive_capacity')
            try:
              chunk = sock.recv(free)
            except BlockingIOError:
              chunk = None
            if chunk == b'':
              raise ClientFailure('eof')
            if chunk:
              self._buffers.feed(chunk)
              if self._buffers.phase == 'ready':
                self._handshake_done.set()
        if writable:
          with self._lock:
            if not self._running or generation != self._generation or not self._send_queue:
              continue
            packet = self._send_queue[0][0]
            # memoryview avoids retaining a second sliced packet on partial writes.
            try:
              sent = sock.send(memoryview(packet)[self._send_offset:])
            except BlockingIOError:
              continue
            if sent == 0:
              raise ClientFailure('io_error')
            self._send_offset += sent
            if self._send_offset == len(packet):
              self._send_queue.popleft()
              self._send_bytes -= sys.getsizeof(packet)
              self._send_offset = 0
            del packet
    except (OSError, ValueError, ClientFailure) as error:
      with self._lock:
        if generation == self._generation and self._running:
          self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'io_error')
    finally:
      with self._lock:
        if generation == self._generation and self._running:
          self._fail_locked('io_error')
      # 2026-09-10: synchronize final descriptor release with client state.
      # sock.close()
      with self._lock:
        sock.close()
        if self._sock is sock:
          self._sock = None

  # 2026-09-09: do not hold the connection-attempt lock while cancelling IO.
  #   def close(self):
  #     with self._lifecycle:
  #       with self._lock:
  #         self._fail_locked('closed')
  #         worker = self._recv_thread
  #       if worker is not None and worker is not threading.current_thread():
  #         # All worker IO is nonblocking; shutdown wakes select/recv. Joining
  #         # outside the state lock lets the worker run its final cleanup.
  #         if worker.ident is not None:
  #           worker.join(timeout=1.0)
  #           if worker.is_alive():
  #             raise RuntimeError('TCP worker did not stop; refusing to reuse the connection')
  #         self._recv_thread = None
  #
  def close(self):
    # Only Connect serializes on _lifecycle. Close must be able to interrupt a
    # handshake waiting for a packet; its generation also invalidates pending
    # connection establishment before that socket can replace the current one.
    with self._lock:
      # 2026-09-10: saturate generation; exhausted clients still permit cleanup.
      # self._generation += 1
      if self._generation < 0xffffffffffffffff:
        self._generation += 1
      self._fail_locked('closed')
      worker = self._recv_thread
    if worker is not None and worker is not threading.current_thread():
      if worker.ident is not None:
        worker.join(timeout=1.0)
        if worker.is_alive():
          raise RuntimeError('TCP worker did not stop; refusing to reuse the connection')
      with self._lock:
        if self._recv_thread is worker:
          self._recv_thread = None

  def reset_for_reconnect(self):
    """Release the old socket and join its worker before a future connection."""
    self.close()

  def __enter__(self):
    return self

  def __exit__(self, *_):
    self.close()
