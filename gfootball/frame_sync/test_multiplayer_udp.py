"""Actual UDP v4 matches, loss, recovery, terminal ACK and persistent outputs.

MatchOracle is an explicit deterministic reducer, never a native GameEnv fake.
"""
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import queue
import select
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from gfootball.frame_sync import main_menu, protocol as wire, udp_session
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.client_udp_resume import ResumableFrameSyncUDPClient
from gfootball.frame_sync.match_archive import MAX_SNAPSHOT, decode_checkpoint, engine_digest, playback, read_checkpoint
from gfootball.frame_sync.menu_options import MenuOptions, save_options
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.multiplayer_udp import MatchUDPServer, MatchUDPClient
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.server_state import ServerLimits, ServerFailure
from gfootball.frame_sync.server_udp import FrameSyncUDPServer
from gfootball.frame_sync.test_match_archive import MatchOracle
from gfootball.frame_sync.test_udp_resume_budget import FaultRelay
from gfootball.frame_sync.udp_state import UDPLimits

MEASUREMENTS = {}


class EndAckRelay(FaultRelay):
  """Drop first EndAck DATA and its first delivery ACK over real sockets."""
  def __init__(self, port, *, blackhole=False):
    self.end_data_dropped = self.end_receipt_dropped = 0
    self.blackhole = blackhole
    self.end_seq = None
    super().__init__(port)

  def run(self):
    address = None
    try:
      while not self.stop.is_set():
        readable, _, _ = select.select([self.front, self.back], [], [], .005)
        for sock in readable:
          try:
            packet, source = sock.recvfrom(1201)
          except ConnectionResetError:
            continue
          self.maximum = max(self.maximum, len(packet))
          if len(packet) > 1200:
            raise AssertionError('Oversized match datagram')
          if sock is self.front:
            address = source
            if len(packet) == 21 and packet[0] == 0x74 and packet[9] == 0 and packet[16] == wire.MessageType.MatchEndAck:
              self.end_seq = packet[10:14]
              if self.blackhole or self.end_data_dropped == 0:
                self.end_data_dropped += 1
                continue
            self.back.send(packet)
          elif address is not None:
            if len(packet) == 14 and packet[0] == 0x74 and packet[9] == 255 and packet[10:14] == self.end_seq and self.end_receipt_dropped == 0:
              self.end_receipt_dropped += 1
              continue
            self.front.sendto(packet, address)
    except BaseException as error:
      self.errors.append(error)
    finally:
      self.front.close()
      self.back.close()


class MultiplayerUDPTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.engines, self.hosts, self.players, self.servers, self.relays, self.clients = [], [], [], [], [], []
    self.reconnect = ReconnectLimits(base_seconds=.02, max_seconds=.05, recovery_seconds=3)

  def factory(self, settings):
    engine = MatchOracle(settings)
    self.engines.append(engine)
    return engine

  def host(self, **options):
    options.setdefault('engine_factory', self.factory)
    options.setdefault('input_provider', lambda frame: wire.SlotInput(.5, 0, 1))
    options.setdefault('reconnect_limits', self.reconnect)
    options.setdefault('server_limits', ServerLimits(heartbeat_interval=.05, idle_timeout=.4))
    host = HostedMatch(transport='udp', listen_host='127.0.0.1', port=0, **options)
    self.hosts.append(host)
    host.start()
    return host

  def player(self, port, **options):
    options.setdefault('engine_factory', self.factory)
    options.setdefault('input_provider', lambda frame: wire.SlotInput(-.5, .25, 4))
    options.setdefault('reconnect_limits', self.reconnect)
    player = NetworkPlayer('127.0.0.1', port, transport='udp', **options)
    self.players.append(player)
    return player

  def wait(self, predicate, pump=None, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
      if pump is not None:
        pump()
      self.assertLess(time.monotonic(), deadline, 'UDP match condition timed out')
      time.sleep(.003)

  def advance(self, host, player, count=1):
    pump = lambda: (host.player.tick(), player.tick())
    self.wait(host.server.participants_ready, pump)
    for _ in range(count):
      pump()
      self.assertTrue(host.advance())
      self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() >= host.frame - 1, pump)

  def end(self, host, player):
    host.server.finish_match()
    self.wait(lambda: player.stats()['ended'] and host.player.stats()['ended'],
              lambda: (host.player.tick(), player.tick()))
    player.flush_end_ack()
    self.assertTrue(host.finish())
    self.assertEqual(engine_digest(player.env), host.server._call(lambda: engine_digest(host.server._runtime.env)))
    self.assertEqual(player.client.logic.stats()['history_bytes'], 0)

  def tearDown(self):
    errors = []
    for owner in self.players + self.hosts + self.clients + self.servers + self.relays:
      try:
        owner.close()
      except BaseException as error:
        errors.append(repr(error))
    self.assertEqual(errors, [])
    self.assertTrue(all(engine.closed == 1 for engine in self.engines), [engine.closed for engine in self.engines])
    for host in self.hosts:
      if host.server._runtime is not None:
        self.assertFalse(host.server._thread is not None and host.server._thread.is_alive())
        self.assertEqual(host.server._runtime._addresses, {})
        self.assertEqual(host.server._runtime._epochs, {})
        self.assertEqual(host.server._runtime._origin, None)
    for player in self.players:
      self.assertFalse(player.client.client.stats()['worker_alive'])
      self.assertEqual(player.client.client.stats()['snapshot_bytes'], 0)

  def test_ready_barrier_lobby_does_not_predict_and_final_prediction_is_undone(self):
    host = self.host()
    for _ in range(4):
      self.assertFalse(host.advance())
    self.assertEqual(host.player.env.frames, 0)
    with self.assertRaisesRegex(ServerFailure, 'participants_not_ready'):
      host.server.run_one_frame(0)
    player = self.player(host.port)
    player.start()
    self.advance(host, player, 3)
    for _ in range(4):
      player.tick()
    self.assertGreater(player.env.frames, host.frame)
    self.end(host, player)
    self.assertEqual(player.env.frames, 3)

  def test_owned_run_loops_write_actual_save_record_and_verified_playback(self):
    record, save = str(self.root / 'match.replay'), str(self.root / 'match.save')
    host = self.host(record_path=record, save_path=save)
    relay = EndAckRelay(host.port)
    self.relays.append(relay)
    results, errors = [], []
    def join():
      # 2026-09-10: exercise final packet/receipt loss inside actual run/close.
      # player = NetworkPlayer('127.0.0.1', host.port, transport='udp', engine_factory=self.factory,
      player = NetworkPlayer('127.0.0.1', relay.port, transport='udp', engine_factory=self.factory,
          input_provider=lambda frame: wire.SlotInput(-.5, 0, 4), reconnect_limits=self.reconnect)
      try:
        player.start()
        results.append(player.run(100, realtime=False))
      except BaseException as error:
        errors.append(repr(error))
      finally:
        player.close()
    worker = threading.Thread(target=join, name='football-match-udp-test-player')
    worker.start()
    try:
      result = host.run(7, realtime=False, lobby_timeout=5)
    finally:
      worker.join(5)
    self.assertFalse(worker.is_alive())
    self.assertEqual(errors, [])
    self.assertTrue(result['end_acknowledged'])
    self.assertEqual((relay.end_data_dropped, relay.end_receipt_dropped), (1, 1))
    self.assertEqual(results[0]['final_frame'], 7)
    self.assertTrue(results[0]['closed'])
    # 2026-09-10: read_checkpoint returns validated payload; decode yields raw state.
    # checkpoint = read_checkpoint(save)
    checkpoint = decode_checkpoint(read_checkpoint(save))
    self.assertEqual(struct.unpack_from('<I', checkpoint[1])[0], 7)
    verified = playback(record, engine_factory=self.factory)
    self.assertTrue(verified['verified'])
    self.assertEqual(verified['frames'], 7)

  def test_maximum_origin_and_frames_survive_loss_duplicate_reordering(self):
    # 2026-09-10: native canonical digests are distinct from serialized state;
    # the original padded reducer digest wrongly exceeded the separate budget.
    # def large(settings):
    #   env = self.factory(settings)
    #   env.padding = MAX_SNAPSHOT - 8
    #   return env
    class LargeSnapshotOracle(MatchOracle):
      def get_state_digest(self):
        self.check()
        return struct.pack('<II', self.frames, self.digest)
    def large(settings):
      env = LargeSnapshotOracle(settings)
      env.identity['implementation'] = 'd' * 64
      env.padding = MAX_SNAPSHOT - 8
      self.engines.append(env)
      return env
    # Large transfer remains subject to the configured handshake deadline.
    host = self.host(engine_factory=large, server_limits=ServerLimits(heartbeat_interval=.1))
    relay = FaultRelay(host.port)
    self.relays.append(relay)
    player = self.player(relay.port, engine_factory=large, client_limits=ClientLimits(handshake_timeout=15))
    started = time.monotonic()
    player.start()
    self.assertEqual(len(player.env.get_state()), MAX_SNAPSHOT)
    self.advance(host, player, 5)
    self.end(host, player)
    self.assertGreater(relay.dropped, 0)
    self.assertGreater(relay.duplicated, 0)
    self.assertGreater(relay.reordered, 0)
    self.assertLessEqual(relay.maximum, 1200)
    MEASUREMENTS['maximum_origin_fault_match'] = dict(seconds=time.monotonic() - started,
        raw_snapshot_bytes=MAX_SNAPSHOT, frames=5, dropped=relay.dropped,
        duplicated=relay.duplicated, reordered=relay.reordered, maximum_datagram=relay.maximum)

  def recover(self, running):
    host = self.host()
    # Short explicit attempt deadlines leave time for another attempt after
    # the server detects the vanished UDP endpoint within the 3s total budget.
    player = self.player(host.port, client_limits=ClientLimits(connect_timeout=.3, handshake_timeout=.3))
    player.start()
    self.wait(host.server.participants_ready, lambda: (host.player.tick(), player.tick()))
    if running:
      self.advance(host, player, 2)
    engine, token = player.env, player.client.client.session_token
    old = player.client.client
    epoch = old.stats()['connection_epoch']
    player.client.client.close()  # Real IO worker/socket shutdown, no server-side drop.
    self.wait(lambda: player.client.client is not old and not player.client.is_reconnecting,
              lambda: (host.player.tick(), player.tick()))
    self.assertIs(player.env, engine)
    self.assertIn(token, host.server.get_session_tokens().values())
    self.assertNotEqual(player.client.client.stats()['connection_epoch'], epoch)
    self.assertEqual(player.slots, (1,))
    if not running:
      self.assertEqual(host.frame, 0)
    # Inject an old-epoch datagram through the actual current UDP socket.
    before = host.server.stats()['epoch_dropped']
    with player.client.client._lock:
      player.client.client._sock.send(udp_session.wrap(epoch, struct.pack('<BIH', 0, 0, 1) + b'x'))
    self.wait(lambda: host.server.stats()['epoch_dropped'] > before)
    self.advance(host, player, 2)
    self.end(host, player)
    self.assertGreater(engine.restores, 1)

  def test_running_client_only_loss_recovers_original_token_engine_and_new_epoch(self):
    self.recover(True)

  def test_ready_lobby_client_only_loss_recovers_original_slot_without_advance(self):
    self.recover(False)

  def test_wrong_origin_identity_never_reaches_native_restore(self):
    host = self.host()
    def wrong(settings):
      env = self.factory(settings)
      env.identity['resources'] = 'e' * 64
      return env
    player = self.player(host.port, engine_factory=wrong)
    with self.assertRaisesRegex(SaveFormatError, 'resources'):
      player.start()
    self.assertEqual(self.engines[-1].restores, 0)
    self.assertTrue(player.stats()['closed'])

  def test_invalid_wire_origin_fails_before_player_factory(self):
    host = self.host()
    host.server._call(lambda: setattr(host.server._runtime, '_origin', b'badmagic' + host.server._runtime._origin[8:]))
    count = len(self.engines)
    player = self.player(host.port)
    with self.assertRaisesRegex(ClientFailure, 'invalid_match_snapshot'):
      player.start()
    self.assertEqual(len(self.engines), count)

  def test_small_client_receive_budget_streams_large_origin(self):
    def padded(settings):
      env = self.factory(settings)
      env.padding = 8192
      return env
    host = self.host(engine_factory=padded)
    player = self.player(host.port, client_limits=ClientLimits(receive_bytes=512))
    player.start()
    self.advance(host, player)
    self.end(host, player)

  def test_final_data_and_delivery_ack_loss_are_retried_before_close(self):
    host = self.host()
    relay = EndAckRelay(host.port)
    self.relays.append(relay)
    player = self.player(relay.port)
    player.start()
    self.advance(host, player, 3)
    self.end(host, player)
    self.assertEqual(relay.end_data_dropped, 1)
    self.assertEqual(relay.end_receipt_dropped, 1)
    self.assertFalse(player.client.client.output_pending())

  def test_unacknowledged_final_data_reports_bounded_timeout(self):
    host = self.host()
    relay = EndAckRelay(host.port, blackhole=True)
    self.relays.append(relay)
    player = self.player(relay.port)
    player.start()
    self.advance(host, player)
    host.server.finish_match()
    self.wait(lambda: player.stats()['ended'], lambda: (host.player.tick(), player.tick()))
    started = time.monotonic()
    with self.assertRaisesRegex(ClientFailure, 'end_ack_timeout'):
      player.flush_end_ack(.08)
    self.assertLess(time.monotonic() - started, .5)
    self.assertFalse(host.server.finish_acknowledged())

  def test_explicit_v4_and_legacy_udp_reject_each_other(self):
    host = self.host()
    legacy = ResumableFrameSyncUDPClient('127.0.0.1', host.port,
                                       limits=ClientLimits(handshake_timeout=.2))
    self.clients.append(legacy)
    with self.assertRaises(ClientFailure):
      legacy.connect()
    server = FrameSyncUDPServer('127.0.0.1', 0, engine_factory=self.factory)
    self.servers.append(server)
    server.start()
    player = self.player(server.listen_port, client_limits=ClientLimits(handshake_timeout=.2))
    count = len(self.engines)
    with self.assertRaises(ClientFailure):
      player.start()
    self.assertEqual(len(self.engines), count)

  def test_invalid_transport_or_limits_fail_before_engine_creation(self):
    for options in ({'transport': 'other'}, {'transport': True}, {'udp_limits': UDPLimits()},
                    {'transport': 'udp', 'udp_limits': 'bad'}):
      with self.assertRaises(ValueError):
        HostedMatch(engine_factory=self.factory, **options)
      with self.assertRaises(ValueError):
        NetworkPlayer(engine_factory=self.factory, **options)
    self.assertEqual(self.engines, [])

  def test_resume_resource_mismatch_does_not_restore_old_replica(self):
    host = self.host()
    player = self.player(host.port, client_limits=ClientLimits(connect_timeout=.3, handshake_timeout=.3))
    player.start()
    self.advance(host, player)
    engine, restores = player.env, player.env.restores
    host.server._call(lambda: host.server._runtime.env.identity.update(resources='f' * 64))
    player.client.client.close()
    with self.assertRaisesRegex(SaveFormatError, 'resources'):
      self.wait(lambda: player.stats()['closed'], lambda: (host.player.tick(), player.tick()))
    self.assertEqual(engine.restores, restores)
    self.assertEqual(engine.closed, 1)

  def test_public_udp_server_loop_waits_then_finishes_and_closes_all_owners(self):
    server = MatchUDPServer('127.0.0.1', 0, engine_factory=self.factory,
                           left_agents=1, right_agents=1, state_hash_interval=1)
    self.servers.append(server)
    server.start()
    errors = []
    def run():
      try:
        server.run_loop()
      except BaseException as error:
        errors.append(repr(error))
    worker = threading.Thread(target=run, name='football-match-udp-public-loop')
    worker.start()
    first, second = self.player(server.listen_port), self.player(server.listen_port)
    try:
      first.start()
      first.tick()
      self.assertEqual(server.get_frame_id(), 0)
      second.start()
      self.wait(lambda: server.get_frame_id() >= 3, lambda: (first.tick(), second.tick()))
      final = server.finish_match()
      self.wait(lambda: first.stats()['ended'] and second.stats()['ended'], lambda: (first.tick(), second.tick()))
      first.flush_end_ack()
      second.flush_end_ack()
      worker.join(4)
      self.assertFalse(worker.is_alive())
      self.assertEqual(first.stats()['final_frame'], final)
      self.assertEqual(engine_digest(first.env), engine_digest(second.env))
    finally:
      server.stop()
      worker.join(3)
    self.assertEqual(errors, [])
    self.assertEqual(server._runtime._addresses, {})
    self.assertEqual(server._runtime._epochs, {})

  def test_udp_menu_host_and_join_select_real_transport_and_restore_scope(self):
    import gfootball.frame_sync.multiplayer_runtime as runtime
    path = self.root / 'preferences.save'
    save_options(replace(MenuOptions(), host_right=0, frames=2), path)
    def factory_host(**options):
      self.assertEqual(options['transport'], 'udp')
      return HostedMatch(**options, engine_factory=self.factory)
    old_transport = main_menu._transport
    with mock.patch.object(runtime, 'HostedMatch', factory_host), mock.patch.object(sys, 'argv',
        ['menu', '--mode', 'host', '--transport', 'udp', '--settings-file', str(path)]), mock.patch(
        'builtins.input', side_effect=['', '', '', '', '0', '', '', '']), contextlib.redirect_stdout(io.StringIO()):
      self.assertEqual(main_menu.main(), 0)
    self.assertEqual(main_menu._transport, old_transport)
    ports, errors = queue.Queue(maxsize=1), []
    def host_worker():
      try:
        with HostedMatch(transport='udp', engine_factory=self.factory) as host:
          ports.put(host.port)
          host.run(3, realtime=False, lobby_timeout=3)
      except BaseException as error:
        errors.append(repr(error))
    worker = threading.Thread(target=host_worker, name='football-match-udp-menu-host')
    worker.start()
    port = ports.get(timeout=3)
    def factory_player(*args, **options):
      self.assertEqual(options['transport'], 'udp')
      return NetworkPlayer(*args, **options, engine_factory=self.factory)
    try:
      with mock.patch.object(runtime, 'NetworkPlayer', factory_player), mock.patch.object(main_menu, '_transport', 'udp'), mock.patch.object(main_menu, '_settings_path', str(path)), mock.patch('builtins.input', side_effect=['127.0.0.1', str(port), '100']), contextlib.redirect_stdout(io.StringIO()):
        result = main_menu.menu_join_game()
    finally:
      worker.join(6)
    self.assertFalse(worker.is_alive())
    self.assertEqual(errors, [])
    self.assertEqual(result['final_frame'], 3)
    self.assertTrue(result['closed'])


if __name__ == '__main__':
  unittest.main()
