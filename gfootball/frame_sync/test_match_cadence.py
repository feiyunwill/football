"""Cadence rejection boundaries using real TCP/UDP and explicit engine oracles."""
from dataclasses import FrozenInstanceError
import json
import struct
import threading
import time
from types import SimpleNamespace
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.match_bootstrap import (
    HEADER, MAGIC, MATCH_VERSION, MatchBuffers, MatchResumeLimits,
    pack_origin, unpack_origin, pack_match_ready, unpack_match_ready,
)
from gfootball.frame_sync.match_cadence import MATCH_CADENCE, MatchCadence, parse_cadence
from gfootball.frame_sync.match_identity import NativeMatchEngine
from gfootball.frame_sync.multiplayer_runtime import NetworkPlayer
from gfootball.frame_sync.multiplayer_transport import MatchServer, MatchTCPClient
from gfootball.frame_sync.multiplayer_udp import MatchUDPServer, MatchUDPClient
from gfootball.frame_sync.resume_protocol import pack_session_token
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.server_state import ServerDecoder, ServerLimits
from gfootball.frame_sync.test_match_archive import MatchOracle


def change_origin(payload, change):
  _, size = HEADER.unpack_from(payload)
  metadata = json.loads(payload[HEADER.size:HEADER.size + size])
  change(metadata)
  encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode('ascii')
  return HEADER.pack(MAGIC, len(encoded)) + encoded + payload[HEADER.size + size:]


class MatchCadenceTest(unittest.TestCase):
  def origin(self):
    env = MatchOracle(ServerSettings())
    try:
      return pack_origin(ServerSettings(), env)
    finally:
      env.close()

  def test_canonical_contract_and_independent_wire_vector(self):
    # 2026-09-13: independent expected v7 physical contract.
    # expected = dict(input_hz=10, network_hz=10, physics_steps=10, physics_step_us=10000)
    expected = dict(input_hz=50, network_hz=50, physics_steps=2, physics_step_us=10000)
    self.assertEqual(MATCH_CADENCE.to_dict(), expected)
    self.assertEqual(MATCH_CADENCE.physics_steps * MATCH_CADENCE.physics_step_us * MATCH_CADENCE.network_hz, 1000000)
    # 2026-09-10: independent v6 vector includes the origin epoch, initially zero.
    # packet = bytes.fromhex('12 0500 0a00 0a00 0a00 10270000')
    # 2026-09-13: independent v7 little-endian wire vector, unchanged epoch layout.
    # packet = bytes.fromhex('12 0600 0a00 0a00 0a00 10270000 00000000')
    packet = bytes.fromhex('12 0700 3200 3200 0200 10270000 00000000')
    self.assertEqual(pack_match_ready(), packet)
    self.assertEqual(unpack_match_ready(packet), MATCH_CADENCE)
    expected['input_hz'] = 20
    # 2026-09-13: canonical v7 remains immutable after dictionary mutation.
    # self.assertEqual(MATCH_CADENCE.input_hz, 10)
    self.assertEqual(MATCH_CADENCE.input_hz, 50)
    with self.assertRaises(FrozenInstanceError):
      MATCH_CADENCE.network_hz = 20

  def test_strict_types_fields_and_unsupported_rates(self):
    for name in MATCH_CADENCE.to_dict():
      for value in (True, False, None, '10', 10.0, -1, 0, 11, 2**64):
        with self.subTest(name=name, value=value), self.assertRaises(ValueError):
          parse_cadence(dict(MATCH_CADENCE.to_dict(), **{name: value}))
    for value in (None, [], {}, dict(MATCH_CADENCE.to_dict(), extra=0)):
      with self.assertRaises(ValueError):
        parse_cadence(value)
    for rate in (True, '10', 9, 100, float('nan'), float('inf')):
      with self.assertRaises(ValueError):
        MATCH_CADENCE.require_rate(rate)
    # 2026-09-13: equal finite numeric 50 Hz is accepted.
    # MATCH_CADENCE.require_rate(10.0)
    MATCH_CADENCE.require_rate(50.0)

  def test_old_versions_or_incomplete_confirmation_rejected(self):
    good = pack_match_ready()
    for packet in (good[:-1], good + b'x', bytearray(good), wire.pack_ready(),
                   good[:1] + b'\x04\x00' + good[3:], good[:3] + b'\x14\x00' + good[5:]):
      with self.assertRaises(ValueError):
        unpack_match_ready(packet)

  def test_origin_requires_contract_before_exposing_ready_and_clears_failure(self):
    origin = self.origin()
    variants = [b'FMATCH4\0' + origin[8:], change_origin(origin, lambda row: row.pop('cadence'))]
    for name in MATCH_CADENCE.to_dict():
      variants.append(change_origin(origin, lambda row, name=name: row['cadence'].update({name: 20})))
    for payload in variants:
      with self.subTest(payload=payload[:12]):
        with self.assertRaises(ClientFailure):
          unpack_origin(payload)
        buffers = MatchBuffers(ClientLimits(), MatchResumeLimits())
        buffers.feed(wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(123), now=1)
        with self.assertRaises(ClientFailure):
          buffers.feed(wire.pack_state_snapshot(0, payload), now=1)
        # 2026-09-10: ClientBuffers.fail uses the terminal 'closed' phase.
        # self.assertEqual(buffers.phase, 'failed')
        self.assertEqual(buffers.phase, 'closed')
        self.assertIsNone(buffers.cadence)
        self.assertEqual(buffers.retained_snapshot_bytes, 0)

  def test_fragmented_origin_and_ack_are_admitted_only_when_complete(self):
    buffers = MatchBuffers(ClientLimits(receive_bytes=512), MatchResumeLimits())
    data = (wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(123)
            + wire.pack_state_snapshot(0, self.origin()))
    for value in data[:-1]:
      buffers.feed(bytes([value]), now=1)
      self.assertIsNone(buffers.cadence)
      self.assertNotEqual(buffers.phase, 'ready')
    buffers.feed(data[-1:], now=1)
    self.assertEqual(buffers.cadence, MATCH_CADENCE)
    decoder = ServerDecoder(ServerLimits(), 1)
    packet = pack_match_ready()
    for value in packet[:-1]:
      decoder.feed(bytes([value]))
      self.assertIsNone(decoder.pop())
    # 2026-09-10: independent frame-input wire bytes, no nonexistent helper.
    # decoder.feed(packet[-1:] + wire.pack_frame_input(0, [(0, wire.default_slot_input())]))
    decoder.feed(packet[-1:] + struct.pack('<BIH', wire.MessageType.FrameInput, 0, 1)
                 + struct.pack('<HffH', 0, 0, 0, 0))
    self.assertEqual(decoder.pop(), packet)
    self.assertEqual(decoder.pop()[0], wire.MessageType.FrameInput)
    self.assertIsNone(decoder.pop())

  def test_native_adapter_checks_steps_without_rehashing_files(self):
    calls, identities = [], []
    identity = dict(backend='explicit-adapter-fixture', abi='fixture', implementation='a'*64, resources='b'*64)
    # 2026-09-13: adapter fixture represents negotiated v7 physics.
    # engine = SimpleNamespace(game_config=SimpleNamespace(render=False, physics_steps_per_frame=10,
    engine = SimpleNamespace(game_config=SimpleNamespace(render=False, physics_steps_per_frame=2,
        render_resolution_x=1280, render_resolution_y=720), step_with_input=lambda data: calls.append(data))
    adapter = NativeMatchEngine(engine, lambda: (identities.append(1), identity)[1], identity)
    for _ in range(10):
      adapter.step_with_input(b'input')
    self.assertEqual((len(calls), len(identities)), (10, 0))
    engine.game_config.physics_steps_per_frame = 11
    with self.assertRaisesRegex(SaveFormatError, 'configuration changed'):
      adapter.step_with_input(b'invalid')
    self.assertEqual(len(calls), 10)
    errors = []
    def foreign():
      try:
        adapter.step_with_input(b'foreign')
      except RuntimeError:
        errors.append(True)
    thread = threading.Thread(target=foreign)
    thread.start()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [True])


