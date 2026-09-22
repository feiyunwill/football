# 2026-09-09: real TCP capacity/lifetime contracts, runnable without GameEnv/Gym.
import collections
import asyncio
import socket
import struct
import sys
import threading
import time
import unittest
from unittest import mock

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client import FrameSyncClient
from gfootball.frame_sync.client_async import FrameSyncClientAsync
from gfootball.frame_sync.client_buffers import ClientBuffers, ClientFailure, ClientLimits


def until(predicate, timeout=3):
  deadline = time.monotonic() + timeout
  while not predicate():
    if time.monotonic() >= deadline:
      raise AssertionError('TCP fixture progress deadline expired')
    time.sleep(0.002)


def exact(peer, count):
  data = b''
  while len(data) < count:
    chunk = peer.recv(count - len(data))
    if not chunk:
      raise AssertionError('TCP fixture saw unexpected EOF')
    data += chunk
  return data


def hello(peer, mode='versioned', left=1, right=1, slots=(0,)):
  expected = wire.pack_version_negotiate() if mode == 'versioned' else b'\x00'
  if exact(peer, len(expected)) != expected:
    raise AssertionError('wrong client hello')
  peer.sendall(wire.pack_session_start(42, left, right) + wire.pack_slot_assignment(slots))


def ready(peer):
  if exact(peer, 1) != wire.pack_ready():
    raise AssertionError('expected Ready')


def authority(frame, count=2):
  return wire.pack_authoritative_frame(frame, [wire.default_slot_input()] * count)


class Peer:
  def __init__(self, *scripts):
    self.listener = socket.socket()
    self.listener.bind(('127.0.0.1', 0))
    self.listener.listen()
    self.listener.settimeout(0.05)
    self.port = self.listener.getsockname()[1]
    self.stop = threading.Event()
    self.failure = None

    def run():
      try:
        for script in scripts:
          deadline = time.monotonic() + 5
          while not self.stop.is_set():
            try:
              peer, _ = self.listener.accept()
              break
            except socket.timeout:
              if time.monotonic() > deadline:
                raise AssertionError('TCP fixture accept timed out')
          else:
            return
          with peer:
            peer.settimeout(3)
            script(peer, self.stop)
      except BaseException as error:
        self.failure = error

    self.worker = threading.Thread(target=run, name='tcp-budget-fixture')
    self.worker.start()

  def __enter__(self):
    return self

  def __exit__(self, exc_type, *_):
    self.stop.set()
    self.worker.join(timeout=5)
    self.listener.close()
    if self.worker.is_alive():
      raise AssertionError('TCP fixture thread did not stop')
    if self.failure is not None and exc_type is None:
      raise self.failure


