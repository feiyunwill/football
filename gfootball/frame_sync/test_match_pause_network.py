"""Actual v6 TCP/UDP control barriers with explicitly identified engine oracles."""
import struct
import select
import tempfile
from pathlib import Path
import threading
import time
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure, ClientLimits
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.graphical_input import InputBuffer
from gfootball.frame_sync.match_archive import engine_digest, decode_checkpoint, read_checkpoint, playback
from gfootball.frame_sync.match_bootstrap import (
    MatchBuffers, MatchResumeLimits, pack_origin, pack_match_ready, unpack_match_ready,
)
from gfootball.frame_sync.match_control import MatchControl, PAUSED, RESUMING, RUNNING, pack_control, pack_control_ack, pack_epoch_input
from gfootball.frame_sync.multiplayer_transport import MatchServer, MatchTCPClient
from gfootball.frame_sync.multiplayer_udp import MatchUDPServer, MatchUDPClient
from gfootball.frame_sync.multiplayer_runtime import NetworkPlayer, HostedMatch
from gfootball.frame_sync.resume_protocol import pack_session_token
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.server_state import ServerFailure, ServerLimits
from gfootball.frame_sync.test_match_archive import MatchOracle
from gfootball.frame_sync.test_udp_resume_budget import FaultRelay


class PauseFaultRelay(FaultRelay):
  """Drop each control phase, both barrier ACKs, and one transport ACK receipt."""
  def __init__(self, port):
    self.control_drops = set()
    self.control_duplicates = self.receipt_drops = 0
    self.ack_seq = None
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
            raise AssertionError('Oversized pause datagram')
          upstream = sock is self.front
          if upstream:
            address = source
          if address is None:
            continue
          key = None
          if len(packet) > 16 and packet[0] == 0x74 and packet[9] == 0:
            if not upstream and len(packet) == 34 and packet[16] == wire.MessageType.MatchControl:
              key = ('control', packet[21])
            elif upstream and len(packet) == 33 and packet[16] == wire.MessageType.MatchControlAck:
              key = ('ack', struct.unpack_from('<I', packet, 17)[0])
              if self.ack_seq is None:
                self.ack_seq = packet[10:14]
          if key is not None and key not in self.control_drops:
            if len(self.control_drops) >= 8:
              raise AssertionError('Control fault fixture exceeded its record bound')
            self.control_drops.add(key)
            continue
          if (not upstream and len(packet) == 14 and packet[0] == 0x74 and packet[9] == 255
              and packet[10:14] == self.ack_seq and not self.receipt_drops):
            self.receipt_drops += 1
            continue
          if upstream:
            self.back.send(packet)
          else:
            self.front.sendto(packet, address)
          if key is not None:
            if upstream:
              self.back.send(packet)
            else:
              self.front.sendto(packet, address)
            self.control_duplicates += 1
    except BaseException as error:
      self.errors.append(error)
    finally:
      self.front.close()
      self.back.close()


