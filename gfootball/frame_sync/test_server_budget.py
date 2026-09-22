# 2026-09-10: real server sockets and client APIs; explicit engine oracle, not GameEnv.
import asyncio
import socket
import struct
import sys
import threading
import time
import unittest
from unittest import mock
import zlib

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client import FrameSyncClient
from gfootball.frame_sync.client_async import FrameSyncClientAsync
from gfootball.frame_sync.client_buffers import ClientLimits
# 2026-09-10: exercise the real public compatibility entrypoints after integration.
# from gfootball.frame_sync.server_api import FrameSyncServer, FrameSyncServerAsync
from gfootball.frame_sync.server import FrameSyncServer
from gfootball.frame_sync.server_async import FrameSyncServerAsync
from gfootball.frame_sync.server_state import (
    FrameInputWindow, ServerDecoder, ServerFailure, ServerLimits, ServerSendQueue,
)
from gfootball.frame_sync.server_runtime import ServerSettings


def until(predicate, timeout=3):
  deadline = time.monotonic() + timeout
  while not predicate():
    if time.monotonic() >= deadline:
      raise AssertionError('Real server progress deadline expired')
    time.sleep(0.002)


def exact(peer, count):
  result = b''
  while len(result) < count:
    data = peer.recv(count - len(result))
    if not data:
      raise EOFError('peer closed')
    result += data
  return result


def packet(peer):
  first = exact(peer, 1)
  kind = first[0]
  fixed = {wire.MessageType.SessionStart: 9, wire.MessageType.Heartbeat: 9,
           wire.MessageType.TakeoverNotify: 7, wire.MessageType.HandbackNotify: 7,
           wire.MessageType.StateHash: 13}
  if kind in fixed:
    return first + exact(peer, fixed[kind] - 1)
  if kind == wire.MessageType.SlotAssignment:
    head = first + exact(peer, 2)
    return head + exact(peer, 2 * struct.unpack_from('<H', head, 1)[0])
  if kind == wire.MessageType.AuthoritativeFrame:
    head = first + exact(peer, 6)
    return head + exact(peer, wire.SLOT_INPUT_BYTES * struct.unpack_from('<H', head, 5)[0])
  if kind == wire.MessageType.StateSnapshot:
    head = first + exact(peer, 8)
    size = struct.unpack_from('<I', head, 5)[0]
    if size > 1024 * 1024:
      raise AssertionError('Server snapshot exceeded wire test limit')
    return head + exact(peer, size)
  raise AssertionError('Unexpected server packet %d' % kind)


def next_kind(peer, kind):
  for _ in range(100):
    data = packet(peer)
    if data[0] == kind:
      return data
  raise AssertionError('Expected server packet not reached')


class EngineOracle:
  """Small deterministic reducer of actual SlotInput bytes, independent of server code."""
  def __init__(self, settings):
    self.slots = settings.left_agents + settings.right_agents
    self.frames = 0
    self.digest = 1
    self.closed = 0
    self.thread = threading.get_ident()
    self.fail_step = None

  def step_with_input(self, data):
    if threading.get_ident() != self.thread:
      raise AssertionError('Engine left its owner thread')
    if self.fail_step is not None:
      raise self.fail_step
    if len(data) != self.slots * 10:
      raise AssertionError('Engine received malformed input bytes')
    for index in range(self.slots):
      dx, dy, buttons = struct.unpack_from('<ffH', data, index * 10)
      if not -1.001 <= dx <= 1.001 or not -1.001 <= dy <= 1.001 or buttons & ~4095:
        raise AssertionError('Engine received invalid input values')
    self.digest = zlib.adler32(data, self.digest)
    self.frames += 1

  def get_state(self, unused=''):
    return struct.pack('<II', self.frames, self.digest)

  def get_state_digest(self):
    return self.get_state()

  def close(self):
    if threading.get_ident() != self.thread:
      raise AssertionError('Engine closed on the wrong thread')
    self.closed += 1