class BufferBudgetTest(unittest.TestCase):
  def streaming(self, **limits):
    state = ClientBuffers(ClientLimits(**limits))
    state.feed(wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([0]))
    state.phase = 'streaming'
    return state

  def test_invalid_configuration_precedes_socket_creation(self):
    with mock.patch('socket.create_connection') as connect:
      for host, port in [('', 1), ('a\x00b', 1), ('x' * 254, 1), ('localhost', True), ('localhost', 0), ('localhost', 65536)]:
        with self.subTest(host=host, port=port), self.assertRaises(ValueError):
          FrameSyncClient(host, port)
      for options in [dict(authority_frames=0), dict(hashes=1025), dict(send_messages=-1),
                      dict(send_bytes=True), dict(handshake_timeout=float('nan')),
                      dict(idle_timeout=0), dict(ready_timeout=31)]:
        with self.subTest(options=options), self.assertRaises(ValueError):
          ClientLimits(**options)
      connect.assert_not_called()

  def test_payload_capacity_fills_rejects_releases_and_refills(self):
    state = self.streaming(authority_frames=2)
    state.feed(authority(0) + authority(1))
    self.assertEqual(state.authority_bytes, sum(sys.getsizeof(value) for value in state.authority))
    first = state.pop_authority()
    self.assertEqual(first[0], 0)
    state.feed(authority(2))
    self.assertEqual([state.pop_authority()[0], state.pop_authority()[0]], [1, 2])
    self.assertEqual(state.authority_bytes, 0)
    state.feed(authority(3) + authority(4))
    with self.assertRaisesRegex(ClientFailure, 'authority_capacity'):
      state.feed(authority(5))
    self.assertEqual(len(state.authority), 0)
    self.assertEqual(state.authority_bytes, 0)
    self.assertEqual(state.receive, b'')

  def test_byte_budget_counts_python_bytes_allocation(self):
    packet = authority(0)
    retained = sys.getsizeof(packet)
    state = self.streaming(authority_bytes=max(64, retained))
    state.feed(packet)
    self.assertEqual(state.authority_bytes, retained)
    with self.assertRaisesRegex(ClientFailure, 'authority_capacity'):
      state.feed(authority(1))
    self.assertEqual(state.authority_bytes, 0)

  def test_receive_budget_and_invalid_headers_reject_before_large_decode(self):
    for data in [b'\xff', wire.pack_session_start(42, 12, 0), wire.pack_session_start(42, 0, 0),
                 wire.pack_session_start(42, 1, 1) + b'\x07\xff\xff',
                 wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([0, 0])]:
      state = ClientBuffers(ClientLimits())
      with self.subTest(data=data), self.assertRaises(ClientFailure):
        state.feed(data)
      self.assertEqual(state.phase, 'closed')
      self.assertEqual(state.receive, b'')
    state = self.streaming()
    with self.assertRaisesRegex(ClientFailure, 'receive_capacity'):
      state.feed(b'x' * state.limits.receive_bytes)
    for packet in [struct.pack('<BIH', 3, 0, 65535), authority(1),
                   wire.pack_authoritative_frame(0, [wire.SlotInput(float('nan'), 0, 0), wire.default_slot_input()])]:
      state = self.streaming()
      with self.subTest(packet=packet), self.assertRaises(ClientFailure):
        state.feed(packet)

  def test_complete_controls_preserve_following_authority_alignment(self):
    state = self.streaming()
    data = (wire.pack_heartbeat(0x03040506, 0x0708090a) + wire.pack_takeover_notify(0, 0x03040506)
            + wire.pack_handback_notify(0, 0x0708090a) + authority(0))
    for byte in data:
      state.feed(bytes([byte]))
    self.assertEqual(state.pop_authority()[0], 0)
    self.assertEqual(state.bots, set())

  def test_hash_budget_deduplicates_but_never_overwrites_conflicts(self):
    state = self.streaming(hashes=2)
    state.feed(wire.pack_state_hash(0, 123) * 20 + wire.pack_state_hash(10, 456))
    self.assertEqual(state.hashes, {0: 123, 10: 456})
    with self.assertRaisesRegex(ClientFailure, 'hash_capacity'):
      state.feed(wire.pack_state_hash(20, 789))
    self.assertEqual(state.hashes, {})
    state = self.streaming()
    state.feed(wire.pack_state_hash(0, 1))
    with self.assertRaisesRegex(ClientFailure, 'invalid_hash'):
      state.feed(wire.pack_state_hash(0, 2))

  def test_timestamp_eviction_is_bounded_diagnostics_and_rtt_uses_monotonic_time(self):
    state = self.streaming(timestamps=4)
    for frame in range(120):
      state.record_send(frame, frame * 0.1)
      state.record_send(frame, frame * 0.1 + 0.004)
      state.feed(authority(frame), now=frame * 0.1 + 0.02)
      state.pop_authority()
    self.assertEqual(len(state.rtt), 50)
    self.assertTrue(all(abs(value - 20) < 0.0001 for value in state.rtt))
    for frame in range(120, 1120):
      state.record_send(frame, 100.0)
      self.assertLessEqual(len(state.timestamps), 4)
    state.fail('eof')
    self.assertEqual(len(state.timestamps), 0)
    self.assertEqual(len(state.rtt), 0)


