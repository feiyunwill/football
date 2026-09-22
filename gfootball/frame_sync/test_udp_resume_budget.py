"""Real UDP sockets and bounded recovery; engine reducers are explicitly not GameEnv."""
from dataclasses import replace
import select
import socket
import struct
import threading
import time
import unittest

from gfootball.frame_sync import protocol as wire, udp_session as session
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_logic import LogicLimits
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.client_udp import ResumableFrameSyncUDPClient, ReconnectingFrameSyncUDPClient
from gfootball.frame_sync.server_udp import FrameSyncUDPServer
from gfootball.frame_sync.server_state import ServerLimits
from gfootball.frame_sync.test_reconnect_budget import Replica
from gfootball.frame_sync.test_server_budget import EngineOracle, until
from gfootball.frame_sync.udp_state import UDPLimits, UDPState

MEASUREMENTS = {}


class FaultRelay:
  """Real loopback proxy: one dropped first send, reordering and duplicate DATA."""
  def __init__(self, port):
    self.front, self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.front.bind(('127.0.0.1', 0))
    self.back.connect(('127.0.0.1', port))
    self.port = self.front.getsockname()[1]
    self.stop = threading.Event()
    self.errors, self.seen = [], set()
    self.dropped = self.duplicated = self.reordered = self.maximum = 0
    self.thread = threading.Thread(target=self.run, name='football-udp-test-relay')
    self.thread.start()

  def run(self):
    address, held, held_at = None, None, 0
    try:
      while not self.stop.is_set():
        readable, _, _ = select.select([self.front, self.back], [], [], .005)
        for sock in readable:
          try:
            packet, source = sock.recvfrom(1201)
          except ConnectionResetError:
            continue  # A production peer may already have closed during cleanup.
          self.maximum = max(self.maximum, len(packet))
          if len(packet) > 1200:
            raise AssertionError('Oversized UDP datagram')
          if sock is self.front:
            address = source
            self.back.send(packet)
          elif address is not None:
            if len(packet) > 16 and packet[0] == 0x74 and packet[9] == 0:
              epoch, seq = struct.unpack_from('<Q', packet, 1)[0], struct.unpack_from('<I', packet, 10)[0]
              key = epoch, seq
              first = key not in self.seen
              self.seen.add(key)
              if len(self.seen) > 4096:
                raise AssertionError('Relay fixture packet bound exceeded')
              if first and seq % 17 == 3:
                self.dropped += 1
                continue
              if first and seq % 23 == 4 and held is None:
                held, held_at = packet, time.monotonic()
                continue
              self.front.sendto(packet, address)
              if first and seq % 19 == 2:
                self.front.sendto(packet, address)
                self.duplicated += 1
              if held is not None:
                self.front.sendto(held, address)
                self.reordered += 1
                held = None
            else:
              self.front.sendto(packet, address)
        if held is not None and time.monotonic() - held_at > .025:
          self.front.sendto(held, address)
          held = None
    except BaseException as error:
      self.errors.append(error)
    finally:
      self.front.close()
      self.back.close()

  def close(self):
    self.stop.set()
    self.thread.join(2)
    if self.thread.is_alive():
      raise AssertionError('Relay owner leaked')
    if self.errors:
      raise self.errors[0]