class MatchCadenceNetworkTest(unittest.TestCase):
  def setUp(self):
    self.engines, self.servers, self.clients, self.players = [], [], [], []

  def tearDown(self):
    for owner in self.players + self.clients + self.servers:
      owner.close()
    self.assertTrue(all(env.closed == 1 for env in self.engines))

  def factory(self, settings):
    env = MatchOracle(settings)
    self.engines.append(env)
    return env

  def server(self, transport):
    cls = MatchServer if transport == 'tcp' else MatchUDPServer
    server = cls(listen_host='127.0.0.1', listen_port=0, left_agents=1, right_agents=0,
                 engine_factory=self.factory, state_hash_interval=1)
    self.servers.append(server)
    server.start()
    return server

  def low_client(self, server, transport):
    cls = MatchTCPClient if transport == 'tcp' else MatchUDPClient
    client = cls('127.0.0.1', server.listen_port)
    self.clients.append(client)
    client.connect()
    return client

  def player(self, server, transport):
    player = NetworkPlayer('127.0.0.1', server.listen_port, transport=transport,
        engine_factory=self.factory, input_provider=lambda _: wire.default_slot_input(),
        # 2026-09-10: client-only UDP loss is first detected by the real 3s idle timer.
        # reconnect_limits=ReconnectLimits(base_seconds=.01, max_seconds=.03, recovery_seconds=2))
        reconnect_limits=ReconnectLimits(base_seconds=.01, max_seconds=.03, recovery_seconds=6))
    self.players.append(player)
    player.start()
    return player

  def wait(self, predicate, pump=lambda: None):
    # 2026-09-10: include UDP idle detection and the subsequent bounded handshake.
    # deadline = time.monotonic() + 4
    deadline = time.monotonic() + 8
    while not predicate():
      pump()
      self.assertLess(time.monotonic(), deadline, 'Cadence network condition timed out')
      time.sleep(.002)

  def test_both_transports_confirm_before_frame_zero_and_after_reconnect(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        player = self.player(server, transport)
        self.wait(server.participants_ready, player.tick)
        # 2026-09-10: match control and cadence now share the v6 handshake.
        # self.assertEqual(server.stats()['match_protocol'], 5)
        # 2026-09-13: real transports must report negotiated v7.
        # self.assertEqual(server.stats()['match_protocol'], 6)
        self.assertEqual(server.stats()['match_protocol'], 7)
        self.assertEqual(player.client.client.match_cadence, MATCH_CADENCE.to_dict())
        player.tick()
        server.run_one_frame(100)
        self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() == 0, player.tick)
        player.client.client.close()
        self.wait(lambda: player.client.stats()['restores'] == 1, player.tick)
        self.assertEqual(player.client.client.match_cadence, server.stats()['cadence'])
        player.tick()
        server.run_one_frame(100)
        self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() == 1, player.tick)
        server.finish_match()
        self.wait(lambda: player.stats()['ended'], player.tick)
        # 2026-09-10: this API succeeds by returning normally, not a boolean.
        # self.assertTrue(player.flush_end_ack())
        player.flush_end_ack()
        self.wait(server.finish_acknowledged)

  def test_mismatched_origin_rejected_before_client_engine_construction(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        count = len(self.engines)
        def corrupt():
          server._runtime._origin = change_origin(server._runtime._origin,
              lambda row: row['cadence'].update(input_hz=20))
        server._call(corrupt)
        with self.assertRaisesRegex(ClientFailure, 'invalid_match_metadata'):
          self.player(server, transport)
        self.assertEqual(len(self.engines), count)
        self.assertFalse(server.participants_ready())
        self.assertEqual(server._call(lambda: server._runtime.window.frame_id), 0)

  def test_resume_cadence_change_never_reaches_existing_engine_restore(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        player = self.player(server, transport)
        self.wait(server.participants_ready, player.tick)
        player.tick()
        server.run_one_frame(100)
        self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() == 0, player.tick)
        restores, env = player.env.restores, player.env
        def corrupt():
          original = server._runtime._snapshot_bytes
          server._runtime._snapshot_bytes = lambda: change_origin(original(),
              lambda row: row['cadence'].update(physics_steps=20))
        server._call(corrupt)
        player.client.client.close()
        with self.assertRaisesRegex(ClientFailure, 'invalid_match_metadata'):
          self.wait(lambda: player.stats()['closed'], player.tick)
        self.assertEqual(env.restores, restores)
        self.assertEqual(env.closed, 1)

  def test_plain_ready_and_wrong_cadence_cannot_release_authority(self):
    for transport in ('tcp', 'udp'):
      for packet in (wire.pack_ready(), struct.pack('<BHHHHI', 18, 5, 20, 10, 10, 10000)):
        with self.subTest(transport=transport, packet=packet):
          server = self.server(transport)
          client = self.low_client(server, transport)
          self.assertFalse(server.participants_ready())
          with client._lock:
            self.assertTrue(client._enqueue_locked(packet))
          self.wait(lambda: bool(client.failure_reason))
          self.assertFalse(server.participants_ready())
          self.assertEqual(server._call(lambda: server._runtime.window.frame_id), 0)

  def test_partial_confirmation_does_not_release_slot(self):
    server = self.server('tcp')
    client = self.low_client(server, 'tcp')
    packet = pack_match_ready()
    with client._lock:
      self.assertTrue(client._enqueue_locked(packet[:-1]))
    self.wait(lambda: server._call(lambda: any(len(peer.decoder.data) == len(packet)-1
                                              for peer in server._runtime.peers.values())))
    self.assertFalse(server.participants_ready())
    with client._lock:
      self.assertTrue(client._enqueue_locked(packet[-1:]))
    self.wait(server.participants_ready)

  def test_old_version_cannot_acquire_a_match_slot(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        cls = MatchTCPClient if transport == 'tcp' else MatchUDPClient
        client = cls('127.0.0.1', server.listen_port)
        self.clients.append(client)
        client._hello_packet = lambda token: wire.pack_version_negotiate(4, 4)
        with self.assertRaises(ClientFailure):
          client.connect()
        self.assertEqual(server.get_session_tokens(), {})

  def test_runtime_cannot_override_confirmed_cadence(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        player = self.player(server, transport)
        for rate in (True, 100, 9, float('nan')):
          # 2026-09-13: runtime override rejects rates outside v7.
          # with self.assertRaisesRegex(ValueError, '10 Hz'):
          #   server.run_loop(rate_hz=rate)
          with self.assertRaisesRegex(ValueError, '50 Hz'):
            server.run_loop(rate_hz=rate)
          # 2026-09-13: runtime override rejects rates outside v7.
          # with self.assertRaisesRegex(ValueError, '10 Hz'):
          #   player.client.attach_logic(player.env, rate_hz=rate)
          with self.assertRaisesRegex(ValueError, '50 Hz'):
            player.client.attach_logic(player.env, rate_hz=rate)
        self.assertEqual(server._call(lambda: server._runtime.window.frame_id), 0)
        self.assertFalse(server._runtime.closed)


if __name__ == '__main__':
  unittest.main()