class TCPClientBudgetTest(unittest.TestCase):
  def make_client(self, peer, callback=None, **options):
    client = FrameSyncClient('127.0.0.1', peer.port, callback, **options)
    self.addCleanup(client.close)
    return client

  def test_both_explicit_handshakes_initialize_before_ready_and_preserve_real_frames(self):
    for mode in ('versioned', 'native'):
      def script(peer, stop):
        hello(peer, mode); ready(peer)
        packet = exact(peer, 19)
        frame, entries = wire.unpack_client_frame_input(packet)
        self.assertEqual(frame, 0)
        self.assertEqual(entries, [(0, wire.SlotInput(0.5, -0.25, 4))])
        peer.sendall(wire.pack_authoritative_frame(0, [entries[0][1], wire.SlotInput(-0.5, 0.25, 8)]))
        stop.wait(3)
      with self.subTest(mode=mode), Peer(script) as peer:
        client = self.make_client(peer, lambda: [(0, wire.SlotInput(0.5, -0.25, 4))], handshake=mode)
        self.assertEqual(client.connect(), ((42, 1, 1), [0]))
        self.assertFalse(client.send_frame_input(0))
        self.assertTrue(client.send_ready())
        self.assertTrue(client.send_frame_input(0))
        until(client.has_authoritative_frame)
        frame, inputs = client.pop_authoritative_frame()
        self.assertEqual(frame, 0)
        self.assertEqual(inputs, [wire.SlotInput(0.5, -0.25, 4), wire.SlotInput(-0.5, 0.25, 8)])
        self.assertEqual(client.stats()['authority_bytes'], 0)
        client.close()

  def test_fragmented_handshake_waits_for_both_complete_packets(self):
    received_ready = threading.Event()
    def script(peer, stop):
      self.assertEqual(exact(peer, 5), wire.pack_version_negotiate())
      peer.sendall(wire.pack_session_start(42, 1, 1))
      peer.settimeout(0.08)
      with self.assertRaises(socket.timeout):
        peer.recv(1)  # A SessionStart alone must not trigger Ready or success.
      packet = wire.pack_slot_assignment([0])
      peer.sendall(packet[:-1]); time.sleep(0.04); peer.sendall(packet[-1:])
      # 2026-09-09: enqueue success is not a completed socket write.
      # peer.settimeout(3); ready(peer); stop.wait(3)
      peer.settimeout(3); ready(peer); received_ready.set(); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer)
      started = time.monotonic()
      self.assertEqual(client.connect(), ((42, 1, 1), [0]))
      self.assertGreaterEqual(time.monotonic() - started, 0.10)
      # 2026-09-09: await actual Ready reception before intentionally aborting IO.
      # client.send_ready(); client.close()
      client.send_ready(); self.assertTrue(received_ready.wait(2)); client.close()

  def test_partial_handshake_timeout_closes_and_joins(self):
    def script(peer, _):
      exact(peer, 5); peer.sendall(b'\x05\x2a')
      self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer, limits=ClientLimits(handshake_timeout=0.06))
      with self.assertRaisesRegex(ClientFailure, 'handshake_timeout'):
        client.connect()
      self.assertTrue(client.is_disconnected())
      self.assertIsNone(client._recv_thread)
      self.assertEqual(client.stats()['send_bytes'], 0)

  def test_eof_and_malformed_authority_fail_without_logic_ticks(self):
    for malformed in (False, True):
      def script(peer, stop):
        hello(peer); ready(peer)
        if malformed:
          peer.sendall(struct.pack('<BIH', 3, 0, 65535))
          self.assertEqual(peer.recv(1), b'')
      with self.subTest(malformed=malformed), Peer(script) as peer:
        client = self.make_client(peer); client.connect(); client.send_ready()
        until(client.is_disconnected)
        self.assertEqual(client.failure_reason, 'invalid_authority' if malformed else 'eof')
        client.close()
        self.assertIsNone(client._recv_thread)

  def test_twenty_two_slots_send_full_packet(self):
    entries = [(i, wire.SlotInput(0.25, -0.5, 1 << (i % 12))) for i in range(22)]
    def script(peer, stop):
      hello(peer, left=11, right=11, slots=range(22)); ready(peer)
      frame, received = wire.unpack_client_frame_input(exact(peer, 271))
      self.assertEqual(frame, 0); self.assertEqual(received, entries)
      peer.sendall(authority(0, 22)); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer, lambda: entries)
      client.connect(); client.send_ready(); self.assertTrue(client.send_frame_input(0))
      until(client.has_authoritative_frame)
      self.assertEqual(len(client.pop_authoritative_frame()[1]), 22)
      client.close()

  def test_hash_check_preserves_other_frames_and_stops_on_mismatch(self):
    def script(peer, stop):
      hello(peer); ready(peer)
      peer.sendall(wire.pack_state_hash(0, wire.compute_state_hash(b'zero')) + wire.pack_state_hash(10, 123))
      stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer); client.connect(); client.send_ready()
      until(lambda: client.stats()['hashes'] == 2)
      self.assertTrue(client.check_state_hash(5, b'other'))
      self.assertEqual(client.stats()['hashes'], 2)
      self.assertTrue(client.check_state_hash(0, b'zero'))
      self.assertEqual(client.stats()['hashes'], 1)
      self.assertFalse(client.check_state_hash(10, b'wrong'))
      self.assertEqual(client.failure_reason, 'hash_mismatch')
      self.assertFalse(client.send_frame_input(11)); client.close()

  def test_pending_send_budget_applies_before_worker_dispatch(self):
    received_ready = threading.Event()
    def script(peer, stop):
      hello(peer); ready(peer); received_ready.set(); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer, lambda: [(0, wire.default_slot_input())], limits=ClientLimits(send_messages=2))
      client.connect(); client.send_ready(); self.assertTrue(received_ready.wait(2))
      # Hold the transport state lock to suspend dispatch while real API calls
      # enqueue packets, matching a temporarily stalled IO worker.
      with client._lock:
        self.assertTrue(client.send_frame_input(0)); self.assertTrue(client.send_frame_input(1))
        self.assertEqual(client.stats()['send_messages'], 2)
        self.assertFalse(client.send_frame_input(2))
      self.assertEqual(client.failure_reason, 'send_capacity')
      client.close(); self.assertEqual(client.stats()['send_bytes'], 0)

  def test_input_callback_can_close_and_invalid_generator_is_bounded(self):
    for invalid in (False, True):
      def script(peer, stop):
        hello(peer); ready(peer)
        self.assertEqual(peer.recv(1), b'')
      with self.subTest(invalid=invalid), Peer(script) as peer:
        generated = []
        def callback():
          if not invalid:
            client.close()
            return [(0, wire.default_slot_input())]
          def entries():
            for i in range(1000000):
              generated.append(i)
              yield (0, wire.default_slot_input())
          return entries()
        client = self.make_client(peer, callback); client.connect(); client.send_ready()
        until(lambda: client.stats()['send_messages'] == 0)
        if invalid:
          with self.assertRaises(ValueError):
            client.send_frame_input(0)
          self.assertEqual(len(generated), 23)
        else:
          self.assertFalse(client.send_frame_input(0))
        self.assertTrue(client.is_disconnected()); client.close()

  def test_repeated_connect_joins_previous_worker_and_clears_all_history(self):
    count = 12
    def script(peer, _):
      hello(peer); ready(peer)
      peer.sendall(authority(0))
      self.assertEqual(peer.recv(1), b'')
    with Peer(*([script] * count)) as peer:
      client = self.make_client(peer)
      previous = None
      for _ in range(count):
        client.connect(); client.send_ready(); until(client.has_authoritative_frame)
        current = client._recv_thread
        if previous is not None:
          self.assertFalse(previous.is_alive())
        self.assertEqual(client.pop_authoritative_frame()[0], 0)
        client.reset_for_reconnect()
        self.assertFalse(current.is_alive())
        self.assertEqual(client.stats()['authority_bytes'], 0)
        previous = current

  def test_partial_stream_drip_does_not_keep_connection_alive(self):
    def script(peer, stop):
      hello(peer); ready(peer)
      for byte in authority(0):
        if stop.wait(0.025):
          return
        try:
          peer.sendall(bytes([byte]))
        except OSError:
          return
    with Peer(script) as peer:
      client = self.make_client(peer, limits=ClientLimits(idle_timeout=0.08))
      client.connect(); client.send_ready()
      until(client.is_disconnected)
      self.assertEqual(client.failure_reason, 'idle_timeout'); client.close()

  def test_close_interrupts_in_progress_handshake_without_waiting_for_its_deadline(self):
    accepted = threading.Event()
    def script(peer, _):
      exact(peer, 5); accepted.set()
      self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer, limits=ClientLimits(handshake_timeout=2.0))
      errors = []
      def connect():
        try:
          client.connect()
        except Exception as error:
          errors.append(error)
      worker = threading.Thread(target=connect, name='tcp-budget-connect')
      worker.start()
      try:
        self.assertTrue(accepted.wait(2))
        started = time.monotonic(); client.close()
        self.assertLess(time.monotonic() - started, 0.5)
      finally:
        worker.join(timeout=4)
      self.assertFalse(worker.is_alive())
      self.assertEqual(len(errors), 1)
      self.assertIsInstance(errors[0], ClientFailure)
      self.assertTrue(client.is_disconnected())

  def test_actual_slow_reader_expires_write_without_unbounded_queue(self):
    received_ready = threading.Event()
    def script(peer, stop):
      peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
      hello(peer, left=11, right=11, slots=range(22)); ready(peer)
      received_ready.set(); stop.wait(5)
    with Peer(script) as peer:
      entries = [(slot, wire.default_slot_input()) for slot in range(22)]
      client = self.make_client(peer, lambda: entries,
                                limits=ClientLimits(send_messages=1024, send_bytes=512 * 1024,
                                                    write_timeout=0.08, idle_timeout=5))
      client.connect()
      with client._lock:
        client._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
      client.send_ready(); self.assertTrue(received_ready.wait(2))
      deadline = time.monotonic() + 3
      frame = 0
      while not client.is_disconnected() and time.monotonic() < deadline:
        client.send_frame_input(frame); frame += 1
        self.assertLessEqual(client.stats()['send_bytes'], client.limits.send_bytes)
        time.sleep(0.002)
      self.assertEqual(client.failure_reason, 'write_timeout')
      client.close(); self.assertEqual(client.stats()['send_bytes'], 0)

  def test_logic_stops_before_snapshot_or_prediction_after_actual_transport_failure(self):
    from gfootball.frame_sync.client import ClientLogicLoop
    def script(peer, _):
      hello(peer); ready(peer); peer.sendall(struct.pack('<BIH', 3, 0, 65535))
      self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer); client.connect(); client.send_ready()
      until(client.is_disconnected)
      # No engine behavior is simulated here: these sentinels fail if the
      # disconnected logic layer tries to save, restore or advance anything.
      engine = mock.Mock()
      for name in ('get_state', 'set_state', 'step_with_input'):
        getattr(engine, name).side_effect = AssertionError('disconnected engine call')
      loop = ClientLogicLoop(client, engine, 2, lambda: [])
      for _ in range(20):
        loop.run_one_tick()
      self.assertEqual(engine.mock_calls, [])
      self.assertEqual(loop.get_current_frame_id(), 0)
      self.assertTrue(loop.is_waiting_for_authority())
      client.close()