class ServerStateTest(unittest.TestCase):
  def test_strict_limits_and_server_settings(self):
    for options in ({'connections': 45}, {'receive_bytes': 1}, {'send_messages': True},
                    {'pending_frames': 1025}, {'snapshot_bytes': 2**30}, {'idle_timeout': float('nan')}):
      with self.assertRaises(ValueError):
        ServerLimits(**options)
    for options in ({'left_agents': 12}, {'left_agents': True}, {'left_agents': 0},
                    {'listen_port': -1}, {'game_engine_random_seed': 2**32}, {'state_hash_interval': -1}):
      with self.assertRaises(ValueError):
        ServerSettings(**options)

  def test_all_client_packet_types_parse_fragmented_and_coalesced(self):
    values = [wire.pack_version_negotiate(), b'\x00', wire.pack_ready(),
              wire.pack_heartbeat(4, 12), wire.pack_reconnect_request(123),
              wire.pack_client_frame_input(1, [(0, wire.default_slot_input())]), b'\x01']
    for width in (1, 3, 4096):
      decoder = ServerDecoder(ServerLimits(), 2)
      joined = b''.join(values)
      result = []
      for start in range(0, len(joined), width):
        decoder.feed(joined[start:start + width])
        while True:
          value = decoder.pop()
          if value is None:
            break
          result.append(value)
      self.assertEqual(result, values)
      self.assertEqual(decoder.data, b'')

  def test_decoder_rejects_oversized_count_before_body_or_unknown_message(self):
    for header in (struct.pack('<BIH', 2, 0, 65535), struct.pack('<BIH', 2, 0, 0), b'\xff'):
      decoder = ServerDecoder(ServerLimits(), 22)
      decoder.feed(header)
      with self.assertRaises(ServerFailure):
        decoder.pop()
    decoder = ServerDecoder(ServerLimits(receive_bytes=512), 22)
    with self.assertRaises(ServerFailure):
      decoder.feed(b'x' * 512)
    self.assertEqual(decoder.data, b'')

  def test_future_inputs_survive_collection_and_duplicates_do_not_grow(self):
    window = FrameInputWindow(ServerLimits(pending_frames=3), 2)
    value = wire.pack_client_frame_input(2, [(0, wire.SlotInput(.5, -.5, 4))])
    self.assertEqual(window.accept(value, (0,)), 'accepted')
    before = window.stats()
    for _ in range(1000):
      self.assertEqual(window.accept(value, (0,)), 'duplicate')
    self.assertEqual(window.stats(), before)
    window.seal()
    window.advance()
    window.seal()
    window.advance()
    self.assertEqual(window.current()[0], wire.SlotInput(.5, -.5, 4))
    window.seal()
    window.advance()
    self.assertEqual(window.payload_bytes, 0)

  def test_invalid_or_conflicting_input_does_not_partially_change_frame(self):
    window = FrameInputWindow(ServerLimits(), 2)
    good = wire.pack_client_frame_input(0, [(0, wire.default_slot_input())])
    window.accept(good, (0,))
    before = window.stats()
    invalid = [wire.pack_client_frame_input(0, [(0, wire.SlotInput(1, 0, 0))]),
               wire.pack_client_frame_input(0, [(1, wire.default_slot_input())]),
               wire.pack_client_frame_input(0, [(0, wire.SlotInput(float('nan'), 0, 0))]),
               wire.pack_client_frame_input(0, [(0, wire.SlotInput(0, 0, 4096))]), good + b'trailer']
    for value in invalid:
      with self.assertRaises(ServerFailure):
        window.accept(value, (0,))
      self.assertEqual(window.stats(), before)
      self.assertEqual(window.current(), [wire.default_slot_input()] * 2)

  def test_input_bytes_window_and_sealed_frame_bounds(self):
    window = FrameInputWindow(ServerLimits(input_bytes=64, pending_frames=2), 1)
    value = lambda frame: wire.pack_client_frame_input(frame, [(0, wire.default_slot_input())])
    window.accept(value(0), (0,))
    for frame in (1, 2, 0xffffffff):
      with self.assertRaises(ServerFailure):
        window.accept(value(frame), (0,))
    window.seal()
    self.assertEqual(window.accept(value(0), (0,)), 'late')
    window.advance()
    window.accept(value(1), (0,))
    self.assertLessEqual(window.payload_bytes, 64)

  def test_disconnect_retains_current_input_and_refunds_future_owned_slots(self):
    window = FrameInputWindow(ServerLimits(), 2)
    for frame in range(4):
      for slot in range(2):
        window.accept(wire.pack_client_frame_input(frame, [(slot, wire.SlotInput(1, 0, 0))]), (slot,))
    window.disconnect((0,))
    self.assertEqual(window.stats()['entries'], 5)
    self.assertEqual(window.current()[0].dir_x, 1)
    window.seal()
    window.advance()
    self.assertEqual(window.current()[0].dir_x, 0)
    self.assertEqual(window.current()[1].dir_x, 1)

  def test_send_budget_counts_active_and_resume_history_until_release(self):
    queue = ServerSendQueue(ServerLimits(send_messages=3, send_bytes=256))
    a, b, c = b'a' * 20, b'b' * 20, b'c' * 20
    queue.enqueue(a)
    queue.enqueue(b, deferred=True)
    queue.enqueue(c, deferred=True)
    self.assertIs(queue.take(), a)
    with self.assertRaises(ServerFailure):
      queue.enqueue(b'd')
    queue.release_active()
    queue.ready()
    self.assertIs(queue.take(), b)
    queue.close()
    self.assertEqual(queue.payload_bytes, sys.getsizeof(b))
    queue.release_active()
    self.assertEqual(queue.payload_bytes, 0)
    self.assertEqual(queue.messages, 0)

  def test_resume_queue_keeps_original_enqueue_timestamp(self):
    queue = ServerSendQueue(ServerLimits())
    queue.enqueue(b'snapshot', now=1)
    queue.enqueue(b'authority', deferred=True, now=2)
    queue.take()
    self.assertEqual(queue.active_since, 1)
    queue.release_active()
    queue.ready()
    self.assertEqual(queue.take(), b'authority')
    self.assertEqual(queue.active_since, 2)


