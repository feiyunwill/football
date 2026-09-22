"""Real TCP multiplayer and files with an explicitly non-native engine oracle."""
import contextlib
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.client_tcp import FrameSyncClient
from gfootball.frame_sync.match_archive import MAX_SNAPSHOT, engine_digest, playback, read_checkpoint
from gfootball.frame_sync.match_bootstrap import (
    HEADER, MAGIC, MAX_PAYLOAD, MatchBuffers, MatchResumeLimits, pack_match_reconnect,
    pack_origin, unpack_match_reconnect, unpack_origin,
)
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.multiplayer_transport import MatchServer, MatchTCPClient
from gfootball.frame_sync.resume_protocol import pack_session_token
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.server_api import FrameSyncServer
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.server_state import ServerFailure
from gfootball.frame_sync.test_match_archive import MatchOracle


class MatchBootstrapTest(unittest.TestCase):
  def origin(self, size=8):
    engine = MatchOracle(ServerSettings())
    engine.padding = size - 8
    try:
      return pack_origin(ServerSettings(), engine)
    finally:
      engine.close()

  def feed(self, buffers, data):
    for start in range(0, len(data), 256):
      buffers.feed(data[start:start + 256], now=1)

  def buffers(self):
    return MatchBuffers(ClientLimits(receive_bytes=512), MatchResumeLimits())

  def start(self, buffers, origin):
    self.feed(buffers, wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(123))
    self.assertEqual(buffers.phase, 'snapshot_header')
    self.feed(buffers, wire.pack_state_snapshot(0, origin))

  def test_maximum_native_snapshot_bootstraps_incrementally_before_ready(self):
    payload = self.origin(MAX_SNAPSHOT)
    buffers = self.buffers()
    self.start(buffers, payload)
    self.assertEqual(buffers.phase, 'ready')
    self.assertEqual(buffers.snapshot, (0, payload))
    self.assertLessEqual(len(payload), MAX_PAYLOAD)
    settings, raw, _, identity = unpack_origin(payload, (42, 1, 0))
    self.assertEqual(len(raw), MAX_SNAPSHOT)
    self.assertEqual(identity['backend'], 'test.MatchOracle.adler32.v1')
    buffers.fail('closed')
    self.assertEqual(buffers.retained_snapshot_bytes, 0)

  def test_corrupt_payload_and_mismatching_session_rejected(self):
    original = self.origin()
    for bad in (original[:-1], original + b'x', b'badmagic' + original[8:], original[:-1] + b'x'):
      with self.assertRaises(ClientFailure):
        unpack_origin(bad)
    with self.assertRaisesRegex(ClientFailure, 'match_session_mismatch'):
      unpack_origin(original, (43, 1, 0))

  def test_malformed_duplicate_nested_or_noninteger_metadata_rejected(self):
    for raw in (b'{"settings":{},"settings":{}}', b'[]', b'{"seed":NaN}', b'{"seed":1.1}',
                b'[' * 1500 + b']' * 1500, b'\xff'):
      with self.assertRaises(ClientFailure):
        unpack_origin(HEADER.pack(MAGIC, len(raw)) + raw + b'x')

  def test_oversized_snapshot_header_is_rejected_without_retained_body(self):
    buffers = self.buffers()
    self.feed(buffers, wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(123))
    with self.assertRaisesRegex(ClientFailure, 'invalid_resume_snapshot'):
      self.feed(buffers, struct.pack('<BII', wire.MessageType.StateSnapshot, 0, MAX_PAYLOAD + 1))
    self.assertEqual(buffers.retained_snapshot_bytes, 0)

  def test_first_match_cannot_start_at_nonzero_frame(self):
    buffers = self.buffers()
    self.feed(buffers, wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(123))
    with self.assertRaisesRegex(ClientFailure, 'initial_match_frame'):
      self.feed(buffers, wire.pack_state_snapshot(1, self.origin()))

  def test_end_is_ordered_uses_full_hash_and_forbids_later_authority(self):
    buffers = self.buffers()
    self.start(buffers, self.origin())
    self.feed(buffers, wire.pack_authoritative_frame(0, [wire.default_slot_input()]))
    value = 0xfedcba9876543210
    self.feed(buffers, struct.pack('<BIQ', wire.MessageType.MatchEnd, 1, value))
    self.assertEqual(buffers.match_end, (1, value))
    with self.assertRaisesRegex(ClientFailure, 'authority_after_match_end'):
      self.feed(buffers, wire.pack_authoritative_frame(1, [wire.default_slot_input()]))

  def test_end_without_all_authority_and_duplicate_end_rejected(self):
    for frame, count in ((1, 1), (0, 2)):
      buffers = self.buffers()
      self.start(buffers, self.origin())
      with self.assertRaises(ClientFailure):
        for _ in range(count):
          self.feed(buffers, struct.pack('<BIQ', wire.MessageType.MatchEnd, frame, 1))

  def test_resume_requires_explicit_version_and_valid_capability(self):
    self.assertEqual(unpack_match_reconnect(pack_match_reconnect(123)), 123)
    for token in (0, True, -1, 2**64):
      with self.assertRaises(ValueError):
        pack_match_reconnect(token)
    for packet in (wire.pack_reconnect_request(123), struct.pack('<BHQ', 15, 3, 123),
                   struct.pack('<BHQ', 15, 4, 0), pack_match_reconnect(123) + b'x'):
      with self.assertRaises(ValueError):
        unpack_match_reconnect(packet)


class MultiplayerTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.engines, self.hosts, self.players, self.servers = [], [], [], []
    self.reconnect = ReconnectLimits(base_seconds=.01, max_seconds=.03, recovery_seconds=1)

  def factory(self, settings):
    engine = MatchOracle(settings)
    self.engines.append(engine)
    return engine

  def host(self, **options):
    options.setdefault('engine_factory', self.factory)
    options.setdefault('reconnect_limits', self.reconnect)
    options.setdefault('input_provider', lambda frame: wire.SlotInput(.5, 0, 0))
    host = HostedMatch(listen_host='127.0.0.1', port=0, **options)
    self.hosts.append(host)
    host.start()
    return host

  def player(self, port, **options):
    options.setdefault('engine_factory', self.factory)
    options.setdefault('reconnect_limits', self.reconnect)
    options.setdefault('input_provider', lambda frame: wire.SlotInput(-.5, 0, 0))
    player = NetworkPlayer('127.0.0.1', port, **options)
    self.players.append(player)
    return player

  def wait(self, predicate, pump=None, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate():
      if pump is not None:
        pump()
      self.assertLess(time.monotonic(), deadline, 'Multiplayer condition timed out')
      time.sleep(.001)

  def advance(self, host, player, count=1):
    self.wait(host.server.participants_ready, lambda: (host.player.tick(), player.tick()))
    for _ in range(count):
      player.tick()
      self.assertTrue(host.advance())
      self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() == host.frame - 1,
                lambda: (host.player.tick(), player.tick()))

  def tearDown(self):
    errors = []
    for owner in self.players + self.hosts + self.servers:
      try:
        owner.close()
      except BaseException as error:
        errors.append(repr(error))
    self.assertEqual(errors, [])
    self.assertTrue(all(engine.closed == 1 for engine in self.engines), [engine.closed for engine in self.engines])

  def test_host_waits_for_every_participant_without_predicting_lobby(self):
    host = self.host()
    for _ in range(3):
      self.assertFalse(host.advance())
    self.assertEqual(host.frame, 0)
    self.assertEqual(host.player.env.frames, 0)
    with self.assertRaisesRegex(ServerFailure, 'participants_not_ready'):
      host.server.run_one_frame(0)
    player = self.player(host.port)
    player.start()
    self.advance(host, player, 3)
    self.assertEqual(player.client.logic.get_last_confirmed_frame_id(), 2)
    self.assertEqual(player.client.logic.stats()['verified_hashes'], 3)

  def test_actual_host_join_end_ack_record_save_and_playback(self):
    replay, save = str(self.root / 'match.replay'), str(self.root / 'match.save')
    host = self.host(record_path=replay, save_path=save)
    results, errors = [], []
    def join():
      player = NetworkPlayer('127.0.0.1', host.port, engine_factory=self.factory,
          input_provider=lambda frame: wire.SlotInput(-.5, .25, 4), reconnect_limits=self.reconnect)
      try:
        player.start()
        results.append(player.run(100, realtime=False))
      except BaseException as error:
        errors.append(repr(error))
      finally:
        player.close()
    worker = threading.Thread(target=join, name='football-match-test-join')
    worker.start()
    try:
      result = host.run(7, realtime=False, lobby_timeout=3)
    finally:
      host.close(finalize=False)
      worker.join(5)
    self.assertFalse(worker.is_alive())
    self.assertEqual(errors, [])
    self.assertTrue(result['end_acknowledged'])
    self.assertTrue(results[0]['ended'])
    self.assertEqual(results[0]['final_frame'], 7)
    self.assertEqual(results[0]['last']['ball'], result['player']['last']['ball'])
    self.assertEqual(playback(replay, engine_factory=self.factory)['digest'], read_checkpoint(save)['digest'])

  def test_finish_rolls_back_speculation_and_verifies_terminal_hash(self):
    host = self.host()
    player = self.player(host.port)
    player.start()
    self.advance(host, player, 2)
    for _ in range(6):
      player.tick()
    self.assertGreater(player.env.frames, host.frame)
    expected = host.server._call(lambda: engine_digest(host.server._runtime.env))
    host.server.finish_match()
    self.wait(lambda: player.stats()['ended'], player.tick)
    self.assertEqual(player.env.frames, host.frame)
    self.assertEqual(engine_digest(player.env), expected)
    self.assertEqual(player.client.logic.stats()['history_bytes'], 0)
    self.assertEqual(player.client.logic.stats()['sampled_input_frames'], 0)
    player.flush_end_ack()

  def test_running_match_recovers_original_session_and_handback(self):
    host = self.host()
    player = self.player(host.port)
    player.start()
    self.advance(host, player, 3)
    token, engine = player.client.client.session_token, player.env
    player.client.client.close()
    self.wait(lambda: player.client.stats()['restores'] == 1, lambda: (player.tick(), host.player.tick()))
    self.assertIs(player.env, engine)
    self.assertEqual(player.slots, (1,))
    self.assertIn(token, host.server.get_session_tokens().values())
    self.advance(host, player, 2)
    self.assertEqual(player.client.logic.get_last_confirmed_frame_id(), 4)

  def test_ready_lobby_player_recovers_without_starting_or_losing_slot(self):
    host = self.host()
    self.wait(lambda: host.server._call(lambda: host.server._runtime.sessions[0].ever_ready))
    host.player.tick()
    host.player.client.client.close()
    self.wait(lambda: host.player.client.stats()['restores'] == 1, host.player.tick)
    self.assertEqual(host.frame, 0)
    self.assertEqual(host.player.env.frames, 0)
    player = self.player(host.port)
    player.start()
    self.advance(host, player)

  def test_resume_identity_mismatch_never_deserializes_and_closes_player(self):
    host = self.host()
    player = self.player(host.port)
    player.start()
    self.advance(host, player)
    engine = player.env
    restores = engine.restores
    host.server._call(lambda: host.server._runtime.env.identity.update(resources='c' * 64))
    player.client.client.close()
    with self.assertRaisesRegex(SaveFormatError, 'resources'):
      self.wait(lambda: player.stats()['closed'], player.tick)
    self.assertEqual(engine.restores, restores)
    self.assertEqual(engine.closed, 1)

  def test_initial_identity_mismatch_closes_without_any_restore(self):
    host = self.host()
    def incompatible(settings):
      engine = self.factory(settings)
      engine.identity['implementation'] = 'c' * 64
      return engine
    player = self.player(host.port, engine_factory=incompatible)
    with self.assertRaisesRegex(SaveFormatError, 'implementation'):
      player.start()
    self.assertEqual(self.engines[-1].restores, 0)
    self.assertTrue(player.stats()['closed'])
    self.assertEqual(host.frame, 0)

  # 2026-09-10: preserve the rejection boundary under the new protocol.
  # def test_legacy_clients_cannot_enter_match_v4(self):
  def test_legacy_clients_cannot_enter_match_v5(self):
    host = self.host()
    for enable in (False, True):
      client = FrameSyncClient('127.0.0.1', host.port, enable_resume=enable)
      try:
        with self.assertRaises(ClientFailure):
          client.connect()
      finally:
        client.close()
    self.assertEqual(host.frame, 0)

  def test_match_client_cannot_silently_enter_legacy_server(self):
    server = FrameSyncServer(listen_host='127.0.0.1', listen_port=0, engine_factory=self.factory)
    self.servers.append(server)
    server.start()
    player = self.player(server.listen_port)
    with self.assertRaises(ClientFailure):
      player.start()
    self.assertEqual(len(self.engines), 1)

  def test_half_open_extra_socket_does_not_hold_ready_match(self):
    host = self.host()
    player = self.player(host.port)
    player.start()
    with socket.create_connection(('127.0.0.1', host.port), timeout=1):
      self.advance(host, player)
    self.assertEqual(host.frame, 1)

  def test_lobby_timeout_closes_all_owners_and_preserves_previous_recording(self):
    path = self.root / 'previous.replay'
    path.write_bytes(b'old recording')
    host = self.host(record_path=str(path))
    with self.assertRaisesRegex(TimeoutError, 'participants timed out'):
      host.run(2, realtime=False, lobby_timeout=.02)
    self.assertTrue(host.stats()['closed'])
    self.assertEqual(path.read_bytes(), b'old recording')

  def test_invalid_input_reentrant_tick_and_foreign_owner_rejected(self):
    host = self.host()
    player = self.player(host.port, input_provider=lambda frame: wire.SlotInput(0, 0, True))
    player.start()
    with self.assertRaises(ValueError):
      player.tick()
    self.assertTrue(player.stats()['closed'])
    failures = []
    def foreign():
      for action in (host.advance, host.save, host.close):
        try:
          action()
        except RuntimeError:
          failures.append(True)
    worker = threading.Thread(target=foreign)
    worker.start()
    worker.join(2)
    self.assertFalse(worker.is_alive())
    self.assertEqual(failures, [True] * 3)

  def test_callback_cannot_close_engine_during_its_input_sample(self):
    host = self.host()
    player = self.player(host.port)
    player._input_provider = lambda frame: player.close()
    player.start()
    with self.assertRaisesRegex(RuntimeError, 'inside its tick'):
      player.tick()
    self.assertTrue(player.stats()['closed'])

  def test_recording_export_failure_still_closes_host_and_replica(self):
    path = self.root / 'previous.replay'
    path.write_bytes(b'previous')
    host = self.host(record_path=str(path), right=0)
    with mock.patch('gfootball.replay_io.os.replace', side_effect=OSError('publish failure')):
      with self.assertRaisesRegex(OSError, 'publish failure'):
        host.run(2, realtime=False, lobby_timeout=2)
    self.assertTrue(host.stats()['closed'])
    self.assertEqual(path.read_bytes(), b'previous')

  def test_initial_snapshot_budget_failure_closes_native_factory_result(self):
    def oversized(settings):
      engine = self.factory(settings)
      engine.padding = MAX_SNAPSHOT
      return engine
    host = HostedMatch(engine_factory=oversized, port=0)
    self.hosts.append(host)
    with self.assertRaises(SaveFormatError):
      host.start()
    self.assertTrue(host.stats()['closed'])

  def test_authority_engine_failure_preserves_error_and_aborts_recording(self):
    path = self.root / 'previous.replay'
    path.write_bytes(b'previous')
    host = self.host(record_path=str(path), right=0)
    self.wait(host.server.participants_ready, host.player.tick)
    host.server._call(lambda: setattr(host.server._runtime.env, 'fail_step', True))
    with self.assertRaisesRegex(RuntimeError, 'engine step failure'):
      host.advance()
    self.assertTrue(host.stats()['closed'])
    self.assertEqual(path.read_bytes(), b'previous')

  def test_terminal_hash_mismatch_closes_player_after_reconciliation(self):
    host = self.host()
    player = self.player(host.port)
    player.start()
    self.advance(host, player)
    wrong = host.server._call(lambda: wire.compute_state_hash(host.server._runtime.env.get_state_digest()) ^ 1)
    host.server.send_to_all(struct.pack('<BIQ', wire.MessageType.MatchEnd, host.frame, wrong))
    with self.assertRaisesRegex(ClientFailure, 'match_end_hash'):
      self.wait(lambda: player.stats()['closed'], player.tick)
    self.assertEqual(player.stats()['failure'], 'match_end_hash')

  def test_malformed_wire_origin_is_rejected_before_client_engine_factory(self):
    host = self.host()
    def corrupt():
      runtime = host.server._runtime
      runtime._origin = b'badmagic' + runtime._origin[8:]
    host.server._call(corrupt)
    before = len(self.engines)
    player = self.player(host.port)
    with self.assertRaisesRegex(ClientFailure, 'invalid_match_snapshot'):
      player.start()
    self.assertEqual(len(self.engines), before)

  def test_lobby_cancel_ends_zero_frame_match_without_predicting(self):
    host = self.host()
    self.assertTrue(host.finish())
    self.assertTrue(host.player.stats()['ended'])
    self.assertEqual(host.player.env.frames, 0)
    self.assertEqual(host.player.client.logic.stats()['history_bytes'], 0)

  def test_public_server_loop_waits_for_slots_and_finishes_after_acknowledgements(self):
    server = MatchServer(listen_host='127.0.0.1', listen_port=0, engine_factory=self.factory,
                         left_agents=1, right_agents=1, state_hash_interval=1)
    self.servers.append(server)
    server.start()
    errors = []
    def run():
      try:
        server.run_loop()
      except BaseException as error:
        errors.append(repr(error))
    worker = threading.Thread(target=run, name='football-match-test-server-loop')
    worker.start()
    first = self.player(server.listen_port)
    second = self.player(server.listen_port)
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
      worker.join(3)
      self.assertFalse(worker.is_alive())
      self.assertEqual(first.stats()['final_frame'], final)
    finally:
      server.stop()
      worker.join(3)
    self.assertEqual(errors, [])

  def test_public_server_loop_can_finish_while_waiting_in_empty_lobby(self):
    server = MatchServer(listen_host='127.0.0.1', listen_port=0, engine_factory=self.factory)
    self.servers.append(server)
    server.start()
    errors = []
    def run():
      try:
        server.run_loop()
      except BaseException as error:
        errors.append(repr(error))
    worker = threading.Thread(target=run, name='football-match-test-empty-loop')
    worker.start()
    try:
      self.assertEqual(server.finish_match(), 0)
      worker.join(3)
      self.assertFalse(worker.is_alive())
    finally:
      server.stop()
      worker.join(3)
    self.assertEqual(errors, [])


if __name__ == '__main__':
  unittest.main()
