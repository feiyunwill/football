# Copyright 2026 Google LLC
# 2026-09-10: one owned IO worker and the common strict frame application state.
import collections
import select
import socket
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import BufferedClientAPI, ClientBuffers, ClientFailure
from gfootball.frame_sync.udp_state import MAX_PACKET, MAX_PAYLOAD, UDPLimits
from gfootball.frame_sync.udp_transport import ReliableUDPClient


class _UDPClientBuffers(ClientBuffers):
  def __init__(self, limits):
    super().__init__(limits)
    self.heartbeats = 0

  def _parse(self, now):
    heartbeat = bool(self.receive) and self.receive[0] == wire.MessageType.Heartbeat
    parsed = super()._parse(now)
    if parsed and heartbeat:
      self.heartbeats = min(0xffffffffffffffff, self.heartbeats + 1)
    return parsed


class FrameSyncUDPClient(BufferedClientAPI):
  """Initial-session UDP client with bounded queues and ordered byte delivery.

  Wire DATA/ACK headers and 1200-byte datagram limit match ReliableUDPChannel.
  This receiver also orders/deduplicates data. Legacy native receivers must
  independently implement those guarantees for the opposite direction.
  Ready remains explicit, after caller engine initialization. Token resume and
  snapshot bootstrap are separate protocols and are not inferred from a hello.
  OS hostname resolution is synchronous; nonblocking socket IO and the handshake
  have bounded waits. close() joins the one worker before releasing its socket.
  """
  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None,
               udp_limits=None, handshake='versioned'):
    if handshake != 'versioned':
      raise ValueError('UDP initial sessions require the versioned handshake')
    if udp_limits is not None and not isinstance(udp_limits, UDPLimits):
      raise ValueError('Expected UDPLimits')
    self._init_buffers(host, port, controlled_slots_callback, limits, handshake)
    self.udp_limits = udp_limits or UDPLimits()
    self._lifecycle = threading.RLock()
    self._sock = None
    self._remote = None
    self._channel = None
    self._recv_thread = None
    self._running = False
    self._generation = 0
    self._handshake_done = threading.Event()
    self._send_queue = collections.deque()
    self._send_bytes = 0

  def _advance_generation_locked(self):
    if self._generation >= 0xffffffffffffffff:
      raise ClientFailure('generation_exhausted')
    self._generation += 1
    return self._generation

  def connect(self):
    with self._lifecycle:
      self.close()
      with self._lock:
        generation = self._advance_generation_locked()
        self._buffers = _UDPClientBuffers(self.limits)
        done = self._handshake_done = threading.Event()
      sock = None
      started = False
      try:
        remote = (socket.gethostbyname(self.host), self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.limits.connect_timeout)
        sock.connect(remote)  # Kernel source filtering applies to recv/recvfrom.
        sock.setblocking(False)
        with self._lock:
          if generation != self._generation or self._buffers.phase == 'closed':
            raise ClientFailure('closed')
          self._sock, self._remote = sock, remote
          self._channel = channel = ReliableUDPClient(
              sock, remote, lambda chunk: self._feed(chunk, generation), limits=self.udp_limits)
          channel.start(background=False)
          self._running = True
          if not self._enqueue_locked(wire.pack_version_negotiate()):
            raise ClientFailure(self._buffers.failure)
          worker = threading.Thread(target=self._recv_loop, args=(sock, channel, generation),
                                    name='football-udp-io')
          self._recv_thread = worker
          worker.start()
          started = True
        if not done.wait(self.limits.handshake_timeout):
          with self._lock:
            if generation == self._generation:
              self._fail_locked('handshake_timeout')
        with self._lock:
          if generation != self._generation:
            raise ClientFailure('closed')
          if self._buffers.phase not in ('ready', 'streaming'):
            raise ClientFailure(self._buffers.failure or 'handshake_timeout')
          return self._buffers.session, list(self._buffers.slots)
      except BaseException:
        with self._lock:
          if generation == self._generation:
            self._fail_locked(self._buffers.failure or 'connect_failed')
        if started:
          self.close()
        elif sock is not None:
          sock.close()
          with self._lock:
            if self._sock is sock:
              self._sock = None
        raise

  def _enqueue_locked(self, packet):
    if self._buffers.phase == 'closed':
      return False
    retained = sys.getsizeof(packet)
    if (len(packet) > MAX_PAYLOAD or len(self._send_queue) >= self.limits.send_messages or
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
    self._handshake_done.set()
    if self._channel is not None:
      self._channel.stop(reason)
    # The worker owns actual socket close in finally. No descriptor is closed
    # while select/recv may be using it (including on Windows).

  def _feed(self, chunk, generation):
    with self._lock:
      if generation != self._generation or not self._running:
        return
      self._buffers.feed(chunk)
      if self._buffers.phase == 'ready':
        self._handshake_done.set()

  def _recv_loop(self, sock, channel, generation):
    try:
      while True:
        with self._lock:
          if not self._running or generation != self._generation:
            return
          now = time.monotonic()
          reason = self._buffers.timeout(now)
          if reason:
            raise ClientFailure(reason)
          if not self._heartbeat_locked(now):
            return
          if self._send_queue and now - self._send_queue[0][1] >= self.limits.write_timeout:
            raise ClientFailure('write_timeout')
          for _ in range(64):
            if not self._send_queue:
              break
            packet = self._send_queue[0][0]
            if not channel.send(packet):
              # 2026-09-10: release temporary references before the IO wait.
              del packet
              break  # Retain the original queue deadline during backpressure.
            self._send_queue.popleft()
            self._send_bytes -= sys.getsizeof(packet)
            del packet
          if not channel.poll():
            raise ClientFailure(channel.failure_reason or 'udp_io_error')
        readable, _, _ = select.select([sock], [], [], .01)
        if readable:
          for _ in range(64):
            with self._lock:
              if not self._running or generation != self._generation:
                return
            try:
              packet, remote = sock.recvfrom(MAX_PACKET + 1)
            except BlockingIOError:
              break
            except OSError as error:
              if getattr(error, 'winerror', None) == 10040:
                # WSAEMSGSIZE consumed an oversized datagram. Account for it
                # as invalid without allocating an arbitrary-size receive.
                packet, remote = b'', self._remote
              else:
                raise
            # 2026-09-10: do not retain the last datagram across idle select loops.
            # if not channel.handle_received(packet, remote):
            #   raise ClientFailure(channel.failure_reason or 'udp_io_error')
            try:
              if not channel.handle_received(packet, remote):
                raise ClientFailure(channel.failure_reason or 'udp_io_error')
            finally:
              del packet
    except Exception as error:
      with self._lock:
        if generation == self._generation and self._running:
          self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'udp_io_error')
    finally:
      channel.stop()
      # 2026-09-10: serialize descriptor release with stats().getsockname().
      # sock.close()
      with self._lock:
        sock.close()
        if self._sock is sock:
          self._sock = None
        if generation == self._generation and self._running:
          self._fail_locked(channel.failure_reason or 'udp_io_error')

  def close(self):
    with self._lock:
      # 2026-09-10: even an exhausted generation must permit final cleanup.
      # self._advance_generation_locked()
      if self._generation < 0xffffffffffffffff:
        self._advance_generation_locked()
      self._fail_locked('closed')
      worker = self._recv_thread
    if worker is not None and worker is not threading.current_thread():
      if worker.ident is not None:
        worker.join(timeout=1.0)
        if worker.is_alive():
          raise RuntimeError('UDP IO worker did not stop; refusing connection reuse')
      with self._lock:
        if self._recv_thread is worker:
          self._recv_thread = None

  def reset_for_reconnect(self):
    self.close()

  def stats(self):
    with self._lock:
      result = super().stats()
      result.update(phase=self._buffers.phase, failure=self._buffers.failure,
                    received_heartbeats=getattr(self._buffers, 'heartbeats', 0),
                    worker_alive=self._recv_thread is not None and self._recv_thread.is_alive(),
                    local_endpoint=self._sock.getsockname() if self._sock is not None else None,
                    udp=self._channel.stats() if self._channel is not None else None)
      return result

  def __enter__(self):
    return self

  def __exit__(self, *_):
    self.close()