async def async_until(predicate, timeout=3):
  deadline = time.monotonic() + timeout
  while not predicate():
    if time.monotonic() >= deadline:
      raise AssertionError('async TCP progress deadline expired')
    await asyncio.sleep(0.002)


class AsyncTCPClientBudgetTest(unittest.IsolatedAsyncioTestCase):
  def make_client(self, peer, callback=None, **options):
    client = FrameSyncClientAsync('127.0.0.1', peer.port, callback, **options)
    self.addAsyncCleanup(client.close_async)
    return client

  async def assert_clean_close(self, client):
    await client.close_async()
    self.assertEqual(client._tasks, ())
    self.assertIsNone(client._active_send)
    self.assertEqual(client.stats()['send_bytes'], 0)
    self.assertEqual(client.stats()['authority_bytes'], 0)
    self.assertFalse([task for task in asyncio.all_tasks() if task.get_name().startswith('football-tcp-')])

  async def test_three_explicit_hello_modes_preserve_twenty_two_slot_wire_inputs(self):
    for mode in ('versioned', 'native', 'server_first'):
      entries = [(i, wire.SlotInput(0.5, 0.25, i % 12)) for i in range(22)]
      def script(peer, stop):
        if mode == 'server_first':
          peer.sendall(wire.pack_session_start(42, 11, 11) + wire.pack_slot_assignment(range(22)))
        else:
          hello(peer, mode, 11, 11, range(22))
        ready(peer)
        self.assertEqual(wire.unpack_client_frame_input(exact(peer, 271)), (0, entries))
        peer.sendall(authority(0, 22)); stop.wait(3)
      with self.subTest(mode=mode), Peer(script) as peer:
        client = self.make_client(peer, lambda: entries, handshake=mode)
        self.assertEqual(await client.connect_async(), ((42, 11, 11), list(range(22))))
        self.assertTrue(client.send_ready()); self.assertTrue(client.send_frame_input(0))
        await async_until(client.has_authoritative_frame)
        self.assertEqual(len(client.pop_authoritative_frame()[1]), 22)
        await self.assert_clean_close(client)

  async def test_handshake_event_requires_both_complete_messages(self):
    first = threading.Event(); release = threading.Event(); got_ready = threading.Event()
    def script(peer, stop):
      peer.sendall(wire.pack_session_start(42, 1, 1)); first.set()
      self.assertTrue(release.wait(2))
      packet = wire.pack_slot_assignment([0]); peer.sendall(packet[:-1])
      time.sleep(0.04); peer.sendall(packet[-1:]); ready(peer); got_ready.set(); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer)
      attempt = asyncio.create_task(client.connect_async())
      await async_until(first.is_set)
      await asyncio.sleep(0.03)
      self.assertFalse(attempt.done())
      release.set()
      self.assertEqual(await attempt, ((42, 1, 1), [0]))
      client.send_ready(); await async_until(got_ready.is_set)
      await self.assert_clean_close(client)

  async def test_initial_eof_and_invalid_header_fail_as_connection_errors(self):
    for data, expected in [(b'', 'eof'), (b'\xff', 'unsupported_message'),
                           (wire.pack_session_start(42, 12, 0), 'invalid_session')]:
      def script(peer, _):
        if data:
          peer.sendall(data)
          self.assertEqual(peer.recv(1), b'')
      with self.subTest(data=data), Peer(script) as peer:
        client = self.make_client(peer)
        with self.assertRaisesRegex(ClientFailure, expected):
          await client.connect_async()
        self.assertEqual(client.failure_reason, expected)
        await self.assert_clean_close(client)

  async def test_partial_handshake_timeout_releases_socket_and_tasks(self):
    def script(peer, _):
      peer.sendall(b'\x05\x2a'); self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer, limits=ClientLimits(handshake_timeout=0.06))
      with self.assertRaisesRegex(ClientFailure, 'handshake_timeout'):
        await client.connect_async()
      await self.assert_clean_close(client)

  async def test_explicit_close_cancels_the_in_progress_handshake(self):
    connected = threading.Event()
    def script(peer, _):
      connected.set(); self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer, limits=ClientLimits(handshake_timeout=2))
      attempt = asyncio.create_task(client.connect_async())
      await async_until(connected.is_set)
      started = time.monotonic(); await client.close_async()
      self.assertLess(time.monotonic() - started, 0.5)
      with self.assertRaises(asyncio.CancelledError):
        await attempt
      await self.assert_clean_close(client)

  async def test_caller_cancellation_cleans_up_without_an_extra_close_call(self):
    connected = threading.Event()
    def script(peer, _):
      # 2026-09-09: cancellation may race the pending OS connect operation;
      # its Windows completion may reset the peer before receive IO starts.
      # peer.sendall(b'\x05'); connected.set(); self.assertEqual(peer.recv(1), b'')
      peer.sendall(b'\x05'); connected.set()
      try:
        self.assertEqual(peer.recv(1), b'')
      except ConnectionResetError:
        pass
    with Peer(script) as peer:
      client = self.make_client(peer)
      attempt = asyncio.create_task(client.connect_async())
      await async_until(connected.is_set); attempt.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await attempt
      self.assertEqual(client._tasks, ())
      self.assertIsNone(client._sock)
      self.assertEqual(client.stats()['send_bytes'], 0)

  async def test_caller_cancellation_after_partial_read_sends_eof_and_cleans_tasks(self):
    def script(peer, _):
      peer.sendall(b'\x05'); self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer:
      client = self.make_client(peer)
      attempt = asyncio.create_task(client.connect_async())
      await async_until(lambda: client._buffers.receive == b'\x05')
      attempt.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await attempt
      self.assertEqual(client._tasks, ())
      self.assertIsNone(client._sock)
      self.assertEqual(client.stats()['send_bytes'], 0)

  async def test_foreign_thread_burst_is_bounded_before_loop_dispatch(self):
    got_ready = threading.Event()
    def script(peer, stop):
      peer.sendall(wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([0]))
      ready(peer); got_ready.set(); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer, lambda: [(0, wire.default_slot_input())], limits=ClientLimits(send_messages=2))
      await client.connect_async(); client.send_ready(); await async_until(got_ready.is_set)
      loop = asyncio.get_running_loop(); sent = []
      with mock.patch.object(loop, 'call_soon_threadsafe', wraps=loop.call_soon_threadsafe) as posted:
        worker = threading.Thread(target=lambda: sent.extend(client.send_frame_input(i) for i in range(1000)),
                                  name='tcp-budget-producer')
        worker.start(); worker.join(timeout=1)  # Intentionally withhold loop dispatch.
        self.assertFalse(worker.is_alive())
        self.assertEqual(sum(sent), 2)
        self.assertLessEqual(posted.call_count, 2)  # One wakeup plus one shutdown.
      self.assertEqual(client.failure_reason, 'send_capacity')
      await self.assert_clean_close(client)

  async def test_actual_slow_reader_expires_one_active_write_and_releases_it(self):
    got_ready = threading.Event()
    def script(peer, stop):
      peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
      peer.sendall(wire.pack_session_start(42, 11, 11) + wire.pack_slot_assignment(range(22)))
      ready(peer); got_ready.set(); stop.wait(5)
    with Peer(script) as peer:
      entries = [(slot, wire.default_slot_input()) for slot in range(22)]
      client = self.make_client(peer, lambda: entries,
                                limits=ClientLimits(send_messages=1024, send_bytes=512 * 1024,
                                                    write_timeout=0.08, idle_timeout=5))
      await client.connect_async()
      client._sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
      client.send_ready(); await async_until(got_ready.is_set)
      deadline = time.monotonic() + 3; frame = 0
      #       while not client.is_disconnected() and time.monotonic() < deadline:
      #         client.send_frame_input(frame); frame += 1
      #         self.assertLessEqual(client.stats()['send_bytes'], client.limits.send_bytes)
      #         self.assertLessEqual(len(client._tasks), 3)
      #         await asyncio.sleep(0.002)
      # 2026-09-09: supply bounded pressure independently of Windows timer
      # granularity; one send per sleep may never fill the kernel receive window.
      while not client.is_disconnected() and time.monotonic() < deadline:
        while not client.is_disconnected() and client.stats()['send_messages'] < 32:
          client.send_frame_input(frame); frame += 1
        self.assertLessEqual(client.stats()['send_bytes'], client.limits.send_bytes)
        self.assertLessEqual(client.stats()['send_messages'], 32)
        self.assertLessEqual(len(client._tasks), 3)
        await asyncio.sleep(0.002)
      self.assertEqual(client.failure_reason, 'write_timeout')
      await self.assert_clean_close(client)

  async def test_repeated_connections_await_previous_cancellations(self):
    def script(peer, _):
      peer.sendall(wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([0]))
      ready(peer); peer.sendall(authority(0)); self.assertEqual(peer.recv(1), b'')
    with Peer(*([script] * 10)) as peer:
      client = self.make_client(peer); previous = ()
      for _ in range(10):
        await client.connect_async()
        self.assertTrue(all(task.done() for task in previous))
        client.send_ready(); await async_until(client.has_authoritative_frame)
        self.assertEqual(client.pop_authoritative_frame()[0], 0)
        previous = client._tasks
        await self.assert_clean_close(client)

  async def test_concurrent_connect_is_rejected_without_disturbing_the_first(self):
    first = threading.Event(); release = threading.Event(); got_ready = threading.Event()
    def script(peer, stop):
      peer.sendall(wire.pack_session_start(42, 1, 1)); first.set()
      self.assertTrue(release.wait(2)); peer.sendall(wire.pack_slot_assignment([0]))
      ready(peer); got_ready.set(); stop.wait(3)
    with Peer(script) as peer:
      client = self.make_client(peer)
      attempt = asyncio.create_task(client.connect_async())
      await async_until(first.is_set)
      with self.assertRaisesRegex(RuntimeError, 'already in progress'):
        await client.connect_async()
      release.set(); self.assertEqual(await attempt, ((42, 1, 1), [0]))
      client.send_ready(); await async_until(got_ready.is_set)
      await self.assert_clean_close(client)

  async def test_stream_overflow_mismatch_and_idle_are_terminal(self):
    for mode in ('capacity', 'hash', 'idle'):
      def script(peer, stop):
        peer.sendall(wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([0])); ready(peer)
        if mode == 'capacity':
          peer.sendall(authority(0) + authority(1))
        elif mode == 'hash':
          peer.sendall(wire.pack_state_hash(0, 123))
        stop.wait(3)
      with self.subTest(mode=mode), Peer(script) as peer:
        client = self.make_client(peer, limits=ClientLimits(authority_frames=1, idle_timeout=0.1))
        await client.connect_async(); client.send_ready()
        if mode == 'hash':
          await async_until(lambda: client.stats()['hashes'] == 1)
          self.assertFalse(client.check_state_hash(0, b'wrong'))
        await async_until(client.is_disconnected)
        self.assertEqual(client.failure_reason, dict(capacity='authority_capacity', hash='hash_mismatch', idle='idle_timeout')[mode])
        await self.assert_clean_close(client)


if __name__ == '__main__':
  unittest.main(verbosity=2)
