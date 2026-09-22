"""UDP cookie/epoch transport for the shared v3 snapshot recovery protocol."""
import math
import select
import socket
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync import udp_session as session
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.client_udp_runtime import FrameSyncUDPClient
from gfootball.frame_sync.client_reconnect import ReconnectingFrameSyncClient
from gfootball.frame_sync.resume_protocol import ResumeBuffers, ResumeLimits, RESUME_VERSION, validate_token
from gfootball.frame_sync.udp_transport import ReliableUDPClient


class ResumableFrameSyncUDPClient(FrameSyncUDPClient):
  """Explicit cookie/epoch UDP protocol; requires a compatible UDP server.

  Legacy FrameSyncUDPClient continues to use native DATA/ACK initial sessions.
  This class does not silently downgrade to a new match after failed recovery.
  """
  _resume_limits_type = ResumeLimits

  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, udp_limits=None,
               handshake='versioned', enable_resume=True, resume_limits=None):
    if enable_resume is not True or handshake != 'versioned':
      raise ValueError('Resumable UDP requires v3 token negotiation')
    # 2026-09-10: explicit match subclass uses its bounded envelope limit.
    # if resume_limits is not None and type(resume_limits) is not ResumeLimits:
    #   raise ValueError('Expected ResumeLimits')
    if resume_limits is not None and type(resume_limits) is not self._resume_limits_type:
      raise ValueError('Expected ' + self._resume_limits_type.__name__)
    super().__init__(host, port, controlled_slots_callback, limits=limits,
                     udp_limits=udp_limits, handshake=handshake)
    # 2026-09-10: preserve v3 default and allow explicit v4 envelope limits.
    # self.resume_limits = resume_limits or ResumeLimits()
    self.resume_limits = resume_limits or self._resume_limits_type()
    self._epoch = None

  def _make_buffers(self, resume_token, expected_session, expected_slots, minimum_frame):
    return ResumeBuffers(self.limits, self.resume_limits, restoring=resume_token is not None,
        expected_session=expected_session, expected_slots=expected_slots, minimum_frame=minimum_frame)

  def _hello_packet(self, resume_token):
    return (wire.pack_reconnect_request(resume_token) if resume_token is not None
            else wire.pack_version_negotiate(RESUME_VERSION, RESUME_VERSION))

  def _enqueue_locked(self, packet):
    if len(packet) > session.MAX_PAYLOAD:
      self._fail_locked('send_capacity')
      return False
    return super()._enqueue_locked(packet)

  def _cookie_handshake(self, sock, epoch, generation, deadline, timeout_reason):
    request = session.hello(epoch)
    next_send = 0
    while True:
      with self._lock:
        if generation != self._generation or not self._running:
          raise ClientFailure('closed')
      now = time.monotonic()
      if now >= deadline:
        raise ClientFailure(timeout_reason)
      if now >= next_send:
        try:
          if sock.send(request) != len(request):
            raise ClientFailure('udp_io_error')
        except BlockingIOError:
          pass
        next_send = now + .1
      readable, _, _ = select.select([sock], [], [], min(.01, deadline - now))
      if not readable:
        continue
      try:
        packet = sock.recv(session.MAX_PACKET + 1)
      except BlockingIOError:
        continue
      except OSError as error:
        if getattr(error, 'winerror', None) == 10040:
          continue
        raise
      parsed = session.parse_cookie(packet)
      if parsed is None or parsed[1] != epoch:
        continue
      if parsed[0] == session.CHALLENGE:
        request = bytes([session.CONFIRM]) + packet[1:]
        next_send = 0
      elif parsed[0] == session.WELCOME and request[0] == session.CONFIRM and packet[1:] == request[1:]:
        return

  def connect(self, *, resume_token=None, expected_session=None, expected_slots=None, minimum_frame=0, deadline=None):
    if type(minimum_frame) is not int or not 0 <= minimum_frame <= 0xfffffff7:
      raise ValueError('Invalid minimum resume frame')
    if deadline is not None and (type(deadline) not in (float, int) or not math.isfinite(deadline)):
      raise ValueError('Invalid absolute connection deadline')
    if resume_token is not None:
      validate_token(resume_token)
      if (type(expected_session) is not tuple or len(expected_session) != 3 or
          type(expected_slots) is not tuple or not 1 <= len(expected_slots) <= 22):
        raise ValueError('Resume requires original session and slots')
    elif expected_session is not None or expected_slots is not None:
      raise ValueError('Expected identity is only valid for resume')
    with self._lifecycle:
      self.close()
      with self._lock:
        generation = self._advance_generation_locked()
        # 2026-09-10: transport-independent protocol buffers, v3 by default.
        # self._buffers = ResumeBuffers(self.limits, self.resume_limits, restoring=resume_token is not None,
        #     expected_session=expected_session, expected_slots=expected_slots, minimum_frame=minimum_frame)
        self._buffers = self._make_buffers(resume_token, expected_session, expected_slots, minimum_frame)
        done = self._handshake_done = threading.Event()
      sock, started = None, False
      try:
        connect_deadline = time.monotonic() + self.limits.connect_timeout
        connect_timeout_reason = 'connect_timeout'
        if deadline is not None:
          if deadline <= connect_deadline:
            connect_timeout_reason = 'recovery_timeout'
          connect_deadline = min(deadline, connect_deadline)
        if time.monotonic() >= connect_deadline:
          raise ClientFailure('recovery_timeout')
        # The OS resolver is synchronous; no detached helper is created.
        remote = socket.gethostbyname(self.host), self.port
        if time.monotonic() >= connect_deadline:
          raise ClientFailure('recovery_timeout' if deadline is not None and time.monotonic() >= deadline else 'connect_timeout')
        with self._lock:
          if generation != self._generation or self._buffers.phase == 'closed':
            raise ClientFailure('closed')
          sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
          sock.setblocking(False)
          sock.connect(remote)
          self._sock, self._remote = sock, remote
          self._epoch = epoch = session.new_epoch()
          self._running = True
        self._cookie_handshake(sock, epoch, generation, connect_deadline, connect_timeout_reason)
        with self._lock:
          if generation != self._generation or not self._running:
            raise ClientFailure('closed')
          self._channel = channel = ReliableUDPClient(sock, remote, lambda data: self._feed(data, generation),
                                                     limits=self.udp_limits, epoch=epoch)
          channel.start(background=False)
          # 2026-09-10: share cookie/epoch IO with explicitly versioned match bootstrap.
          # hello = (wire.pack_reconnect_request(resume_token) if resume_token is not None
          #          else wire.pack_version_negotiate(RESUME_VERSION, RESUME_VERSION))
          hello = self._hello_packet(resume_token)
          if not self._enqueue_locked(hello):
            raise ClientFailure(self._buffers.failure)
          worker = threading.Thread(target=self._recv_loop, args=(sock, channel, generation), name='football-udp-io')
          self._recv_thread = worker
          worker.start()
          started = True
        remaining, timeout_reason = self.limits.handshake_timeout, 'handshake_timeout'
        if deadline is not None:
          outer_remaining = max(0, deadline - time.monotonic())
          if outer_remaining <= remaining:
            remaining, timeout_reason = outer_remaining, 'recovery_timeout'
        if not done.wait(remaining):
          with self._lock:
            if generation == self._generation:
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
            self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'udp_io_error')
        if started:
          self.close()
        elif sock is not None:
          with self._lock:
            sock.close()
            if self._sock is sock:
              self._sock = None
        raise

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
      state = self._buffers
      return bool(getattr(state, 'restoring', False) and state.phase == 'streaming'
                  and set(state.slots or ()) <= state.handed_back)

  def stats(self):
    with self._lock:
      return dict(super().stats(), snapshot_bytes=getattr(self._buffers, 'retained_snapshot_bytes', 0),
                  connection_epoch=self._epoch)


class ReconnectingFrameSyncUDPClient(ReconnectingFrameSyncClient):
  """The common bounded restore/Ready/handback owner over epoch-tagged UDP."""
  _retryable = ReconnectingFrameSyncClient._retryable | frozenset((
      'udp_io_error', 'udp_retry_exhausted', 'udp_gap_timeout', 'udp_delivery_timeout'))

  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None,
               udp_limits=None, resume_limits=None, reconnect_limits=None):
    self._udp_limits = udp_limits
    super().__init__(host, port, controlled_slots_callback, limits=limits,
                     resume_limits=resume_limits, reconnect_limits=reconnect_limits)

  def _new_client(self):
    return ResumableFrameSyncUDPClient(self.host, self.port, self.controlled_slots_callback,
                                      udp_limits=self._udp_limits, **self._client_options)