class CookieTest(unittest.TestCase):
  def test_delivery_ack_retains_sender_backpressure_across_a_gap(self):
    limits = UDPLimits(pending_packets=3, receive_packets=3)
    sender, receiver = UDPState(limits), UDPState(limits, ack_on_delivery=True)
    for value in (b'a', b'b', b'c'):
      sender.enqueue(value, 0)
    packets = sender.due(0)
    for seq, packet in packets:
      sender.mark_sent(seq, 0)
    for seq, packet in packets[1:]:
      self.assertIsNone(receiver.receive(packet, .01))
    self.assertIsNone(receiver.next_delivery())
    self.assertIsNone(sender.enqueue(b'd', .02))
    self.assertIsNone(receiver.receive(packets[0][1], .03))
    for value in (b'a', b'b', b'c'):
      self.assertEqual(receiver.next_delivery(), value)
      sender.receive(receiver.complete_delivery(), .04)
    self.assertEqual(sender.pending_bytes, 0)
    self.assertEqual(receiver.receive_bytes, 0)
    self.assertEqual(receiver.receive(packets[0][1], .05), b'\xff' + bytes(4))
    self.assertIsNone(receiver.next_delivery())

  def test_ambiguous_half_space_sequence_is_rejected(self):
    state = UDPState()
    with self.assertRaisesRegex(ClientFailure, 'udp_sequence_window'):
      state.receive(struct.pack('<BIH', 0, 0x80000000, 1) + b'x', 0)
    self.assertEqual(state.receive_bytes, 0)

  def test_wire_contract_and_epoch_isolation(self):
    packet = session.hello(0x0102030405060708)
    self.assertEqual(packet, b'\x70\x08\x07\x06\x05\x04\x03\x02\x01' + bytes(20))
    data = session.wrap(3, struct.pack('<BIH', 0, 0, 1) + b'x')
    self.assertIsNone(session.unwrap(4, data))
    self.assertEqual(session.unwrap(3, data), b'\x00' + bytes(4) + b'\x01\x00x')
    for bad in (b'', bytes(1201), packet[:-1], packet + b'x'):
      self.assertIsNone(session.parse_cookie(bad))

  def test_cookie_address_epoch_and_time_binding(self):
    authority = session.CookieAuthority()
    packet = authority.challenge(('127.0.0.1', 1000), 3, 90)
    _, epoch, bucket, cookie = session.parse_cookie(packet)
    self.assertTrue(authority.verify(('127.0.0.1', 1000), epoch, bucket, cookie, 119))
    self.assertTrue(authority.verify(('127.0.0.1', 1000), epoch, bucket, cookie, 149))
    for address, e, now in ((('127.0.0.1', 1001), 3, 90), (('127.0.0.2', 1000), 3, 90),
                            (('127.0.0.1', 1000), 4, 90), (('127.0.0.1', 1000), 3, 150)):
      self.assertFalse(authority.verify(address, e, bucket, cookie, now))

  def test_constant_rate_budget_and_strict_limits(self):
    authority = session.CookieAuthority(session.CookieLimits(burst_requests=2, requests_per_second=1))
    self.assertEqual([authority.allow(1) for _ in range(1000)].count(True), 2)
    self.assertFalse(authority.allow(0))
    self.assertTrue(authority.allow(2))
    for kwargs in ({'recent_epochs': 0}, {'period': float('nan')}, {'burst_requests': True}):
      with self.assertRaises(ValueError):
        session.CookieLimits(**kwargs)
    for epoch in (0, -1, True, 2**64):
      with self.assertRaises(ValueError):
        session.hello(epoch)