class MatchControlBufferTest(unittest.TestCase):
  def origin(self):
    settings = ServerSettings()
    env = MatchOracle(settings)
    try:
      buffers = MatchBuffers(ClientLimits(receive_bytes=512), MatchResumeLimits())
      origin = pack_origin(settings, env)
      data = (wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0]) + pack_session_token(99)
              + wire.pack_state_snapshot(0, origin))
      for byte in data:
        buffers.feed(bytes([byte]), now=1)
      return buffers
    finally:
      env.close()

  def test_fragmented_control_is_not_exposed_before_its_hash_arrives(self):
    buffers = self.origin()
    old = buffers.control
    control = MatchControl(1, PAUSED, 0, old.state_hash)
    packet = pack_control(control)
    for byte in packet[:-1]:
      buffers.feed(bytes([byte]), now=1)
      self.assertEqual(buffers.next_control(), old)
    buffers.feed(packet[-1:], now=1)
    self.assertEqual(buffers.next_control(), control)
    self.assertEqual(buffers.applied_control, old)
    buffers.consume_control(control)
    self.assertEqual(buffers.applied_control, control)
    self.assertEqual(buffers.pending_controls, ())

  def test_commit_and_repause_are_retained_in_order_with_two_record_limit(self):
    buffers = self.origin()
    digest = buffers.control.state_hash
    paused = MatchControl(1, PAUSED, 0, digest)
    prepared = MatchControl(2, RESUMING, 0, digest)
    committed = MatchControl(2, RUNNING, 0, digest)
    next_pause = MatchControl(3, PAUSED, 0, digest)
    for state in (paused, prepared):
      buffers.feed(pack_control(state), now=1)
      buffers.consume_control(state)
    buffers.feed(pack_control(committed) + pack_control(next_pause), now=1)
    self.assertEqual(buffers.pending_controls, (committed, next_pause))
    self.assertEqual(buffers.next_control(), committed)
    buffers.consume_control(committed)
    self.assertEqual(buffers.next_control(), next_pause)
    with self.assertRaisesRegex(ClientFailure, 'control_before_ack'):
      buffers.feed(pack_control(MatchControl(4, RESUMING, 0, digest)), now=1)
    self.assertEqual(buffers.pending_controls, ())
    self.assertIsNone(buffers.control)
    self.assertEqual(buffers.retained_snapshot_bytes, 0)

  def test_authority_after_pause_and_wrong_boundary_fail_before_buffering(self):
    for variant in ('frame', 'authority', 'early_prepare'):
      buffers = self.origin()
      digest = buffers.control.state_hash
      first = MatchControl(1, PAUSED, int(variant == 'frame'), digest)
      with self.assertRaises(ClientFailure):
        buffers.feed(pack_control(first), now=1)
        if variant == 'authority':
          buffers.feed(wire.pack_authoritative_frame(0, [wire.default_slot_input()]), now=1)
        elif variant == 'early_prepare':
          buffers.feed(pack_control(MatchControl(2, RESUMING, 0, digest)), now=1)
      self.assertEqual(len(buffers.authority), 0)

  def test_ready_carries_epoch_and_rejects_old_v5_bytes(self):
    # 2026-09-13: control epoch retains the same bytes under v7 cadence.
    # golden = bytes.fromhex('12 0600 0a00 0a00 0a00 10270000 78563412')
    golden = bytes.fromhex('12 0700 3200 3200 0200 10270000 78563412')
    self.assertEqual(pack_match_ready(0x12345678), golden)
    self.assertEqual(unpack_match_ready(golden, include_epoch=True)[1], 0x12345678)
    for packet in (bytes.fromhex('12 0500 0a00 0a00 0a00 10270000'),
                   golden[:1] + b'\x05\x00' + golden[3:]):
      with self.assertRaises(ValueError):
        unpack_match_ready(packet)

  def test_hash_beyond_frozen_boundary_rejects_and_refunds_control_queue(self):
    buffers = self.origin()
    paused = MatchControl(1, PAUSED, 0, buffers.control.state_hash)
    buffers.feed(pack_control(paused), now=1)
    with self.assertRaisesRegex(ClientFailure, 'hash_while_paused'):
      buffers.feed(wire.pack_state_hash(0, paused.state_hash), now=1)
    self.assertEqual(buffers.pending_controls, ())
    self.assertEqual(buffers.hashes, {})

  def test_duplicate_commit_after_later_authority_is_idempotent(self):
    buffers = self.origin()
    buffers.phase = 'streaming'
    digest = buffers.control.state_hash
    states = (MatchControl(1, PAUSED, 0, digest), MatchControl(2, RESUMING, 0, digest),
              MatchControl(2, RUNNING, 0, digest))
    for state in states:
      buffers.feed(pack_control(state), now=1)
      buffers.consume_control(state)
    buffers.feed(wire.pack_authoritative_frame(0, [wire.default_slot_input()]), now=1)
    self.assertEqual(buffers.next_authority, 1)
    buffers.feed(pack_control(states[-1]), now=1)
    self.assertEqual(buffers.pending_controls, ())
    self.assertEqual(buffers.applied_control, states[-1])
    self.assertEqual(len(buffers.authority), 1)


