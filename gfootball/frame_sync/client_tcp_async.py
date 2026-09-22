# Copyright 2026 Google LLC
# 2026-09-09: bounded asyncio TCP using one reader/writer/watchdog per connection.
import asyncio
import collections
import socket
import sys
import time

from gfootball.frame_sync.client_buffers import BufferedClientAPI, ClientBuffers, ClientFailure
from gfootball.frame_sync import protocol as wire


class FrameSyncClientAsync(BufferedClientAPI):
  """One event loop owns all IO; public send/close may be called from other threads.

  Raw nonblocking sockets avoid StreamReader/Writer internal buffers. Pending
  bytes are charged before scheduling a single writer wakeup. close() signals
  shutdown; await close_async() completes cancellation and releases active IO.
  The default server_first hello preserves the existing Python asyncio server;
  versioned and native modes explicitly select the other server handshakes.
  """
  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, handshake='server_first'):
    self._init_buffers(host, port, controlled_slots_callback, limits, handshake)
    self._loop = None
    self._sock = None
    self._running = False
    self._connecting = False
    self._connect_task = None
    self._connect_io = None
    self._cleanup_done = None
    self._generation = 0
    self._cancel_version = 0
    self._tasks = ()
    self._handshake_done = None
    self._write_ready = None
    self._send_queue = collections.deque()
    self._active_send = None
    self._send_bytes = 0
    self._wake_scheduled = False
    self._stop_scheduled = False

  def _bind_loop(self):
    loop = asyncio.get_running_loop()
    if self._loop is not None and self._loop is not loop:
      raise RuntimeError('An asynchronous client belongs to one event loop')
    self._loop = loop
    return loop

  async def connect_async(self):
    loop = self._bind_loop()
    with self._lock:
      if self._connecting:
        raise RuntimeError('TCP connection attempt already in progress')
      self._connecting = True
      cancel_version = self._cancel_version
    established = False
    try:
      await self._close_io()
      with self._lock:
        if cancel_version != self._cancel_version:
          raise asyncio.CancelledError()
        self._generation += 1
        generation = self._generation
        self._buffers = ClientBuffers(self.limits)
        self._sock = sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        self._handshake_done = asyncio.Event()
        self._write_ready = asyncio.Event()
        self._wake_scheduled = self._stop_scheduled = False
        self._cleanup_done = None
        self._running = True
        self._connect_task = asyncio.current_task()
      # 2026-09-10: track OS connect separately from the caller's whole handshake;
      # cleanup can await IO without deadlocking a handshake that awaits cleanup.
      # await asyncio.wait_for(loop.sock_connect(sock, (self.host, self.port)), self.limits.connect_timeout)
      self._connect_io = asyncio.create_task(loop.sock_connect(sock, (self.host, self.port)), name='football-tcp-connect')
      try:
        await asyncio.wait_for(self._connect_io, self.limits.connect_timeout)
      finally:
        self._connect_io = None
      established = True
      with self._lock:
        # 2026-09-09: Close has cancellation semantics even if connect finished
        # just before the stop callback could cancel its waiting task.
        if cancel_version != self._cancel_version:
          raise asyncio.CancelledError()
        if not self._running:
          raise ClientFailure(self._buffers.failure or 'closed')
        if self.handshake != 'server_first':
          hello = wire.pack_version_negotiate() if self.handshake == 'versioned' else b'\x00'
          if not self._enqueue_locked(hello):
            raise ClientFailure(self._buffers.failure)
        self._tasks = (
            asyncio.create_task(self._read_loop(sock, generation), name='football-tcp-reader'),
            asyncio.create_task(self._write_loop(sock, generation), name='football-tcp-writer'),
            asyncio.create_task(self._watchdog(generation), name='football-tcp-watchdog'))
      await asyncio.wait_for(self._handshake_done.wait(), self.limits.handshake_timeout)
      with self._lock:
        if self._buffers.phase != 'ready':
          raise ClientFailure(self._buffers.failure or 'invalid_handshake')
        return self._buffers.session, list(self._buffers.slots)
    except BaseException as error:
      with self._lock:
        self._connect_task = None
        if isinstance(error, TimeoutError):
          reason = 'handshake_timeout' if established else 'connect_timeout'
        elif isinstance(error, asyncio.CancelledError):
          reason = 'cancelled'
        else:
          reason = error.reason if isinstance(error, ClientFailure) else 'io_error'
        self._fail_locked(reason)
      await self._close_io()
      if isinstance(error, TimeoutError):
        raise ClientFailure(reason) from error
      raise
    finally:
      with self._lock:
        self._connect_task = None
        self._connecting = False

  def _enqueue_locked(self, packet):
    if not self._running:
      return False
    retained = sys.getsizeof(packet)
    count = len(self._send_queue) + (self._active_send is not None)
    if count >= self.limits.send_messages or retained > self.limits.send_bytes - self._send_bytes:
      self._fail_locked('send_capacity')
      return False
    self._send_queue.append((packet, time.monotonic()))
    self._send_bytes += retained
    if not self._wake_scheduled:
      self._wake_scheduled = True
      try:
        self._loop.call_soon_threadsafe(self._wake_writer, self._generation)
      except RuntimeError:
        self._fail_locked('io_error')
        return False
    return True

  def _wake_writer(self, generation):
    with self._lock:
      if generation != self._generation:
        return
      self._wake_scheduled = False
      if self._running:
        self._write_ready.set()

  def _fail_locked(self, reason):
    self._buffers.fail(reason)
    self._running = False
    for packet, _ in self._send_queue:
      self._send_bytes -= sys.getsizeof(packet)
    self._send_queue.clear()
    # Keep the active packet charged until sock_sendall's cancellation completes.
    if not self._stop_scheduled and self._loop is not None:
      self._stop_scheduled = True
      try:
        self._loop.call_soon_threadsafe(self._stop_io, self._generation)
      except RuntimeError:
        if self._sock is not None:
          self._sock.close()

  # 2026-09-10: defer descriptor close until actual read/write/connect IO
  # cancellation completes; fixes WinError 6 exposed by real server integration.
  # def _stop_io(self, generation):
  #   with self._lock:
  #     if generation != self._generation:
  #       return
  #     if self._sock is not None:
  #       # 2026-09-09: shutdown wakes pending overlapped reads and sends FIN;
  #       # closing a Windows socket with a pending read otherwise resets peers.
  #       try:
  #         self._sock.shutdown(socket.SHUT_RDWR)
  #       except OSError:
  #         pass
  #       self._sock.close()
  #       self._sock = None
  #     if self._handshake_done is not None:
  #       self._handshake_done.set()
  #     for task in self._tasks:
  #       if not task.done():
  #         task.cancel()
  #     # 2026-09-09: malformed handshakes are connection errors, not caller
  #     # cancellation. The handshake event delivers their original failure.
  #     # if self._connect_task is not None and not self._connect_task.done():
  #     #   self._connect_task.cancel()
  #     if (self._buffers.failure in ('closed', 'cancelled') and
  #         self._connect_task is not None and not self._connect_task.done()):
  #       self._connect_task.cancel()
  #
  def _stop_io(self, generation):
    with self._lock:
      if generation != self._generation or self._cleanup_done is not None:
        return
      sock, self._sock = self._sock, None
      tasks = list(self._tasks)
      if self._connect_io is not None:
        tasks.append(self._connect_io)
      tasks = tuple(set(tasks))
      self._cleanup_done = completed = self._loop.create_future()
      if sock is not None:
        try:
          sock.shutdown(socket.SHUT_RDWR)
        except OSError:
          pass
      if self._handshake_done is not None:
        self._handshake_done.set()
      for task in tasks:
        if not task.done():
          task.cancel()
      if (self._buffers.failure in ('closed', 'cancelled') and
          self._connect_task is not None and not self._connect_task.done()):
        self._connect_task.cancel()

      def finish(task=None):
        if task is not None and not task.cancelled():
          task.exception()
        if all(owner.done() for owner in tasks) and not completed.done():
          # Windows overlapped cancellation still needs the actual descriptor.
          # Finish every OS operation before releasing that descriptor.
          if sock is not None:
            sock.close()
          completed.set_result(None)
      for task in tasks:
        task.add_done_callback(finish)
      finish()

  async def _read_loop(self, sock, generation):
    try:
      while True:
        with self._lock:
          if not self._running or generation != self._generation:
            return
          free = min(4096, self.limits.receive_bytes - sys.getsizeof(self._buffers.receive))
          if free <= 0:
            raise ClientFailure('receive_capacity')
        chunk = await self._loop.sock_recv(sock, free)
        with self._lock:
          if not self._running or generation != self._generation:
            return
          if not chunk:
            raise ClientFailure('eof')
          self._buffers.feed(chunk)
          if self._buffers.phase == 'ready':
            self._handshake_done.set()
    except asyncio.CancelledError:
      return
    except (OSError, ValueError, ClientFailure) as error:
      with self._lock:
        if generation == self._generation and self._running:
          self._fail_locked(error.reason if isinstance(error, ClientFailure) else 'io_error')

  async def _write_loop(self, sock, generation):
    try:
      while True:
        await self._write_ready.wait()
        with self._lock:
          if not self._running or generation != self._generation:
            return
          if not self._send_queue:
            self._write_ready.clear()
            continue
          packet, queued_at = self._send_queue.popleft()
          self._active_send = packet
        try:
          remaining = self.limits.write_timeout - (time.monotonic() - queued_at)
          if remaining <= 0:
            raise TimeoutError()
          await asyncio.wait_for(self._loop.sock_sendall(sock, packet), remaining)
        finally:
          with self._lock:
            self._send_bytes -= sys.getsizeof(packet)
            self._active_send = None
            del packet
    except asyncio.CancelledError:
      return
    except (OSError, ValueError) as error:
      with self._lock:
        if generation == self._generation and self._running:
          self._fail_locked('write_timeout' if isinstance(error, TimeoutError) else 'io_error')

  async def _watchdog(self, generation):
    try:
      while True:
        await asyncio.sleep(0.01)
        with self._lock:
          if not self._running or generation != self._generation:
            return
          reason = self._buffers.timeout(time.monotonic())
          if reason:
            self._fail_locked(reason)
            return
          if not self._heartbeat_locked(time.monotonic()):
            return
    except asyncio.CancelledError:
      return

  def close(self):
    with self._lock:
      self._cancel_version += 1
      self._fail_locked('closed')

  async def _close_io(self):
    with self._lock:
      self._fail_locked('closed')
      tasks = list(self._tasks)
      if self._connect_task is not None and self._connect_task is not asyncio.current_task():
        tasks.append(self._connect_task)
    # 2026-09-10: establish the shared completion even when the coalesced stop
    # callback has not run yet; caller cancellation cannot cancel this owner.
    # await asyncio.sleep(0)
    self._stop_io(self._generation)
    if self._cleanup_done is not None:
      await asyncio.shield(self._cleanup_done)
    if tasks:
      await asyncio.gather(*tasks, return_exceptions=True)
    with self._lock:
      if all(task.done() for task in self._tasks):
        self._tasks = ()

  async def close_async(self):
    self._bind_loop()
    self.close()
    await self._close_io()

  async def __aenter__(self):
    return self

  async def __aexit__(self, *_):
    await self.close_async()