class UDPResumeTest(unittest.TestCase):
  def setUp(self):
    self.clients, self.servers, self.relays = [], [], []

  def tearDown(self):
    errors = []
    for client in self.clients:
      try:
        client.close()
        self.assertFalse(client.stats()['worker_alive'])
        self.assertEqual(client.stats()['snapshot_bytes'], 0)
      except BaseException as error:
        errors.append(error)
    for relay in self.relays:
      try:
        relay.close()
      except BaseException as error:
        errors.append(error)
    for server in self.servers:
      try:
        server.stop()
        self.assertFalse(server._thread.is_alive())
        self.assertEqual(server._runtime._addresses, {})
        self.assertEqual(server._runtime._epochs, {})
      except BaseException as error:
        errors.append(error)
    if errors:
      raise errors[0]

  def server(self, **options):
    options.setdefault('engine_factory', EngineOracle)
    options.setdefault('limits', ServerLimits(heartbeat_interval=.05))
    server = FrameSyncUDPServer('127.0.0.1', 0, state_hash_interval=1, **options)
    self.servers.append(server)
    server.start()
    return server

  def client(self, server, **options):
    client = ResumableFrameSyncUDPClient('127.0.0.1', server.listen_port, **options)
    self.clients.append(client)
    return client

  def drop(self, server):
    server._call(lambda: [server._runtime._drop(peer, 'test_link_loss') for peer in tuple(server._runtime.peers.values())])
    until(lambda: server.stats()['connections'] == 0)

  def raw(self, server):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.addCleanup(sock.close)
    sock.connect(('127.0.0.1', server.listen_port))
    sock.settimeout(.5)
    return sock

  def confirm(self, sock, epoch):
    sock.send(session.hello(epoch))
    challenge = sock.recv(1201)
    self.assertEqual(len(challenge), 29)
    self.assertEqual(challenge[0], 0x71)
    confirm = b'\x72' + challenge[1:]
    sock.send(confirm)
    self.assertEqual(sock.recv(1201), b'\x73' + challenge[1:])
    return confirm

  def test_unverified_requests_allocate_no_peers_and_no_amplification(self):
    server = self.server()
    sock = self.raw(server)
    for epoch in range(1, 21):
      request = session.hello(epoch)
      sock.send(request)
      self.assertEqual(len(sock.recv(1201)), len(request))
    sock.send(b'\x72' + session.hello(22)[1:])
    until(lambda: server.stats()['cookie_rejected'] == 1)
    stats = server.stats()
    self.assertEqual((stats['connections'], stats['sessions'], stats['epoch_history']), (0, 0, 0))

  def test_confirm_replay_and_old_epoch_never_reset_live_sequence(self):
    server = self.server()
    sock = self.raw(server)
    confirm = self.confirm(sock, 10)
    sock.send(confirm)
    self.assertEqual(sock.recv(1201), b'\x73' + confirm[1:])
    self.assertEqual(server.stats()['accepted'], 1)
    sock.send(session.wrap(11, b'\x00' + bytes(4) + b'\x05\x00' + wire.pack_version_negotiate(3, 3)))
    until(lambda: server.stats()['epoch_dropped'] == 1)
    self.assertEqual(server.stats()['sessions'], 0)
    self.drop(server)
    sock.send(confirm)
    until(lambda: server.stats()['cookie_rejected'] == 1)
    self.assertEqual(server.stats()['accepted'], 1)
    self.confirm(sock, 12)
    self.assertEqual(server.stats()['accepted'], 2)

  def test_tombstone_capacity_refuses_instead_of_evicting(self):
    server = self.server(cookie_limits=session.CookieLimits(recent_epochs=1))
    sock = self.raw(server)
    confirm = self.confirm(sock, 1)
    self.drop(server)
    sock.send(session.hello(2))
    challenge = sock.recv(1201)
    sock.send(b'\x72' + challenge[1:])
    until(lambda: server.stats()['rejected'] == 1)
    sock.send(confirm)
    until(lambda: server.stats()['rejected'] == 2)
    self.assertEqual(server.stats()['epoch_history'], 1)

  def test_live_epoch_survives_cookie_expiry_and_refreshed_confirm_cannot_reopen(self):
    server = self.server(cookie_limits=session.CookieLimits(period=.1))
    first, second = self.raw(server), self.raw(server)
    self.confirm(first, 1)
    time.sleep(.22)
    self.confirm(second, 2)  # Prunes only expired closed epochs.
    confirm = self.confirm(first, 1)  # Refreshes the existing epoch's cookie validity.
    self.assertEqual(server.stats()['accepted'], 2)
    self.drop(server)
    first.send(confirm)
    until(lambda: server.stats()['cookie_rejected'] > 0)
    self.assertEqual(server.stats()['accepted'], 2)

  def test_expired_deadline_sends_nothing_and_joins(self):
    server = self.server()
    client = self.client(server)
    with self.assertRaisesRegex(ClientFailure, 'recovery_timeout'):
      client.connect(deadline=time.monotonic() - 1)
    self.assertEqual(server.stats()['cookie_challenges'], 0)

  def test_close_during_cookie_wait_stops_the_single_connection_owner(self):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blackhole:
      blackhole.bind(('127.0.0.1', 0))
      blackhole.settimeout(1)
      client = ResumableFrameSyncUDPClient('127.0.0.1', blackhole.getsockname()[1])
      self.clients.append(client)
      errors = []
      def connect():
        try:
          client.connect()
        except BaseException as error:
          errors.append(error)
      owner = threading.Thread(target=connect, name='football-udp-test-connect')
      owner.start()
      try:
        self.assertEqual(len(blackhole.recv(1201)), 29)
        client.close()
      finally:
        client.close()
        owner.join(2)
      self.assertFalse(owner.is_alive())
      self.assertEqual(len(errors), 1)
      self.assertEqual(errors[0].reason, 'closed')
      self.assertIsNone(client._sock)

  def test_maximum_snapshot_real_loss_reordering_duplicates_and_ready(self):
    payload = bytes(range(256)) * 4096
    class LargeEngine(EngineOracle):
      def get_state(self, unused=''):
        return payload
    server = self.server(engine_factory=LargeEngine)
    first = self.client(server)
    first.connect()
    token = first.session_token
    first.send_ready()
    until(server.all_clients_ready)
    server.run_one_frame(0)
    first.close()
    self.drop(server)
    relay = FaultRelay(server.listen_port)
    self.relays.append(relay)
    client = ResumableFrameSyncUDPClient('127.0.0.1', relay.port)
    self.clients.append(client)
    started = time.monotonic()
    client.connect(resume_token=token, expected_session=(42, 1, 0), expected_slots=(0,))
    MEASUREMENTS['snapshot'] = dict(bytes=len(payload), seconds=time.monotonic() - started,
        dropped_first_transmissions=relay.dropped, duplicate_datagrams=relay.duplicated,
        reordered_datagrams=relay.reordered, maximum_datagram_bytes=relay.maximum)
    self.assertEqual(client.take_resume_snapshot(), (1, payload))
    self.assertIsNone(client.take_resume_snapshot())
    self.assertFalse(server.all_clients_ready())
    client.send_ready()
    until(lambda: client.resume_handback_complete)
    self.assertGreater(relay.dropped, 20)
    self.assertGreater(relay.duplicated, 20)
    self.assertGreater(relay.reordered, 20)
    self.assertEqual(relay.maximum, 1200)
    stats = server.stats()
    self.assertLessEqual(stats['udp_pending_bytes'], UDPLimits().pending_bytes)
    self.assertLessEqual(client.stats()['udp']['receive_bytes'], UDPLimits().receive_bytes)

  # 2026-09-10: name the actual unacknowledged session handshake under test.
  # def test_unacknowledged_snapshot_is_bounded_and_expires(self):
  def test_unacknowledged_session_is_bounded_and_expires(self):
    server = self.server(udp_limits=UDPLimits(pending_packets=2, pending_bytes=256, delivery_timeout=.12))
    sock = self.raw(server)
    self.confirm(sock, 7)
    hello = wire.pack_version_negotiate(3, 3)
    sock.send(session.wrap(7, struct.pack('<BIH', 0, 0, len(hello)) + hello))
    until(lambda: server.stats()['sessions'] == 1)
    self.assertLessEqual(server.stats()['udp_pending_bytes'], 256)
    until(lambda: server.stats()['connected'] == 0)
    self.assertEqual(server.stats()['last_peer_failure'], 'udp_delivery_timeout')

  def test_unacknowledged_large_snapshot_keeps_active_queue_charge_until_expiry(self):
    class LargeEngine(EngineOracle):
      def get_state(self, unused=''):
        return bytes(1024 * 1024)
    server = self.server(engine_factory=LargeEngine,
        udp_limits=UDPLimits(pending_packets=2, pending_bytes=2500, delivery_timeout=.5),
        limits=ServerLimits(write_timeout=.12, heartbeat_interval=1))
    client = self.client(server)
    client.connect()
    token = client.session_token
    client.send_ready()
    until(server.all_clients_ready)
    server.run_one_frame(0)
    client.close()
    self.drop(server)
    sock = self.raw(server)
    self.confirm(sock, 42)
    request = wire.pack_reconnect_request(token)
    sock.send(session.wrap(42, struct.pack('<BIH', 0, 0, len(request)) + request))
    until(lambda: server.stats()['send_bytes'] >= 1024 * 1024)
    self.assertLessEqual(server.stats()['udp_pending_bytes'], 2500)
    until(lambda: server.stats()['connections'] == 0)
    stats = server.stats()
    self.assertEqual(stats['last_peer_failure'], 'write_timeout')
    self.assertEqual((stats['send_bytes'], stats['udp_pending_bytes'], stats['udp_receive_bytes']), (0, 0, 0))
    self.assertTrue(stats['running'])

  def make_reconnecting(self, **options):
    server = self.server(**options.pop('server_options', {}))
    options.setdefault('limits', ClientLimits(connect_timeout=.3, handshake_timeout=.3))
    options.setdefault('reconnect_limits', ReconnectLimits(base_seconds=.02, max_seconds=.05, recovery_seconds=3))
    client = ReconnectingFrameSyncUDPClient('127.0.0.1', server.listen_port,
              lambda: [(0, wire.SlotInput(.5, -.25, 4))], **options)
    self.clients.append(client)
    self.assertEqual(client.connect(), ((42, 1, 0), [0]))
    replica = Replica()
    client.attach_logic(replica, limits=LogicLimits(prediction_frames=0))
    until(server.all_clients_ready)
    return server, client, replica

  def frame(self, server, client, replica):
    client.run_one_tick()
    frame, _ = server.run_one_frame(500)
    until(client.client.has_authoritative_frame)
    client.run_one_tick()
    self.assertEqual(client.logic.get_last_confirmed_frame_id(), frame)
    self.assertEqual(replica.get_state(), server.get_env().get_state())

  def test_automatic_restore_deferred_authority_hashes_and_repeated_cleanup(self):
    server, client, replica = self.make_reconnecting()
    self.frame(server, client, replica)
    for recovery in range(3):
      previous = client.client._recv_thread
      epoch = client.client.stats()['connection_epoch']
      self.drop(server)
      client.client.close()
      until(lambda: client.stats()['state'] == 'restoring')
      before = len(replica.restored)
      for _ in range(3):
        server.run_one_frame(0)
      replica.on_restore = lambda: self.assertFalse(server.all_clients_ready())
      client.tick()
      self.assertEqual(client.stats()['state'], 'handback')
      until(lambda: client.client.resume_handback_complete)
      client.tick()
      self.assertEqual(len(replica.restored), before + 1)
      self.assertNotEqual(client.client.stats()['connection_epoch'], epoch)
      until(lambda: client.client.stats()['authority_frames'] == 3)
      client.run_one_tick()
      self.assertEqual(replica.get_state(), server.get_env().get_state())
      self.assertEqual(client.logic.stats()['verified_hashes'], 3)
      self.frame(server, client, replica)
      self.assertFalse(previous.is_alive())
      self.assertEqual(server.get_connected_client_count(), 1)
    self.assertEqual(client.stats()['restores'], 3)

  def test_client_only_loss_recovers_after_server_idle_detection(self):
    server, client, replica = self.make_reconnecting(server_options={'limits': ServerLimits(idle_timeout=.2, heartbeat_interval=.05)})
    self.frame(server, client, replica)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    client.tick()
    until(lambda: client.client.resume_handback_complete)
    client.tick()
    self.frame(server, client, replica)
    self.assertEqual(client.stats()['restores'], 1)

  def test_1000_ticks_do_not_block_during_attempt_and_give_up_is_terminal(self):
    server, client, replica = self.make_reconnecting(reconnect_limits=ReconnectLimits(
        base_seconds=.02, max_seconds=.03, recovery_seconds=2, max_attempts=2))
    self.frame(server, client, replica)
    notices = []
    client.set_on_give_up(lambda: notices.append('give_up'))
    server.stop()
    client.client.close()
    until(lambda: client.stats()['state'] in ('attempting', 'backoff', 'gave_up'))
    started = time.monotonic()
    for _ in range(1000):
      client.tick()
    self.assertLess(time.monotonic() - started, .3)
    until(lambda: client.stats()['state'] == 'gave_up')
    attempts = client.stats()['total_attempts']
    for _ in range(1000):
      client.tick()
    self.assertEqual(client.stats()['total_attempts'], attempts)
    self.assertEqual(notices, ['give_up'])
    self.assertFalse(client.stats()['worker_alive'])

  def test_restore_error_never_sends_ready_or_success(self):
    server, client, replica = self.make_reconnecting()
    self.frame(server, client, replica)
    self.drop(server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    def fail():
      raise RuntimeError('restore rejected')
    replica.on_restore = fail
    with self.assertRaisesRegex(RuntimeError, 'restore rejected'):
      client.tick()
    self.assertEqual(client.stats()['state'], 'gave_up')
    self.assertFalse(server.all_clients_ready())
    self.assertEqual(client.stats()['restores'], 0)


if __name__ == '__main__':
  unittest.main()