class MatchPauseNetworkTest(unittest.TestCase):
  def setUp(self):
    self.servers, self.players, self.clients, self.engines, self.inputs = [], [], [], [], []
    self.hosts, self.relays = [], []

  def tearDown(self):
    # 2026-09-10: host and real relay owners are also required to stop.
    # for owner in self.players + self.clients + self.servers:
    for owner in self.hosts + self.players + self.clients + self.servers + self.relays:
      owner.close()
    for buffer in self.inputs:
      buffer.close()
    self.assertTrue(all(env.closed == 1 for env in self.engines))

  def factory(self, settings):
    env = MatchOracle(settings)
    self.engines.append(env)
    return env

  def server(self, transport, players=2, **limits):
    cls = MatchServer if transport == 'tcp' else MatchUDPServer
    server = cls(listen_host='127.0.0.1', listen_port=0, left_agents=1, right_agents=players - 1,
        engine_factory=self.factory, state_hash_interval=1, limits=ServerLimits(**limits))
    self.servers.append(server)
    server.start()
    return server

  # 2026-09-10: optional real UDP relay endpoint for the same production player.
  # def player(self, server, transport):
  def player(self, server, transport, port=None):
    inputs = InputBuffer()
    self.inputs.append(inputs)
    # player = NetworkPlayer('127.0.0.1', server.listen_port, transport=transport,
    player = NetworkPlayer('127.0.0.1', server.listen_port if port is None else port, transport=transport,
        engine_factory=self.factory, input_provider=inputs.sample,
        on_control=lambda control: inputs.set_suspended(control.phase != RUNNING),
        reconnect_limits=ReconnectLimits(base_seconds=.01, max_seconds=.03, recovery_seconds=6))
    self.players.append(player)
    player.start()
    return player, inputs

  def low_client(self, server, transport, **connect_options):
    cls = MatchTCPClient if transport == 'tcp' else MatchUDPClient
    client = cls('127.0.0.1', server.listen_port)
    self.clients.append(client)
    client.connect(**connect_options)
    return client

  def wait(self, predicate, players=(), seconds=8):
    deadline = time.monotonic() + seconds
    while not predicate():
      for player in players:
        player.tick()
      self.assertLess(time.monotonic(), deadline, 'Pause network condition timed out')
      time.sleep(.002)

  def advance(self, server, players):
    for player in players:
      player.tick()
    result = server.run_one_frame(100)
    self.wait(lambda: all(p.client.logic.get_last_confirmed_frame_id() == result[0] for p in players), players)
    return result

  def pause(self, server, players):
    state = server.pause()
    self.assertEqual(state.phase, PAUSED)
    self.wait(lambda: server.stats()['control_pending_peers'] == 0, players)
    self.assertTrue(all(p.client.logic.control_state == state for p in players))
    return state

  def resume(self, server, players):
    state = server.resume()
    self.assertEqual(state.phase, RESUMING)
    self.wait(lambda: server.stats()['control']['phase'] == RUNNING, players)
    self.wait(lambda: all(p.client.logic.control_state.phase == RUNNING for p in players), players)
    return state

  def test_both_transports_pause_rewind_release_held_controls_and_resume_same_frame(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport)
        first, keys = self.player(server, transport)
        second, _ = self.player(server, transport)
        players = first, second
        self.wait(server.participants_ready, players)
        self.advance(server, players)
        keys.feed(keys=('z', 'w'))
        for player in players:
          for _ in range(3):
            player.tick()
        self.assertGreater(first.client.logic.get_current_frame_id(), 1)
        paused = self.pause(server, players)
        expected = server._call(lambda: engine_digest(server._runtime.env))
        for player in players:
          self.assertEqual(player.client.logic.get_current_frame_id(), 1)
          self.assertEqual(engine_digest(player.env), expected)
          self.assertEqual(player.client.logic.stats()['sampled_input_frames'], 0)
        keys.feed(pressed_keys=('v',), keys=('z', 'w'))
        for _ in range(10):
          for player in players:
            player.tick()
          with self.assertRaisesRegex(ServerFailure, 'match_paused'):
            server.run_one_frame(0)
        self.assertEqual(server._call(lambda: engine_digest(server._runtime.env)), expected)
        self.assertEqual(server.stats()['control'], dict(epoch=1, phase=PAUSED, next_frame=1))
        self.resume(server, players)
        frame, inputs = self.advance(server, players)
        self.assertEqual(frame, paused.next_frame)
        self.assertEqual(inputs, [wire.default_slot_input()] * 2)
        keys.feed()
        keys.feed(pressed_keys=('z',))
        # Previously predicted same-epoch frames remain immutable; the fresh
        # action is sampled at a future frame and then reaches authority once.
        seen = []
        for _ in range(8):
          seen.append(self.advance(server, players)[1][0].buttons)
        self.assertEqual(seen.count(4), 1)

  def test_old_epoch_input_is_ignored_after_resume_even_if_frame_number_reused(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        self.pause(server, (player,))
        self.resume(server, (player,))
        client = player.client.client
        old = pack_epoch_input(0, 1, [(0, wire.SlotInput(1, 0, 4))])
        with client._lock:
          self.assertTrue(client._enqueue_locked(old))
        frame, values = self.advance(server, (player,))
        self.assertEqual((frame, values), (1, [wire.default_slot_input()]))
        self.assertFalse(client.is_disconnected())

  def test_resume_waits_for_each_online_peer_and_heartbeat_cannot_extend_ack_deadline(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1, ready_timeout=.3, idle_timeout=.15, heartbeat_interval=.03)
        client = self.low_client(server, transport)
        self.assertTrue(client.send_ready())
        self.wait(server.participants_ready)
        self.assertTrue(client.send_frame_entries(0, [(0, wire.default_slot_input())]))
        server.run_one_frame(100)
        server.pause()
        state = server.resume()
        self.assertEqual(state.phase, PAUSED)  # Pause ACK itself is still pending.
        start = time.monotonic()
        # 2026-09-10: use the existing thread-safe facade method.
        # while server.connected_client_count:
        while server.get_connected_client_count():
          with client._lock:
            if not client.is_disconnected():
              client._enqueue_locked(wire.pack_heartbeat(1, 1))
          self.assertLess(time.monotonic() - start, 1.5)
          time.sleep(.02)
        self.assertEqual(server.stats()['last_peer_failure'], 'control_ack_timeout')
        self.assertEqual(server.stats()['control']['phase'], RUNNING)
        self.assertEqual(server._call(lambda: server._runtime.window.frame_id), 1)

  def test_control_request_during_collection_finishes_exactly_the_in_progress_frame(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready)
        results, errors = [], []
        def frame():
          try:
            results.append(server.run_one_frame(1000))
          except BaseException as error:
            errors.append(error)
        thread = threading.Thread(target=frame, name='football-pause-frame-test')
        thread.start()
        try:
          self.wait(lambda: server._call(lambda: server._runtime.collecting))
          requested = server.pause()
          self.assertEqual(requested.phase, RUNNING)
          player.tick()
        finally:
          thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0][0], 0)
        self.wait(lambda: server.stats()['control_pending_peers'] == 0, (player,))
        self.assertEqual(server.stats()['control'], dict(epoch=1, phase=PAUSED, next_frame=1))
        self.assertEqual(player.client.logic.get_last_confirmed_frame_id(), 0)

  def test_reconnect_restores_paused_origin_and_waits_for_resume_commit(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, inputs = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        paused = self.pause(server, (player,))
        player.client.client.close()
        self.wait(lambda: player.client.stats()['restores'] == 1, (player,))
        self.assertEqual(player.client.logic.control_state, paused)
        self.assertEqual(player.client.logic.get_current_frame_id(), 1)
        inputs.feed(pressed_keys=('z',))
        player.tick()
        self.assertEqual(player.client.logic.stats()['sampled_input_frames'], 0)
        self.resume(server, (player,))
        self.assertEqual(self.advance(server, (player,))[1], [wire.default_slot_input()])

  def test_stale_snapshot_ready_cannot_hand_back_but_same_capability_can_retry(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        self.pause(server, (player,))
        token = player.client.client.session_token
        session = (42, 1, 0)
        # Close the whole player to prevent its automatic worker taking the token.
        player.close()
        # self.wait(lambda: server.connected_client_count == 0)
        self.wait(lambda: server.get_connected_client_count() == 0)
        stale = self.low_client(server, transport, resume_token=token,
            expected_session=session, expected_slots=(0,), minimum_frame=1)
        self.assertEqual(stale.get_match_control().phase, PAUSED)
        server.resume()  # No online ACK participants; epoch advances to 2.
        self.assertTrue(stale.send_ready())
        self.wait(stale.is_disconnected)
        self.assertEqual(server.stats()['last_peer_failure'], 'stale_match_ready')
        # self.wait(lambda: server.connected_client_count == 0)
        self.wait(lambda: server.get_connected_client_count() == 0)
        fresh = self.low_client(server, transport, resume_token=token,
            expected_session=session, expected_slots=(0,), minimum_frame=1)
        self.assertEqual((fresh.get_match_control().epoch, fresh.get_match_control().phase), (2, RUNNING))
        self.assertTrue(fresh.send_ready())
        self.wait(lambda: fresh.resume_handback_complete)
        self.assertTrue(server.participants_ready())

  def test_pause_before_first_frame_still_processes_controls_without_lobby_prediction(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready)
        self.pause(server, (player,))
        self.assertEqual(player.client.logic.get_current_frame_id(), 0)
        self.assertEqual(player.client.logic.stats()['sampled_input_frames'], 0)
        self.resume(server, (player,))
        self.assertEqual(self.advance(server, (player,))[0], 0)

  def test_finish_while_paused_delivers_same_digest_and_terminal_ack(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        self.pause(server, (player,))
        digest = engine_digest(player.env)
        self.assertEqual(server.finish_match(), 1)
        self.wait(lambda: player.stats()['ended'], (player,))
        self.assertEqual(engine_digest(player.env), digest)
        player.flush_end_ack()
        self.wait(server.finish_acknowledged)

  def test_end_supersedes_unconsumed_pause_ack_deadline(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1, ready_timeout=.3)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        server.pause()
        server.finish_match()
        self.wait(lambda: player.client.client.match_end is not None)
        self.wait(lambda: player.stats()['ended'], (player,))
        player.flush_end_ack()
        self.wait(server.finish_acknowledged)
        # This pending pause is intentionally superseded, not acknowledged by
        # the completed loop. End must retain the peer for its UDP drain grace.
        self.assertEqual(server.stats()['control_pending_peers'], 1)
        time.sleep(.4)
        self.assertEqual(server.get_connected_client_count(), 1)
        self.assertIsNone(server.stats()['last_peer_failure'])

  def test_targeted_udp_control_ack_and_receipt_loss_preserves_barriers(self):
    server = self.server('udp', players=1)
    relay = PauseFaultRelay(server.listen_port)
    self.relays.append(relay)
    player, _ = self.player(server, 'udp', port=relay.port)
    self.wait(server.participants_ready, (player,))
    self.advance(server, (player,))
    self.pause(server, (player,))
    self.resume(server, (player,))
    self.assertEqual(self.advance(server, (player,))[0], 1)
    self.assertEqual(relay.control_drops, {('control', PAUSED), ('control', RESUMING),
                                        ('control', RUNNING), ('ack', 1), ('ack', 2)})
    self.assertEqual(relay.receipt_drops, 1)
    self.assertGreaterEqual(relay.control_duplicates, 5)
    self.assertLessEqual(relay.maximum, 1200)
    self.assertEqual(player.client.stats()['restores'], 0)

  def test_repause_during_resume_preparation_consumes_commit_and_remains_frozen(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        self.pause(server, (player,))
        for epoch in range(3, 24, 2):
          self.assertEqual(server.resume().phase, RESUMING)
          self.assertEqual(server.pause().phase, RESUMING)
          self.wait(lambda: server.stats()['control']['epoch'] == epoch and
                    server.stats()['control_pending_peers'] == 0, (player,))
          self.assertEqual(player.client.logic.control_state.phase, PAUSED)
          self.assertEqual(player.client.logic.get_current_frame_id(), 1)
          self.assertEqual(player.client.logic.stats()['sampled_input_frames'], 0)
          with player.client.client._lock:
            self.assertEqual(player.client.client._buffers.pending_controls, ())
            self.assertEqual(len(player.client.client._buffers.timestamps), 0)
        self.assertEqual(server._call(lambda: server._runtime.window.stats()['frames']), 0)

  def test_io_close_during_control_read_or_ack_enters_automatic_recovery(self):
    for transport in ('tcp', 'udp'):
      for location in ('read', 'ack'):
        with self.subTest(transport=transport, location=location):
          server = self.server(transport, players=1)
          player, _ = self.player(server, transport)
          self.wait(server.participants_ready, (player,))
          self.advance(server, (player,))
          client = player.client.client
          if location == 'read':
            original = client.get_match_control
            def read():
              client.close()
              return original()
            player.client.logic._control_reader = read
          else:
            def ack(control):
              client.close()
              return False
            client.acknowledge_control = ack
            server.pause()
            self.wait(lambda: client.get_match_control().phase == PAUSED)
          player.tick()
          self.assertFalse(player.stats()['closed'])
          self.wait(lambda: player.client.stats()['restores'] == 1, (player,))
          self.assertIsNone(player.client.failure_reason)
          self.assertIsNone(player.client.logic.failure_reason)
          self.assertEqual(player.client.logic.control_state.phase, PAUSED if location == 'ack' else RUNNING)

  def test_invalid_old_epoch_values_future_epoch_and_legacy_inputs_cannot_mutate_authority(self):
    for transport in ('tcp', 'udp'):
      for variant, reason in (('slot', 'invalid_input'), ('future', 'future_input_epoch'),
                              ('legacy', 'match_input_epoch_required')):
        with self.subTest(transport=transport, variant=variant):
          server = self.server(transport, players=1)
          player, _ = self.player(server, transport)
          self.wait(server.participants_ready, (player,))
          self.advance(server, (player,))
          self.pause(server, (player,))
          self.resume(server, (player,))
          client = player.client.client
          digest = server._call(lambda: engine_digest(server._runtime.env))
          if variant == 'legacy':
            packet = wire.pack_client_frame_input(1, [(0, wire.SlotInput(1, 0, 4))])
          else:
            packet = pack_epoch_input(3 if variant == 'future' else 0, 1, [(0, wire.SlotInput(1, 0, 4))])
            if variant == 'slot':
              packet = packet[:11] + b'\x02\x00' + packet[13:]
          with client._lock:
            self.assertTrue(client._enqueue_locked(packet))
          self.wait(client.is_disconnected)
          self.assertEqual(server.stats()['last_peer_failure'], reason)
          self.assertEqual(server._call(lambda: engine_digest(server._runtime.env)), digest)

  def test_host_pause_save_resume_and_recording_replay_use_exact_authority(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport), tempfile.TemporaryDirectory() as directory:
        save, record = str(Path(directory) / 'paused.json'), str(Path(directory) / 'match.jsonl')
        inputs = InputBuffer()
        self.inputs.append(inputs)
        host = HostedMatch(listen_host='127.0.0.1', left=1, right=0, transport=transport,
            engine_factory=self.factory, input_provider=inputs.sample,
            on_control=lambda control: inputs.set_suspended(control.phase != RUNNING),
            save_path=save, record_path=record)
        self.hosts.append(host)
        host.start()
        self.wait(host.server.participants_ready, (host.player,))
        self.assertTrue(host.advance())
        self.pause(host.server, (host.player,))
        digest = host.server._call(lambda: engine_digest(host.server._runtime.env))
        for _ in range(4):
          self.assertFalse(host.advance())
        self.assertEqual(host.save()['digest'], digest)
        self.assertEqual(decode_checkpoint(read_checkpoint(save))[2], digest)
        self.resume(host.server, (host.player,))
        self.assertTrue(host.advance())
        self.assertTrue(host.finish())
        host.close()
        result = playback(record, engine_factory=self.factory)
        self.assertTrue(result['verified'])
        self.assertEqual(result['frames'], 2)

  def test_duplicate_ack_does_not_release_a_newer_barrier(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        self.wait(server.participants_ready, (player,))
        self.advance(server, (player,))
        paused = self.pause(server, (player,))
        self.assertEqual(server.resume().phase, RESUMING)
        client = player.client.client
        with client._lock:
          self.assertTrue(client._enqueue_locked(pack_control_ack(paused)))
        self.wait(lambda: not client.output_pending())
        time.sleep(.03)
        self.assertEqual(server.stats()['control_pending_peers'], 1)
        self.assertEqual(server.stats()['control']['phase'], RESUMING)
        self.assertFalse(client.is_disconnected())
        self.wait(lambda: server.stats()['control']['phase'] == RUNNING, (player,))

  def test_public_server_loop_stops_physics_while_paused_and_exits_after_end(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        server = self.server(transport, players=1)
        player, _ = self.player(server, transport)
        errors, results = [], []
        def run():
          try:
            server.run_loop()
            results.append(True)
          except BaseException as error:
            errors.append(error)
        thread = threading.Thread(target=run, name='football-pause-public-loop-test')
        thread.start()
        try:
          self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() >= 0, (player,))
          server.pause()
          self.wait(lambda: server.stats()['control']['phase'] == PAUSED and
                    server.stats()['control_pending_peers'] == 0, (player,))
          boundary = server.stats()['control']['next_frame']
          digest = server._call(lambda: engine_digest(server._runtime.env))
          until = time.monotonic() + .15
          while time.monotonic() < until:
            player.tick()
            time.sleep(.005)
          self.assertEqual(server._call(lambda: server._runtime.window.frame_id), boundary)
          self.assertEqual(engine_digest(player.env), digest)
          self.resume(server, (player,))
          self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() >= boundary, (player,))
          def finish_between_frames():
            runtime = server._runtime
            if runtime.collecting:
              return False
            runtime.finish_match()
            return True
          self.wait(lambda: server._call(finish_between_frames), (player,))
          self.wait(lambda: player.stats()['ended'], (player,))
          player.flush_end_ack()
          thread.join(3)
          self.assertFalse(thread.is_alive())
          self.assertEqual(errors, [])
          self.assertEqual(results, [True])
        finally:
          server.close()
          thread.join(3)


if __name__ == '__main__':
  unittest.main()
