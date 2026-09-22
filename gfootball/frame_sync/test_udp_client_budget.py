# Copyright 2026 Google LLC
"""Real UDP sockets and an independent wire peer; no GameEnv simulation."""
import select
import socket
import struct
import threading
import time
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_udp import FrameSyncUDPClient, ReliableUDPClient, UDPLimits
from gfootball.frame_sync.test_udp_budget import data_packet, ack_packet


def wait_for(predicate, timeout=1.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    if predicate():
      return True
    time.sleep(.002)
  return bool(predicate())


class WirePeer:
  """Small deterministic peer fixture; manually encodes DATA/ACK framing.

  Tests can drop first transmissions, reorder bootstrap fragments and inject
  exact bytes. This peer does not import/use the production UDP state machine.
  """
  # 2026-09-10: allow one human slot with a second authoritative bot slot.
  # def __init__(self, bootstrap=True, fragmented=False, heartbeats=True, slots=1):
  def __init__(self, bootstrap=True, fragmented=False, heartbeats=True, slots=1, controlled_slots=None):
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.sock.bind(('127.0.0.1', 0))
    self.sock.setblocking(False)
    self.endpoint = self.sock.getsockname()
    self.lock = threading.RLock()
    self.stopped = threading.Event()
    self.client = None
    self.bootstrap = bootstrap
    self.fragmented = fragmented
    self.heartbeats = heartbeats
    self.slots = slots
    self.controlled_slots = list(range(slots)) if controlled_slots is None else list(controlled_slots)
    self.next_seq = 0
    self.pending = {}
    self.incoming = {}
    self.next_incoming = 0
    self.received = []
    self.ready = False
    self.hello = False
    self.acknowledge = True
    self.errors = []
    self.worker = threading.Thread(target=self._run, name='football-udp-test-peer')
    self.worker.start()

  def send(self, payload, *, drop_first=False, copies=1):
    with self.lock:
      seq = self.next_seq
      self.next_seq += 1
      packet = data_packet(seq, payload)
      self.pending[seq] = packet, time.monotonic()
      if not drop_first:
        for _ in range(copies):
          self.sock.sendto(packet, self.client)
      return seq

  def raw(self, packet):
    with self.lock:
      self.sock.sendto(packet, self.client)

  def _bootstrap(self):
    session = wire.pack_session_start(42, min(11, self.slots), max(0, self.slots - 11))
    # 2026-09-10: protocol fixture distinguishes total and owned slots.
    # slots = wire.pack_slot_assignment(list(range(self.slots)))
    slots = wire.pack_slot_assignment(self.controlled_slots)
    if self.fragmented:
      self.send(session[:3], drop_first=True)
      self.send(session[3:] + slots, copies=2)
    else:
      self.send(session)
      self.send(slots)

  def _run(self):
    next_heartbeat = time.monotonic() + .05
    try:
      while not self.stopped.is_set():
        readable, _, _ = select.select([self.sock], [], [], .005)
        with self.lock:
          if readable:
            try:
              packet, remote = self.sock.recvfrom(1201)
            except OSError as error:
              if getattr(error, 'winerror', None) == 10054:
                continue  # Expected peer-close ICMP on Windows.
              raise
            if self.client is None:
              self.client = remote
            if remote != self.client:
              continue
            if len(packet) == 5 and packet[0] == 255:
              self.pending.pop(struct.unpack_from('<I', packet, 1)[0], None)
            elif len(packet) >= 7 and packet[0] == 0:
              _, seq, length = struct.unpack_from('<BIH', packet)
              if len(packet) != length + 7:
                raise AssertionError('Client emitted an invalid DATA packet')
              if self.acknowledge:
                self.sock.sendto(ack_packet(seq), remote)
              if seq >= self.next_incoming:
                self.incoming[seq] = packet[7:]
              while self.next_incoming in self.incoming:
                payload = self.incoming.pop(self.next_incoming)
                self.next_incoming += 1
                self.received.append(payload)
                if payload[0] == wire.MessageType.VersionNegotiate and not self.hello:
                  self.hello = True
                  if self.bootstrap:
                    self._bootstrap()
                elif payload[0] == wire.MessageType.Ready:
                  self.ready = True
          now = time.monotonic()
          for seq, (packet, sent) in list(self.pending.items()):
            if now - sent >= .06:
              self.sock.sendto(packet, self.client)
              self.pending[seq] = packet, now
          if self.ready and self.heartbeats and now >= next_heartbeat:
            self.send(wire.pack_heartbeat(0, int(now * 1000) & 0xffffffff))
            next_heartbeat = now + .05
    except BaseException as error:
      self.errors.append(error)

  def messages(self, kind):
    with self.lock:
      return [packet for packet in self.received if packet[0] == kind]

  def close(self):
    self.stopped.set()
    self.worker.join(1)
    self.sock.close()
    if self.worker.is_alive():
      raise AssertionError('UDP fixture worker leaked')
    if self.errors:
      raise self.errors[0]


class UDPClientTest(unittest.TestCase):
  def setUp(self):
    self.clients = []
    self.peers = []

  def tearDown(self):
    for peer in self.peers:
      peer.close()
    for client in self.clients:
      client.close()
      self.assertFalse(client.stats()['worker_alive'])
      self.assertIsNone(client.stats()['local_endpoint'])
      self.assertEqual(client.stats()['send_bytes'], 0)
      stats = client.stats()['udp']
      if stats is not None:
        self.assertEqual((stats['pending_bytes'], stats['receive_bytes'], stats['receipt_bytes']), (0, 0, 0))

  def make(self, *, peer_options=None, **options):
    peer = WirePeer(**(peer_options or {}))
    self.peers.append(peer)
    client = FrameSyncUDPClient(*peer.endpoint, **options)
    self.clients.append(client)
    return client, peer

  def connected(self, **options):
    client, peer = self.make(**options)
    session, slots = client.connect()
    self.assertEqual(session, (42, min(11, peer.slots), max(0, peer.slots - 11)))
    # 2026-09-10: verify the actual assignment for partial-control sessions.
    # self.assertEqual(slots, list(range(peer.slots)))
    self.assertEqual(slots, peer.controlled_slots)
    self.assertTrue(client.send_ready())
    self.assertTrue(wait_for(lambda: peer.ready))
    return client, peer

  def test_public_classes_are_actual_bounded_runtime(self):
    self.assertEqual(FrameSyncUDPClient.__module__, 'gfootball.frame_sync.client_udp_runtime')
    self.assertEqual(ReliableUDPClient.__module__, 'gfootball.frame_sync.udp_transport')
    for args in (('', 1), ('127.0.0.1', 0), ('127.0.0.1', 99999), ('127.0.0.1', True)):
      with self.assertRaises(ValueError):
        FrameSyncUDPClient(*args)
    with self.assertRaises(ValueError):
      FrameSyncUDPClient('127.0.0.1', 1, handshake='server_first')

  def test_fragmented_reordered_duplicate_handshake_and_explicit_ready(self):
    client, peer = self.make(peer_options=dict(fragmented=True))
    self.assertEqual(client.connect(), ((42, 1, 0), [0]))
    self.assertFalse(peer.ready)
    self.assertEqual(client.stats()['phase'], 'ready')
    self.assertTrue(client.send_ready())
    self.assertTrue(client.send_ready())
    self.assertTrue(wait_for(lambda: peer.ready))
    self.assertEqual(len(peer.messages(wire.MessageType.Ready)), 1)
    self.assertGreaterEqual(client.stats()['udp']['duplicates'], 1)
    self.assertIsNone(client._channel._retransmit_thread)
    self.assertFalse(client._recv_thread.daemon)

  def test_actual_input_and_22_slot_authority_bytes(self):
    values = [wire.SlotInput(0.5, -0.5, i) for i in range(22)]
    client, peer = self.connected(peer_options=dict(slots=22),
                                 controlled_slots_callback=lambda: list(enumerate(values)))
    self.assertTrue(client.send_frame_input(0))
    self.assertTrue(wait_for(lambda: peer.messages(wire.MessageType.FrameInput)))
    self.assertEqual(peer.messages(wire.MessageType.FrameInput), [wire.pack_client_frame_input(0, list(enumerate(values)))])
    peer.send(wire.pack_authoritative_frame(0, values))
    self.assertTrue(wait_for(client.has_authoritative_frame))
    self.assertEqual(client.pop_authoritative_frame(), (0, values))
    self.assertEqual(client.stats()['authority_bytes'], 0)
    self.assertEqual(client.stats()['timestamps'], 0)
    self.assertEqual(len(client.get_rtt_samples()), 1)

  def test_ordered_authority_after_lost_first_datagram_and_duplicates(self):
    client, peer = self.connected()
    value = wire.default_slot_input()
    peer.send(wire.pack_authoritative_frame(0, [value]), drop_first=True)
    for frame in range(1, 40):
      peer.send(wire.pack_authoritative_frame(frame, [value]), copies=2)
    self.assertTrue(wait_for(lambda: client.stats()['authority_frames'] == 40))
    self.assertEqual([client.pop_authoritative_frame()[0] for _ in range(40)], list(range(40)))
    self.assertFalse(client.is_disconnected(), client.failure_reason)
    self.assertGreater(client.stats()['udp']['duplicates'], 0)

  def test_kernel_filters_foreign_endpoint_before_reliable_decoder(self):
    client, peer = self.connected()
    before = client.stats()['udp']['invalid']
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as foreign:
      for _ in range(10):
        foreign.sendto(data_packet(2, b'\xfe'), client.stats()['local_endpoint'])
    peer.send(wire.pack_authoritative_frame(0, [wire.default_slot_input()]))
    self.assertTrue(wait_for(client.has_authoritative_frame))
    self.assertFalse(client.is_disconnected())
    self.assertEqual(client.stats()['udp']['invalid'], before)

  def test_invalid_datagrams_and_oversized_udp_do_not_poison_stream(self):
    client, peer = self.connected()
    # 2026-09-10: a 1201-byte datagram crosses the protocol limit while fitting
    # the local path MTU; larger datagrams may be dropped before recvfrom.
    # for packet in (b'', b'\xff', b'\xfe', data_packet(300, b'x' * 2000)):
    for packet in (b'', b'\xff', b'\xfe', data_packet(300, b'x' * 1194),
                   data_packet(300, b'x' * 2000)):
      peer.raw(packet)
    peer.send(wire.pack_authoritative_frame(0, [wire.default_slot_input()]))
    self.assertTrue(wait_for(client.has_authoritative_frame))
    self.assertFalse(client.is_disconnected(), client.failure_reason)
    self.assertGreaterEqual(client.stats()['udp']['invalid'], 4)

  def test_hashes_match_requested_frame_and_mismatch_closes(self):
    client, peer = self.connected()
    peer.send(wire.pack_state_hash(0, wire.compute_state_hash(b'a')) +
              wire.pack_state_hash(1, wire.compute_state_hash(b'b')))
    self.assertTrue(wait_for(lambda: client.stats()['hashes'] == 2))
    self.assertTrue(client.check_state_hash(1, b'b'))
    self.assertEqual(client.stats()['hashes'], 1)
    self.assertFalse(client.check_state_hash(0, b'wrong'))
    self.assertEqual(client.failure_reason, 'hash_mismatch')

  def test_authority_consumer_backlog_is_terminal_and_releases_queues(self):
    client, peer = self.connected(limits=ClientLimits(authority_frames=2))
    for i in range(3):
      peer.send(wire.pack_authoritative_frame(i, [wire.default_slot_input()]))
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'authority_capacity')
    self.assertEqual(client.stats()['authority_bytes'], 0)

  def test_bad_authority_count_and_unknown_message_fail_promptly(self):
    for payload, reason in ((struct.pack('<BIH', 3, 0, 65535), 'invalid_authority'),
                            (b'\xfe', 'unsupported_message'),
                            (wire.pack_authoritative_frame(1, [wire.default_slot_input()]), 'invalid_authority'),
                            (wire.pack_authoritative_frame(0, [wire.SlotInput(float('nan'), 0, 0)]), 'invalid_input')):
      with self.subTest(reason=reason):
        client, peer = self.connected()
        peer.send(payload)
        self.assertTrue(wait_for(client.is_disconnected))
        self.assertEqual(client.failure_reason, reason)

  def test_hash_capacity_and_conflicting_duplicate_hash_fail(self):
    for packet, reason in ((wire.pack_state_hash(0, 1) + wire.pack_state_hash(1, 2), 'hash_capacity'),
                           (wire.pack_state_hash(0, 1) + wire.pack_state_hash(0, 2), 'invalid_hash')):
      client, peer = self.connected(limits=ClientLimits(hashes=1))
      peer.send(packet)
      self.assertTrue(wait_for(client.is_disconnected))
      self.assertEqual(client.failure_reason, reason)

  def test_heartbeat_is_real_received_progress_independent_of_poll_frequency(self):
    client, peer = self.connected(limits=ClientLimits(idle_timeout=.15))
    self.assertTrue(wait_for(lambda: client.stats()['received_heartbeats'] >= 6))
    for _ in range(1000):
      client.tick_disconnect_detection()
    self.assertFalse(client.is_disconnected(), client.failure_reason)
    self.assertGreaterEqual(len(peer.messages(wire.MessageType.Heartbeat)), 4)

  def test_ack_and_partial_application_bytes_do_not_extend_idle_deadline(self):
    client, peer = self.connected(peer_options=dict(heartbeats=False), limits=ClientLimits(idle_timeout=.12))
    until = time.monotonic() + .4
    while not client.is_disconnected() and time.monotonic() < until:
      peer.raw(ack_packet(0))
      time.sleep(.01)
    self.assertTrue(client.is_disconnected())
    self.assertEqual(client.failure_reason, 'idle_timeout')
    client, peer = self.connected(peer_options=dict(heartbeats=False), limits=ClientLimits(idle_timeout=.12))
    peer.send(bytes([wire.MessageType.Heartbeat]))
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'idle_timeout')

  def test_ready_timeout_is_automatic_without_ui_ticks(self):
    client, _ = self.make(limits=ClientLimits(ready_timeout=.05))
    client.connect()
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'ready_timeout')

  def test_retry_exhaustion_and_queued_write_deadline(self):
    client, peer = self.connected(udp_limits=UDPLimits(max_retries=0))
    with peer.lock:
      peer.acknowledge = False
    client.send_frame_entries(0, [(0, wire.default_slot_input())])
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'udp_retry_exhausted')
    client, peer = self.connected(limits=ClientLimits(write_timeout=.04), udp_limits=UDPLimits(pending_packets=1))
    self.assertTrue(wait_for(lambda: client.stats()['udp']['pending_packets'] == 0))
    with peer.lock:
      peer.acknowledge = False
    client.send_frame_entries(0, [(0, wire.default_slot_input())])
    client.send_frame_entries(1, [(0, wire.default_slot_input())])
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'write_timeout')

  def test_invalid_local_inputs_are_terminal_before_sending(self):
    client, peer = self.connected()
    with self.assertRaises(ValueError):
      client.send_frame_entries(0, [(1, wire.default_slot_input())])
    self.assertEqual(client.failure_reason, 'invalid_input')
    self.assertEqual(peer.messages(wire.MessageType.FrameInput), [])

  def test_failed_handshake_joins_worker_and_releases_socket(self):
    client, _ = self.make(peer_options=dict(bootstrap=False), limits=ClientLimits(handshake_timeout=.05))
    with self.assertRaisesRegex(ClientFailure, 'handshake_timeout'):
      client.connect()
    self.assertFalse(client.stats()['worker_alive'])
    self.assertIsNone(client.stats()['local_endpoint'])
    self.assertEqual(client.stats()['udp']['pending_bytes'], 0)

  def test_close_cancels_pending_handshake_and_generation(self):
    client, peer = self.make(peer_options=dict(bootstrap=False))
    errors = []
    def connect():
      try:
        client.connect()
      except ClientFailure as error:
        errors.append(error.reason)
    worker = threading.Thread(target=connect, name='football-udp-test-connect')
    worker.start()
    try:
      self.assertTrue(wait_for(lambda: peer.hello))
      start = time.monotonic()
      client.close()
      worker.join(1)
      self.assertLess(time.monotonic() - start, 1)
      self.assertFalse(worker.is_alive())
      self.assertEqual(errors, ['closed'])
    finally:
      client.close()
      worker.join(1)

  def test_connection_churn_joins_every_owned_worker(self):
    for _ in range(30):
      client, peer = self.connected()
      worker = client._recv_thread
      client.reset_for_reconnect()
      self.assertFalse(worker.is_alive())
      peer.close()
      self.peers.remove(peer)
      self.assertIsNone(client.stats()['local_endpoint'])

  def test_close_during_input_callback_cannot_send_into_new_generation(self):
    client, peer = self.connected()
    entered, release = threading.Event(), threading.Event()
    results = []
    def callback():
      entered.set()
      if not release.wait(1):
        raise AssertionError('callback release timeout')
      return [(0, wire.default_slot_input())]
    client.controlled_slots_callback = callback
    worker = threading.Thread(target=lambda: results.append(client.send_frame_input(0)), name='football-udp-test-input')
    worker.start()
    try:
      self.assertTrue(entered.wait(1))
      client.close()
      fresh = WirePeer()
      self.peers.append(fresh)
      client.host, client.port = fresh.endpoint
      client.connect()
      client.send_ready()
    finally:
      release.set()
      worker.join(1)
    self.assertEqual(results, [False])
    self.assertEqual(peer.messages(wire.MessageType.FrameInput), [])
    self.assertEqual(fresh.messages(wire.MessageType.FrameInput), [])

  def test_client_queue_admission_is_bounded_before_worker_drain(self):
    client, _ = self.connected(limits=ClientLimits(send_messages=2))
    self.assertTrue(wait_for(lambda: client.stats()['send_messages'] == 0))
    with client._lock:
      self.assertTrue(client.send_frame_entries(0, [(0, wire.default_slot_input())]))
      self.assertTrue(client.send_frame_entries(1, [(0, wire.default_slot_input())]))
      self.assertFalse(client.send_frame_entries(2, [(0, wire.default_slot_input())]))
    self.assertEqual(client.failure_reason, 'send_capacity')
    self.assertEqual(client.stats()['send_bytes'], 0)

  def test_gap_failure_stops_stream_without_returning_future_authority(self):
    client, peer = self.connected(udp_limits=UDPLimits(gap_timeout=.05))
    with peer.lock:
      peer.next_seq += 1  # Permanently lose the next DATA sequence.
      peer.send(wire.pack_authoritative_frame(1, [wire.default_slot_input()]), copies=2)
    self.assertTrue(wait_for(client.is_disconnected))
    self.assertEqual(client.failure_reason, 'udp_gap_timeout')
    self.assertIsNone(client.pop_authoritative_frame())

  def test_unbounded_input_generator_stops_after_23_entries(self):
    client, _ = self.connected()
    samples = []
    def entries():
      while True:
        samples.append(1)
        yield 0, wire.default_slot_input()
    with self.assertRaises(ValueError):
      client.send_frame_entries(0, entries())
    self.assertEqual(len(samples), 23)
    self.assertEqual(client.failure_reason, 'invalid_input')

  def test_exhausted_generation_still_closes_socket_and_worker(self):
    client, _ = self.connected()
    worker = client._recv_thread
    with client._lock:
      client._generation = 0xffffffffffffffff
    client.close()
    self.assertFalse(worker.is_alive())
    self.assertIsNone(client.stats()['local_endpoint'])
    with self.assertRaisesRegex(ClientFailure, 'generation_exhausted'):
      client.connect()

  def test_real_udp_logic_rollback_and_three_confirmed_hashes(self):
    from gfootball.frame_sync.test_client_logic_budget import SocketScenario, inputs, packed
    case = SocketScenario()  # Explicit integer reducer, not native GameEnv.
    def forbidden():
      raise AssertionError('Transport must not resample logic input')
    client, peer = self.connected(peer_options=dict(slots=2, controlled_slots=[0]),
                                 controlled_slots_callback=forbidden)
    case.build_loop(client)
    for _ in range(3):
      case.loop.run_one_tick()
    self.assertTrue(wait_for(lambda: len(peer.messages(wire.MessageType.FrameInput)) == 3))
    for packet in peer.messages(wire.MessageType.FrameInput):
      frame, entries = wire.unpack_client_frame_input(packet)
      case.received.append((frame, entries, packet))
    output = b''
    for frame in range(3):
      authoritative = inputs(-.75 + frame / 8, .5)
      case.reference.step_with_input(packed(authoritative))
      output += wire.pack_authoritative_frame(frame, authoritative)
      output += wire.pack_state_hash(frame, wire.compute_state_hash(case.reference.get_state_digest()))
    peer.send(output[:12], drop_first=True)
    peer.send(output[12:31], copies=2)
    peer.send(output[31:], copies=2)
    self.assertTrue(wait_for(lambda: client.stats()['authority_frames'] == 3 and client.stats()['hashes'] == 3))
    case.loop.run_one_tick()
    self.assertTrue(wait_for(lambda: len(peer.messages(wire.MessageType.FrameInput)) == 4))
    packet = peer.messages(wire.MessageType.FrameInput)[3]
    frame, entries = wire.unpack_client_frame_input(packet)
    case.received.append((frame, entries, packet))
    case.verify(self)

  def exercise_fixture(self, *, authority=True, state_hash=True, heartbeats=True):
    from gfootball.frame_sync.test_e2e_udp import exercise_session
    client, peer = self.make(peer_options=dict(heartbeats=heartbeats))
    errors = []
    def produce():
      try:
        if not wait_for(lambda: peer.ready):
          raise AssertionError('Fixture never received Ready')
        if authority:
          for frame in range(10):
            peer.send(wire.pack_authoritative_frame(frame, [wire.default_slot_input()]))
        if state_hash:
          peer.send(wire.pack_state_hash(0, 1234))
      except BaseException as error:
        errors.append(error)
    worker = threading.Thread(target=produce, name='football-udp-test-producer')
    worker.start()
    try:
      return exercise_session(client, timeout=.15)
    finally:
      worker.join(1)
      self.assertFalse(worker.is_alive())
      self.assertEqual(errors, [])

  def test_cli_requires_all_three_actual_wire_observations(self):
    result = self.exercise_fixture()
    self.assertEqual(result['authority_frames'], 10)
    self.assertEqual(result['first_hash'], (0, 1234))
    self.assertGreaterEqual(result['received_heartbeats'], 1)

  def test_cli_rejects_missing_authority_hash_or_heartbeat(self):
    for missing in ('authority', 'state_hash', 'heartbeats'):
      with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, 'UDP evidence deadline'):
        self.exercise_fixture(**{missing: False})


if __name__ == '__main__':
  unittest.main()
