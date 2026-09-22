# Copyright 2026 Google LLC
# 2026-09-10: explicit reliable channel lifecycle around a borrowed UDP socket.
import socket
import threading
import time

from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.udp_state import UDPState
from gfootball.frame_sync import udp_session


class ReliableUDPClient:
  """Ordered delivery, bounded retransmission, and recoverable send backpressure.

  The socket is borrowed and must be nonblocking. The owner supplies received
  datagrams and closes its socket after its receiver exits. start(background=False)
  lets an existing IO owner call poll(), avoiding a second transport thread.
  stop() joins the optional retry worker. A caller-owned on_data callback cannot
  be forcibly stopped; its payload stays charged until that callback returns.
  """
  # 2026-09-10: optional epoch envelope isolates reconnect attempts; legacy stays unchanged.
  # def __init__(self, sock, remote_addr, on_data_callback, *, limits=None):
  def __init__(self, sock, remote_addr, on_data_callback, *, limits=None, epoch=None):
    if (not isinstance(sock, socket.socket) or sock.type & 0xf != socket.SOCK_DGRAM or
        sock.family != socket.AF_INET or sock.gettimeout() != 0.0):
      raise ValueError('Expected a nonblocking IPv4 UDP socket')
    if (type(remote_addr) is not tuple or len(remote_addr) != 2 or
        type(remote_addr[0]) is not str or type(remote_addr[1]) is not int or
        not 1 <= remote_addr[1] <= 65535):
      raise ValueError('Expected a numeric IPv4 endpoint')
    try:
      if socket.inet_ntop(socket.AF_INET, socket.inet_pton(socket.AF_INET, remote_addr[0])) != remote_addr[0]:
        raise ValueError('Expected canonical IPv4 endpoint')
    except OSError as error:
      raise ValueError('Expected a numeric IPv4 endpoint') from error
    if not callable(on_data_callback):
      raise ValueError('UDP data callback must be callable')
    self._sock, self._remote, self._on_data = sock, remote_addr, on_data_callback
    self._epoch = None if epoch is None else udp_session.epoch_value(epoch)
    self._epoch_dropped = 0
    # 2026-09-10: epoch protocol peers ACK completed ordered delivery.
    # self._state = UDPState(limits)
    self._state = UDPState(limits, ack_on_delivery=epoch is not None)
    self._lock = threading.RLock()
    self._delivery_lock = threading.RLock()
    self._stopped = threading.Event()
    self._running = False
    self._retransmit_thread = None

  def start(self, *, background=True):
    if type(background) is not bool:
      raise ValueError('background must be bool')
    with self._lock:
      self._state._open()
      if self._running:
        return
      self._running = True
      if background:
        worker = threading.Thread(target=self._retransmit_loop, name='football-udp-retry')
        self._retransmit_thread = worker
        try:
          worker.start()
        except Exception:
          self._fail_locked('udp_worker_start_failed')
          raise

  def _fail_locked(self, reason):
    self._state.close(reason)
    self._running = False
    self._stopped.set()

  def stop(self, reason='closed'):
    with self._lock:
      self._fail_locked(reason)
      worker = self._retransmit_thread
    if worker is not None and worker is not threading.current_thread() and worker.ident is not None:
      worker.join(timeout=1.0)
      if worker.is_alive():
        raise RuntimeError('UDP retry worker did not stop')

  def _emit_locked(self, packet):
    try:
      if self._epoch is not None:
        packet = udp_session.wrap(self._epoch, packet)
      sent = self._sock.sendto(packet, self._remote)
      if sent != len(packet):
        raise OSError('Incomplete datagram send')
      return True
    except BlockingIOError:
      # DATA remains unsent; ACK can be regenerated from a retransmitted DATA.
      return False
    except OSError:
      self._fail_locked('udp_io_error')
      return False

  def send(self, data):
    with self._lock:
      if not self._running:
        return False
      if self._epoch is not None and (type(data) is not bytes or not 1 <= len(data) <= udp_session.MAX_PAYLOAD):
        raise ValueError('UDP session payload exceeds its datagram budget')
      try:
        seq = self._state.enqueue(data, time.monotonic())
      except ClientFailure as error:
        self._fail_locked(error.reason)
        return False
      if seq is None:
        return False
      packet = self._state.pending[seq][0]
      if self._emit_locked(packet):
        self._state.mark_sent(seq, time.monotonic())
      return self._running

  def poll(self):
    with self._lock:
      if not self._running:
        return False
      try:
        for seq, packet in self._state.due(time.monotonic()):
          if not self._emit_locked(packet):
            break
          self._state.mark_sent(seq, time.monotonic())
      except ClientFailure as error:
        self._fail_locked(error.reason)
      return self._running

  def handle_received(self, buf, remote_addr=None):
    # Serialize callback order even when an embedding application dispatches
    # receives from several threads. Reentrancy cannot redeliver active data.
    with self._delivery_lock:
      with self._lock:
        if not self._running:
          return False
        if remote_addr is not None and remote_addr != self._remote:
          return True
        if self._epoch is not None:
          buf = udp_session.unwrap(self._epoch, buf)
          if buf is None:
            self._epoch_dropped = min(0xffffffffffffffff, self._epoch_dropped + 1)
            return True
        try:
          ack = self._state.receive(buf, time.monotonic())
          if ack is not None:
            self._emit_locked(ack)
        except ClientFailure as error:
          self._fail_locked(error.reason)
          return False
      while True:
        with self._lock:
          if not self._running:
            return False
          payload = self._state.next_delivery()
        if payload is None:
          return True
        try:
          self._on_data(payload)
        except Exception as error:
          with self._lock:
            self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'udp_callback_failed')
          raise
        finally:
          with self._lock:
            # 2026-09-10: completed delivery releases remote pressure, even if
            # the original ACK was lost (a delivered duplicate regenerates it).
            # self._state.complete_delivery()
            ack = self._state.complete_delivery()
            if ack is not None and self._running:
              self._emit_locked(ack)
          del payload

  def _retransmit_loop(self):
    try:
      while not self._stopped.wait(.01):
        if not self.poll():
          break
    finally:
      with self._lock:
        self._fail_locked(self._state.failure or 'closed')

  @property
  def failure_reason(self):
    with self._lock:
      return self._state.failure

  def stats(self):
    with self._lock:
      # 2026-09-10: report stale/control envelopes discarded before stream delivery.
      # return self._state.stats()
      return dict(self._state.stats(), epoch_enabled=self._epoch is not None, epoch_dropped=self._epoch_dropped)