class SyncServerTest(unittest.TestCase):
  def server(self, **options):
    server = FrameSyncServer(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle, **options)
    self.addCleanup(server.stop)
    server.start()
    return server

  def raw(self, server, hello=True):
    peer = socket.create_connection(('127.0.0.1', server.listen_port), timeout=2)
    peer.settimeout(2)
    self.addCleanup(peer.close)
    if hello:
      peer.sendall(wire.pack_version_negotiate())
      self.assertEqual(packet(peer)[0], wire.MessageType.SessionStart)
      self.assertEqual(packet(peer)[0], wire.MessageType.SlotAssignment)
    return peer

  def test_actual_client_pair_preserves_early_and_future_inputs_and_hashes(self):
    server = self.server(right_agents=1, state_hash_interval=1)
    clients = [FrameSyncClient('127.0.0.1', server.listen_port) for _ in range(2)]
    for slot, client in enumerate(clients):
      self.addCleanup(client.close)
      self.assertEqual(client.connect(), ((42, 1, 1), [slot]))
      client.send_ready()
    until(server.all_clients_ready)
    expected_digest = 1
    for frame in range(10):
      for slot, client in enumerate(clients):
        client.send_frame_entries(frame, [(slot, wire.SlotInput(.5 if slot == 0 else -.5, 0, frame % 8))])
    until(lambda: server.stats()['input']['entries'] == 20)
    for frame in range(10):
      result_frame, inputs = server.run_one_frame()
      self.assertEqual(result_frame, frame)
      self.assertEqual(inputs, [wire.SlotInput(.5, 0, frame % 8), wire.SlotInput(-.5, 0, frame % 8)])
      expected_digest = zlib.adler32(b''.join(struct.pack('<ffH', *value) for value in inputs), expected_digest)
      for client in clients:
        until(client.has_authoritative_frame)
        self.assertEqual(client.pop_authoritative_frame(), (frame, inputs))
        until(lambda: bool(client._buffers.hashes))
        self.assertTrue(client.check_state_hash(frame, struct.pack('<II', frame + 1, expected_digest)))
    engine = server.get_env()
    self.assertEqual(engine.frames, 10)
    server.stop()
    self.assertEqual(engine.closed, 1)
    self.assertEqual(server.stats()['connections'], 0)

  def test_heartbeat_plus_ready_plus_input_is_consumed_without_desynchronizing(self):
    server = self.server()
    peer = self.raw(server)
    peer.sendall(wire.pack_heartbeat(0, 123) + wire.pack_ready()
                 + wire.pack_client_frame_input(0, [(0, wire.SlotInput(0, 1, 8))]))
    until(lambda: server.stats()['input']['entries'] == 1)
    server.run_one_frame()
    self.assertEqual(wire.unpack_authoritative_frame(next_kind(peer, wire.MessageType.AuthoritativeFrame)),
                     (0, [wire.SlotInput(0, 1, 8)]))

  def test_connection_cap_and_partial_handshake_timeout_release_real_sockets(self):
    server = self.server(limits=ServerLimits(connections=2, handshake_timeout=.12))
    first, second = self.raw(server, False), self.raw(server, False)
    until(lambda: server.stats()['connections'] == 2)
    excess = self.raw(server, False)
    self.assertEqual(excess.recv(1), b'')
    first.sendall(wire.pack_version_negotiate()[:2])
    self.assertEqual(first.recv(1), b'')
    self.assertEqual(second.recv(1), b'')
    until(lambda: server.stats()['connections'] == 0)
    self.assertGreaterEqual(server.stats()['rejected'], 1)
    live = self.raw(server)
    live.sendall(wire.pack_ready())
    until(server.all_clients_ready)

  def test_oversized_header_and_invalid_owned_input_close_without_entering_engine(self):
    server = self.server()
    for bad in (struct.pack('<BIH', wire.MessageType.FrameInput, 0, 65535),
                wire.pack_client_frame_input(0, [(1, wire.default_slot_input())])):
      peer = self.raw(server)
      peer.sendall(wire.pack_ready() + bad)
      self.assertEqual(peer.recv(1), b'')
      until(lambda: server.stats()['connections'] == 0)
      self.assertEqual(server.stats()['input']['entries'], 0)
      self.assertEqual(server.get_env().frames, 0)

  def test_churn_before_match_reuses_slots_and_has_no_tombstones(self):
    server = self.server()
    for _ in range(40):
      peer = self.raw(server)
      peer.close()
      until(lambda: server.stats()['connections'] == 0)
      self.assertEqual(server.stats()['sessions'], 0)
    self.assertEqual(server.stats()['accepted'], 40)

  def test_authenticated_resume_snapshots_then_releases_exact_deferred_authority(self):
    server = self.server()
    peer = self.raw(server)
    peer.sendall(wire.pack_ready() + wire.pack_client_frame_input(0, [(0, wire.SlotInput(1, 0, 4))]))
    until(server.all_clients_ready)
    token = server.get_session_tokens()[0]
    server.run_one_frame()
    self.assertEqual(wire.unpack_authoritative_frame(next_kind(peer, wire.MessageType.AuthoritativeFrame))[0], 0)
    expected_snapshot = server.get_env().get_state()
    peer.close()
    until(lambda: server.stats()['bots'] == (0,))
    invalid = self.raw(server, False)
    invalid.sendall(wire.pack_reconnect_request(token ^ 1))
    self.assertEqual(invalid.recv(1), b'')
    self.assertEqual(server.stats()['bots'], (0,))
    resumed = self.raw(server, False)
    resumed.sendall(wire.pack_reconnect_request(token))
    self.assertEqual(packet(resumed)[0], wire.MessageType.SessionStart)
    self.assertEqual(packet(resumed)[0], wire.MessageType.SlotAssignment)
    snapshot = packet(resumed)
    self.assertEqual(wire.unpack_state_snapshot(snapshot), (1, expected_snapshot))
    self.assertEqual(packet(resumed)[0], wire.MessageType.TakeoverNotify)
    server.run_one_frame(timeout_ms=0)
    server.run_one_frame(timeout_ms=0)
    self.assertEqual(server.stats()['bots'], (0,))
    resumed.settimeout(.05)
    with self.assertRaises(socket.timeout):
      resumed.recv(1)
    resumed.settimeout(2)
    resumed.sendall(wire.pack_ready())
    self.assertEqual(wire.unpack_authoritative_frame(packet(resumed))[0], 1)
    self.assertEqual(wire.unpack_authoritative_frame(packet(resumed))[0], 2)
    self.assertEqual(packet(resumed)[0], wire.MessageType.HandbackNotify)
    until(lambda: not server.stats()['bots'])
    resumed.sendall(wire.pack_client_frame_input(3, [(0, wire.SlotInput(-1, 0, 8))]))
    self.assertEqual(server.run_one_frame()[1], [wire.SlotInput(-1, 0, 8)])

  def test_engine_error_closes_io_and_engine_once_without_publishing_bad_frame(self):
    server = self.server()
    engine = server.get_env()
    error = ValueError('engine failed')
    engine.fail_step = error
    peer = self.raw(server)
    peer.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    with self.assertRaises(ValueError) as caught:
      server.run_one_frame(timeout_ms=0)
    self.assertIs(caught.exception, error)
    server.stop()
    self.assertEqual(peer.recv(1), b'')
    self.assertEqual(engine.closed, 1)
    self.assertEqual(engine.frames, 0)
    self.assertTrue(server.stats()['closed'])

  def test_full_and_partial_message_deadlines_are_distinct_and_do_not_deadlock(self):
    server = self.server(limits=ServerLimits(message_timeout=.07, idle_timeout=.25, heartbeat_interval=.02))
    peer = self.raw(server)
    peer.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    peer.sendall(wire.pack_heartbeat(0, 1)[:1])
    until(lambda: server.stats()['connections'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'message_timeout')
    valid = self.raw(server)
    valid.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    for _ in range(5):
      valid.sendall(wire.pack_heartbeat(0, 2))
      time.sleep(.035)
      self.assertEqual(server.get_connected_client_count(), 1)
    until(lambda: server.stats()['connections'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'idle_timeout')

  def test_message_rate_limit_rejects_completed_packet_flood_without_growing_input(self):
    server = self.server(limits=ServerLimits(messages_per_second=1, message_burst=4))
    peer = self.raw(server)
    peer.sendall(wire.pack_ready() + wire.pack_heartbeat(0, 1) * 5)
    self.assertEqual(peer.recv(1), b'')
    until(lambda: server.stats()['connections'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'message_rate')
    self.assertEqual(server.stats()['input']['entries'], 0)

  def test_actual_slow_reader_hits_write_deadline_and_server_stays_responsive(self):
    server = self.server(limits=ServerLimits(write_timeout=.1, send_bytes=2 * 1024 * 1024))
    peer = self.raw(server)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    peer.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    # Actual TCP backpressure: the peer stops reading a 900 KiB heartbeat stream.
    server.send_to_all(wire.pack_heartbeat(0, 1) * 100000)
    until(lambda: server.stats()['connections'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'write_timeout')
    self.assertEqual(server.get_frame_id(), 0)
    fresh = self.raw(server)
    fresh.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    self.assertEqual(server.run_one_frame(timeout_ms=0)[0], 0)

  def test_resume_waiting_history_has_the_same_send_capacity(self):
    server = self.server(limits=ServerLimits(send_messages=2))
    peer = self.raw(server)
    peer.sendall(wire.pack_ready())
    until(server.all_clients_ready)
    token = server.get_session_tokens()[0]
    server.run_one_frame(timeout_ms=0)
    next_kind(peer, wire.MessageType.AuthoritativeFrame)
    peer.close()
    until(lambda: server.stats()['bots'] == (0,))
    resumed = self.raw(server, False)
    resumed.sendall(wire.pack_reconnect_request(token))
    for kind in (wire.MessageType.SessionStart, wire.MessageType.SlotAssignment,
                 wire.MessageType.StateSnapshot, wire.MessageType.TakeoverNotify):
      self.assertEqual(packet(resumed)[0], kind)
    until(lambda: server.stats()['send_messages'] == 0)
    for _ in range(3):
      server.run_one_frame(timeout_ms=0)
    self.assertEqual(resumed.recv(1), b'')
    until(lambda: server.stats()['connections'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'send_capacity')
    self.assertEqual(server.stats()['bots'], (0,))

  def test_stop_wakes_ready_wait_and_joins_the_private_loop(self):
    server = self.server()
    errors = []
    def run():
      try:
        server.run_loop(wait_for_ready=True)
      except BaseException as error:
        errors.append(error)
    thread = threading.Thread(target=run, name='football-server-test-loop')
    thread.start()
    time.sleep(.03)
    server.stop()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [])
    self.assertTrue(server.stats()['closed'])

  def test_startup_and_shutdown_engine_failures_are_reported_and_owner_exits(self):
    original = ValueError('failed factory')
    server = FrameSyncServer(listen_host='127.0.0.1', listen_port=0,
                             engine_factory=mock.Mock(side_effect=original))
    self.addCleanup(server.stop)
    with self.assertRaises(ValueError) as caught:
      server.start()
    self.assertIs(caught.exception, original)
    self.assertFalse(server._thread.is_alive())
    server = self.server()
    engine = server.get_env()
    actual_close = engine.close
    error = OSError('engine close failed')
    def fail_close():
      actual_close()
      raise error
    engine.close = fail_close
    with self.assertRaises(OSError) as caught:
      server.stop()
    self.assertIs(caught.exception, error)
    self.assertFalse(server._thread.is_alive())
    self.assertEqual(engine.closed, 1)

  def test_idle_actual_client_sends_periodic_liveness_without_input(self):
    server = self.server(limits=ServerLimits(idle_timeout=.2, heartbeat_interval=.03))
    client = FrameSyncClient('127.0.0.1', server.listen_port, limits=ClientLimits(idle_timeout=.2))
    self.addCleanup(client.close)
    client.connect()
    client.send_ready()
    until(server.all_clients_ready)
    time.sleep(.65)
    self.assertEqual(server.get_connected_client_count(), 1)
    self.assertFalse(client.is_disconnected())
    self.assertEqual(server.get_frame_id(), 0)
    self.assertLessEqual(client.stats()['send_messages'], 1)

  def test_queued_foreign_commands_are_bounded_before_owner_loop_dispatch(self):
    server = self.server()
    entered, release = threading.Event(), threading.Event()
    engine = server.get_env()
    original = engine.step_with_input
    def paused(data):
      entered.set()
      if not release.wait(2):
        raise AssertionError('Test did not release the engine owner')
      original(data)
    engine.step_with_input = paused
    results, errors = [], []
    def call(operation):
      try:
        results.append(operation())
      except BaseException as error:
        errors.append(error)
    first = threading.Thread(target=call, args=(lambda: server.run_one_frame(timeout_ms=0),),
                             name='football-server-test-frame')
    first.start()
    self.assertTrue(entered.wait(1))
    readers = [threading.Thread(target=call, args=(server.stats,), name='football-server-test-command') for _ in range(8)]
    try:
      for reader in readers:
        reader.start()
      until(lambda: bool(errors), timeout=1)
      self.assertEqual([error.reason for error in errors], ['control_capacity'])
    finally:
      release.set()
      first.join(2)
      for reader in readers:
        reader.join(2)
    self.assertFalse(first.is_alive() or any(reader.is_alive() for reader in readers))
    self.assertEqual(len(results), 8)

  def test_twenty_two_real_clients_share_one_bounded_future_window(self):
    server = self.server(left_agents=11, right_agents=11, limits=ServerLimits(idle_timeout=5))
    clients = [FrameSyncClient('127.0.0.1', server.listen_port) for _ in range(22)]
    for slot, client in enumerate(clients):
      self.addCleanup(client.close)
      self.assertEqual(client.connect(), ((42, 11, 11), [slot]))
      client.send_ready()
    until(server.all_clients_ready)
    for slot, client in enumerate(clients):
      for frame in range(32):
        client.send_frame_entries(frame, [(slot, wire.SlotInput(.5 if slot % 2 == 0 else -.5, 0, slot + frame))])
    until(lambda: server.stats()['input']['entries'] == 22 * 32)
    self.assertEqual(server.stats()['input']['frames'], 32)
    self.assertLessEqual(server.stats()['input']['payload_bytes'], server._runtime.limits.input_bytes)
    for frame in range(32):
      expected = [wire.SlotInput(.5 if slot % 2 == 0 else -.5, 0, slot + frame) for slot in range(22)]
      self.assertEqual(server.run_one_frame(), (frame, expected))
      for client in clients:
        until(client.has_authoritative_frame)
        self.assertEqual(client.pop_authoritative_frame(), (frame, expected))
    self.assertEqual(server.stats()['input']['entries'], 0)
    self.assertEqual(server.stats()['input']['payload_bytes'], 0)


class AsyncServerTest(unittest.IsolatedAsyncioTestCase):
  async def until(self, predicate):
    deadline = asyncio.get_running_loop().time() + 3
    while not predicate():
      if asyncio.get_running_loop().time() >= deadline:
        self.fail('Async server progress deadline expired')
      await asyncio.sleep(.002)

  async def test_actual_async_client_preserves_server_first_handshake_and_future_input(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    server.start()
    engine = server.get_env()
    await server.start_server()
    client = FrameSyncClientAsync('127.0.0.1', server.listen_port)
    self.addAsyncCleanup(client.close_async)
    self.assertEqual(await client.connect_async(), ((42, 1, 0), [0]))
    client.send_ready()
    for frame in range(5):
      client.send_frame_entries(frame, [(0, wire.SlotInput(1, 0, frame))])
    await self.until(lambda: server.stats()['input']['entries'] == 5)
    for frame in range(5):
      await server.run_one_frame()
      await self.until(client.has_authoritative_frame)
      self.assertEqual(client.pop_authoritative_frame(), (frame, [wire.SlotInput(1, 0, frame)]))
    await server.close_async()
    self.assertEqual(engine.closed, 1)

    unused = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(unused.close_async)
    unused.stop()
    with self.assertRaises(ServerFailure):
      unused.start()
    with self.assertRaises(ServerFailure):
      await unused.start_server()
    self.assertIsNone(unused.get_env())
    await unused.close_async()
    self.assertEqual(server.stats()['connections'], 0)
    self.assertEqual([task.get_name() for task in asyncio.all_tasks()
                      if task.get_name().startswith('football-server-') and not task.done()], [])

  async def test_cancel_frame_wait_closes_tasks_and_native_owner_contract(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    await server.start_server()
    engine = server.get_env()
    client = FrameSyncClientAsync('127.0.0.1', server.listen_port)
    self.addAsyncCleanup(client.close_async)
    await client.connect_async()
    client.send_ready()
    await self.until(server._runtime.all_ready)
    task = asyncio.create_task(server.run_one_frame(timeout_ms=30000))
    await self.until(lambda: server._runtime.collecting)
    task.cancel()
    with self.assertRaises(asyncio.CancelledError):
      await task
    self.assertEqual(engine.closed, 1)
    self.assertTrue(server.stats()['closed'])

  async def test_cancelled_close_waiter_does_not_cancel_socket_cleanup(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    await server.start_server()
    engine = server.get_env()
    client = FrameSyncClientAsync('127.0.0.1', server.listen_port)
    self.addAsyncCleanup(client.close_async)
    await client.connect_async()
    client.send_ready()
    await self.until(server._runtime.all_ready)
    waiter = asyncio.create_task(server.close_async())
    await asyncio.sleep(0)
    waiter.cancel()
    with self.assertRaises(asyncio.CancelledError):
      await waiter
    await server.close_async()
    self.assertEqual(engine.closed, 1)
    self.assertEqual(server.stats()['connections'], 0)

  async def test_concurrent_frame_work_is_rejected_and_original_can_finish(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    await server.start_server()
    client = FrameSyncClientAsync('127.0.0.1', server.listen_port)
    self.addAsyncCleanup(client.close_async)
    await client.connect_async()
    client.send_ready()
    await self.until(server._runtime.all_ready)
    first = asyncio.create_task(server.run_one_frame(timeout_ms=1000))
    await self.until(lambda: server._runtime.collecting)
    with self.assertRaisesRegex(RuntimeError, 'already in progress'):
      await server.run_one_frame()
    client.send_frame_entries(0, [(0, wire.SlotInput(1, 0, 0))])
    self.assertEqual(await first, (0, [wire.SlotInput(1, 0, 0)]))
    self.assertTrue(server.stats()['running'])

  async def test_idle_actual_async_client_keeps_waiting_session_alive(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle,
                                  limits=ServerLimits(idle_timeout=.2, heartbeat_interval=.03))
    self.addAsyncCleanup(server.close_async)
    await server.start_server()
    client = FrameSyncClientAsync('127.0.0.1', server.listen_port, limits=ClientLimits(idle_timeout=.2))
    self.addAsyncCleanup(client.close_async)
    await client.connect_async()
    client.send_ready()
    await self.until(server._runtime.all_ready)
    await asyncio.sleep(.65)
    self.assertEqual(await server.get_connected_client_count(), 1)
    self.assertFalse(client.is_disconnected())
    self.assertEqual(await server.get_frame_id(), 0)

  async def test_stop_rejects_immediate_frame_before_cleanup_gets_a_tick(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    await server.start_server()
    engine = server.get_env()
    server.stop()
    # 2026-09-10: the public contract exposes a fixed failure reason.
    # with self.assertRaisesRegex(RuntimeError, 'not running'):
    with self.assertRaises(ServerFailure) as failure:
      await server.run_one_frame(timeout_ms=0)
    self.assertEqual(failure.exception.reason, 'closed')
    self.assertEqual(engine.frames, 0)
    await server.close_async()
    self.assertEqual(engine.closed, 1)

  async def test_initialized_engine_cannot_move_to_a_foreign_event_loop_thread(self):
    server = FrameSyncServerAsync(listen_host='127.0.0.1', listen_port=0, engine_factory=EngineOracle)
    self.addAsyncCleanup(server.close_async)
    server.start()
    engine = server.get_env()

    def foreign_start():
      async def attempt():
        with self.assertRaisesRegex(RuntimeError, 'owner thread'):
          await server.start_server()
      asyncio.run(attempt())

    await asyncio.to_thread(foreign_start)
    self.assertEqual(engine.closed, 0)
    self.assertIsNone(server._runtime.loop)
    await server.start_server()
    await server.run_one_frame(timeout_ms=0)
    self.assertEqual(engine.frames, 1)
    await server.close_async()
    self.assertEqual(engine.closed, 1)


if __name__ == '__main__':
  unittest.main()
