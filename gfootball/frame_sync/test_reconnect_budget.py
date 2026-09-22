# Copyright 2026 Google LLC
"""Bounded snapshot parsing and actual TCP server/automatic recovery contracts."""
from dataclasses import replace
import socket
import struct
import sys
import threading
import time
import unittest
from unittest import mock
import zlib

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client import ReconnectingFrameSyncClient, ReconnectLimits
from gfootball.frame_sync.client_buffers import ClientLimits, ClientFailure
from gfootball.frame_sync.client_logic import ClientLogicLoop, LogicLimits
from gfootball.frame_sync.client_tcp import FrameSyncClient
from gfootball.frame_sync.resume_protocol import ResumeBuffers, ResumeLimits, pack_session_token
from gfootball.frame_sync.server import FrameSyncServer
from gfootball.frame_sync.server_state import ServerLimits
from gfootball.frame_sync.test_server_budget import EngineOracle
from gfootball.frame_sync.test_tcp_client_budget import Peer, exact, until


def metadata():
  return wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0])


class ResumeBufferTest(unittest.TestCase):
  def make(self, **kwargs):
    return ResumeBuffers(ClientLimits(), ResumeLimits(), restoring=True,
                         expected_session=(42, 1, 0), expected_slots=(0,), **kwargs)

  def test_token_is_required_once_and_nonzero(self):
    state = ResumeBuffers(ClientLimits(), ResumeLimits())
    state.feed(metadata())
    self.assertEqual(state.phase, 'token')
    state.feed(pack_session_token(123)[:4])
    self.assertEqual(state.phase, 'token')
    state.feed(pack_session_token(123)[4:])
    self.assertEqual((state.phase, state.session_token), ('ready', 123))
    with self.assertRaises(ClientFailure):
      state.feed(pack_session_token(123))
    for token in (0, -1, True, 2**64, '1'):
      with self.assertRaises(ValueError):
        pack_session_token(token)

  def test_maximum_snapshot_streamed_in_small_reads_and_exact_refund(self):
    state = self.make()
    payload = bytes(range(256)) * 4096
    packet = metadata() + wire.pack_state_snapshot(100, payload)
    peak = 0
    for offset in range(0, len(packet), 137):
      state.feed(packet[offset:offset + 137])
      peak = max(peak, state.retained_snapshot_bytes)
      self.assertLessEqual(len(state.receive), 22)
    self.assertEqual(state.snapshot, (100, payload))
    self.assertEqual(state.next_authority, 100)
    self.assertLessEqual(peak, len(payload) + sys.getsizeof(bytearray()) + 1)
    state.fail('closed')
    self.assertEqual(state.retained_snapshot_bytes, 0)

  def test_size_and_identity_validation_precede_snapshot_allocation(self):
    for header in (struct.pack('<BII', 13, 1, 0), struct.pack('<BII', 13, 1, 2**32-1),
                   struct.pack('<BII', 13, 0xffffffff, 1)):
      state = self.make()
      state.feed(metadata())
      with self.assertRaisesRegex(ClientFailure, 'invalid_resume_snapshot'):
        state.feed(header)
      self.assertEqual(state.retained_snapshot_bytes, 0)
    for packet, reason in ((wire.pack_session_start(43, 1, 0), 'resume_session_mismatch'),
                            (wire.pack_session_start(42, 1, 0) + wire.pack_slot_assignment([0, 0]), 'invalid_slots')):
      state = self.make()
      with self.assertRaisesRegex(ClientFailure, reason):
        state.feed(packet)
      self.assertEqual(state.retained_snapshot_bytes, 0)

  def test_missing_snapshot_wrong_slot_and_zero_token_fail(self):
    state = self.make()
    with self.assertRaisesRegex(ClientFailure, 'missing_resume_snapshot'):
      state.feed(metadata() + wire.pack_ready())
    state = ResumeBuffers(ClientLimits(), ResumeLimits(), restoring=True,
                          expected_session=(42, 1, 1), expected_slots=(0,))
    with self.assertRaisesRegex(ClientFailure, 'resume_slots_mismatch'):
      state.feed(wire.pack_session_start(42, 1, 1) + wire.pack_slot_assignment([1]))
    state = ResumeBuffers(ClientLimits(), ResumeLimits())
    with self.assertRaisesRegex(ClientFailure, 'invalid_session_token'):
      state.feed(metadata() + bytes([14]) + bytes(8))

  def test_native_pre_ready_authority_and_hash_use_bounded_common_queues(self):
    state = self.make()
    value = wire.default_slot_input()
    state.feed(metadata() + wire.pack_state_snapshot(7, b'engine') +
               wire.pack_authoritative_frame(7, [value]) + wire.pack_state_hash(7, 99))
    self.assertEqual(state.phase, 'ready')
    self.assertEqual(state.pop_authority(), (7, [value]))
    self.assertEqual(state.hashes, {7: 99})
    self.assertEqual(state.snapshot, (7, b'engine'))

  def test_partial_snapshot_cleanup_and_second_snapshot_rejected(self):
    state = self.make()
    state.feed(metadata() + struct.pack('<BII', 13, 4, 1000) + b'a')
    self.assertGreater(state.retained_snapshot_bytes, 1000)
    state.fail('cancelled')
    self.assertEqual(state.retained_snapshot_bytes, 0)
    # 2026-09-10: keep the second-snapshot check in its state-fixture class.
    state = self.make()
    state.feed(metadata() + wire.pack_state_snapshot(7, b'x'))
    with self.assertRaises(ClientFailure):
      state.feed(wire.pack_state_snapshot(8, b'x'))
    self.assertEqual(state.retained_snapshot_bytes, 0)

  def test_stale_snapshot_and_early_handback_are_rejected(self):
    state = self.make(minimum_frame=4)
    with self.assertRaisesRegex(ClientFailure, 'invalid_resume_snapshot'):
      state.feed(metadata() + wire.pack_state_snapshot(3, b'a'))
    self.assertEqual(state.retained_snapshot_bytes, 0)
    state = self.make()
    state.feed(metadata() + wire.pack_state_snapshot(4, b'a'))
    with self.assertRaisesRegex(ClientFailure, 'unexpected_handback'):
      state.feed(wire.pack_handback_notify(0, 4))


class ResumeTransportTest(unittest.TestCase):
  def test_expired_deadline_does_not_establish_a_connection(self):
    with socket.socket() as listener:
      listener.bind(('127.0.0.1', 0))
      listener.listen()
      listener.settimeout(.03)
      with FrameSyncClient('127.0.0.1', listener.getsockname()[1]) as client:
        with self.assertRaisesRegex(ClientFailure, 'recovery_timeout'):
          client.connect(deadline=time.monotonic() - 1)
        with self.assertRaises(socket.timeout):
          listener.accept()
        self.assertFalse(client.stats()['worker_alive'])

  def test_actual_maximum_snapshot_and_authority_before_ready(self):
    payload = bytes(range(256)) * 4096
    def script(peer, stop):
      self.assertEqual(exact(peer, 9), wire.pack_reconnect_request(123))
      peer.sendall(metadata() + wire.pack_state_snapshot(5, payload) +
                   wire.pack_authoritative_frame(5, [wire.default_slot_input()]))
      self.assertEqual(exact(peer, 1), wire.pack_ready())
      peer.sendall(wire.pack_handback_notify(0, 6))
      stop.wait(2)
    with Peer(script) as peer, FrameSyncClient('127.0.0.1', peer.port) as client:
      client.connect(resume_token=123, expected_session=(42, 1, 0), expected_slots=(0,))
      self.assertEqual(client.take_resume_snapshot(), (5, payload))
      self.assertEqual(client.stats()['snapshot_bytes'], 0)
      client.send_ready()
      until(lambda: client.resume_handback_complete)
      self.assertEqual(client.pop_authoritative_frame()[0], 5)

  def test_partial_snapshot_obeys_absolute_handshake_deadline_and_cleanup(self):
    def script(peer, stop):
      exact(peer, 9)
      peer.sendall(metadata() + struct.pack('<BII', 13, 1, 100000) + bytes(2000))
      self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer, FrameSyncClient('127.0.0.1', peer.port, limits=ClientLimits(handshake_timeout=.5)) as client:
      with self.assertRaisesRegex(ClientFailure, 'recovery_timeout'):
        client.connect(resume_token=1, expected_session=(42, 1, 0), expected_slots=(0,), deadline=time.monotonic() + .08)
      self.assertEqual(client.stats()['snapshot_bytes'], 0)
      self.assertFalse(client.stats()['worker_alive'])

  def test_oversized_header_rejected_before_receiving_declared_body(self):
    def script(peer, stop):
      exact(peer, 9)
      peer.sendall(metadata() + struct.pack('<BII', 13, 1, 0xffffffff))
      self.assertEqual(peer.recv(1), b'')
    with Peer(script) as peer, FrameSyncClient('127.0.0.1', peer.port) as client:
      with self.assertRaisesRegex(ClientFailure, 'invalid_resume_snapshot'):
        client.connect(resume_token=1, expected_session=(42, 1, 0), expected_slots=(0,))
      self.assertEqual(client.stats()['snapshot_bytes'], 0)
    # 2026-09-10: this block was misplaced by the prior test insertion; moved above.
    # state = self.make()
    # state.feed(metadata() + wire.pack_state_snapshot(7, b'x'))
    # with self.assertRaises(ClientFailure):
    #   state.feed(wire.pack_state_snapshot(8, b'x'))
    # self.assertEqual(state.retained_snapshot_bytes, 0)


class Replica:
  """Independent Adler32 input reducer, explicitly not GameEnv."""
  def __init__(self):
    self.frames, self.digest = 0, 1
    self.owner = threading.current_thread()
    self.restored = []
    self.on_restore = None

  def get_state(self, _=''):
    return struct.pack('<II', self.frames, self.digest)

  def get_state_digest(self):
    return self.get_state()

  def step_with_input(self, data):
    if self.owner is not threading.current_thread():
      raise AssertionError('Replica stepped on wrong thread')
    self.digest = zlib.adler32(data, self.digest)
    self.frames += 1

  def set_state(self, data):
    if self.owner is not threading.current_thread():
      raise AssertionError('Replica restored on wrong thread')
    if self.on_restore:
      self.on_restore()
    self.frames, self.digest = struct.unpack('<II', data)
    self.restored.append(self.frames)


class ReconnectClientTest(unittest.TestCase):
  def setUp(self):
    self.servers, self.clients = [], []

  def tearDown(self):
    for client in self.clients:
      client.close()
      self.assertFalse(client.stats()['worker_alive'])
      self.assertEqual(client.stats()['snapshot_bytes'], 0)
    for server in self.servers:
      server.stop()

  def make(self, **kwargs):
    server = FrameSyncServer('127.0.0.1', 0, engine_factory=EngineOracle, state_hash_interval=1,
                             limits=ServerLimits(heartbeat_interval=.05), **kwargs.pop('server_options', {}))
    self.servers.append(server)
    server.start()
    options = dict(reconnect_limits=ReconnectLimits(base_seconds=.02, max_seconds=.05, recovery_seconds=2),
                   limits=ClientLimits(handshake_timeout=.2, connect_timeout=.2))
    options.update(kwargs)
    client = ReconnectingFrameSyncClient('127.0.0.1', server.listen_port,
                 lambda: [(0, wire.SlotInput(.5, -.25, 4))], **options)
    self.clients.append(client)
    self.assertEqual(client.connect(), ((42, 1, 0), [0]))
    replica = Replica()
    client.attach_logic(replica, limits=LogicLimits(prediction_frames=0))
    until(server.all_clients_ready)
    return client, server, replica

  def frame(self, client, server):
    client.run_one_tick()
    frame, _ = server.run_one_frame(timeout_ms=500)
    until(lambda: client.client.has_authoritative_frame())
    client.run_one_tick()
    self.assertEqual(client.logic.get_last_confirmed_frame_id(), frame)
    self.assertEqual(client._env.get_state(), server.get_env().get_state())
    return frame

  def test_wire_token_automatic_restore_before_ready_and_contiguous_hashes(self):
    client, server, replica = self.make()
    self.assertEqual(client._token, server.get_session_tokens()[0])
    for _ in range(3):
      self.frame(client, server)
    events = []
    client.set_on_disconnect(lambda: events.append('disconnect'))
    client.set_on_reconnect(lambda session, slots: events.append(('restored', session, slots)))
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    self.assertEqual(server.stats()['bots'], (0,))
    self.assertFalse(server.all_clients_ready())
    for _ in range(3):
      server.run_one_frame(timeout_ms=0)  # Authority after snapshot is deferred.
    replica.on_restore = lambda: self.assertFalse(server.all_clients_ready())
    client.tick()
    until(server.all_clients_ready)
    self.assertEqual(client.stats()['state'], 'handback')
    self.assertEqual(events, ['disconnect'])
    until(lambda: client.client.resume_handback_complete)
    client.tick()
    self.assertEqual(replica.restored, [3])
    self.assertEqual(client.logic.get_current_frame_id(), 3)
    self.assertEqual(events, ['disconnect', ('restored', (42, 1, 0), [0])])
    until(lambda: client.client.stats()['authority_frames'] == 3)
    client.run_one_tick()
    self.assertEqual(client.logic.get_last_confirmed_frame_id(), 5)
    self.assertEqual(client.logic.stats()['verified_hashes'], 3)
    self.assertEqual(replica.get_state(), server.get_env().get_state())
    for _ in range(5):
      self.frame(client, server)
    self.assertEqual(client.logic.stats()['verified_hashes'], 8)
    self.assertEqual(client.stats()['restores'], 1)
    self.assertEqual(client.stats()['snapshot_bytes'], 0)

  def test_repeated_disconnect_reclaims_old_workers_and_engine_stays_on_owner(self):
    client, server, replica = self.make()
    self.frame(client, server)
    for _ in range(5):
      old_worker = client.client._recv_thread
      client.client.close()
      until(lambda: client.stats()['state'] == 'restoring')
      client.tick()
      until(server.all_clients_ready)
      until(lambda: client.client.resume_handback_complete)
      client.tick()
      self.frame(client, server)
      self.assertFalse(old_worker.is_alive())
      self.assertEqual(server.get_connected_client_count(), 1)
    self.assertEqual(client.stats()['restores'], 5)
    self.assertEqual(len(replica.restored), 5)

  def test_attempt_limit_gives_up_once_and_never_restarts_on_ticks(self):
    client, server, _ = self.make(reconnect_limits=ReconnectLimits(base_seconds=.02, max_seconds=.04,
                                                                 max_attempts=3, recovery_seconds=2))
    self.frame(client, server)
    notices = []
    client.set_on_give_up(lambda: notices.append('done'))
    server.stop()
    until(lambda: client.stats()['state'] == 'gave_up')
    count = client.stats()['total_attempts']
    self.assertEqual(count, 3)
    self.assertEqual(client.failure_reason, 'reconnect_exhausted')
    for _ in range(1000):
      client.tick()
    time.sleep(.05)
    self.assertEqual(client.stats()['total_attempts'], count)
    self.assertEqual(notices, ['done'])
    self.assertFalse(client.stats()['worker_alive'])

  def test_restore_error_never_sends_ready_or_reports_success(self):
    client, server, replica = self.make()
    self.frame(client, server)
    events = []
    client.set_on_reconnect(lambda *_: events.append('bad success'))
    def fail():
      raise RuntimeError('Engine restore failed')
    replica.on_restore = fail
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    with self.assertRaisesRegex(RuntimeError, 'Engine restore failed'):
      client.tick()
    self.assertEqual(events, [])
    self.assertEqual(client.failure_reason, 'restore_or_callback_failed')
    self.assertEqual(server.stats()['bots'], (0,))
    self.assertFalse(server.all_clients_ready())

  def test_invalid_authority_is_terminal_without_reconnecting(self):
    client, server, _ = self.make()
    self.frame(client, server)
    server.send_to_all(struct.pack('<BIH', 3, 100, 65535))
    until(lambda: client.stats()['state'] == 'gave_up')
    self.assertEqual(client.failure_reason, 'invalid_authority')
    self.assertEqual(client.stats()['total_attempts'], 0)

  def test_close_during_backoff_is_terminal_and_clears_all_ownership(self):
    client, server, _ = self.make(reconnect_limits=ReconnectLimits(base_seconds=.2, max_seconds=.2))
    self.frame(client, server)
    server.stop()
    until(lambda: client.stats()['state'] == 'backoff' and client.stats()['attempts'] == 1)
    client.close()
    attempts = client.stats()['total_attempts']
    for _ in range(100):
      client.tick()
    self.assertEqual(client.stats()['state'], 'closed')
    self.assertEqual(client.stats()['total_attempts'], attempts)

  def test_close_with_pending_snapshot_refunds_without_engine_restore(self):
    client, server, replica = self.make()
    self.frame(client, server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    self.assertGreater(client.stats()['snapshot_bytes'], 0)
    client.close()
    self.assertEqual(client.stats()['snapshot_bytes'], 0)
    self.assertEqual(replica.restored, [])

  def test_engine_owner_guard_and_reconnect_limit_validation(self):
    client, _, _ = self.make()
    errors = []
    def tick():
      try:
        client.tick()
      except RuntimeError as error:
        errors.append(str(error))
    worker = threading.Thread(target=tick, name='football-reconnect-test-owner')
    worker.start()
    worker.join(1)
    self.assertEqual(len(errors), 1)
    for kwargs in (dict(max_attempts=True), dict(base_seconds=1, max_seconds=.5),
                   dict(recovery_seconds=float('nan')), dict(max_attempts=1001)):
      with self.assertRaises(ValueError):
        ReconnectLimits(**kwargs)

  def test_server_first_can_explicitly_negotiate_v3_after_legacy_metadata(self):
    client, server, _ = self.make(server_options=dict(handshake='server_first'))
    self.assertEqual(client._token, server.get_session_tokens()[0])
    self.frame(client, server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    client.tick()
    until(lambda: client.client.resume_handback_complete)
    client.tick()
    self.assertEqual(client.stats()['restores'], 1)

  def test_tick_does_not_wait_for_live_resume_handshake_and_close_cancels_it(self):
    stalled = threading.Event()
    initial_ready = threading.Event()
    def initial(peer, stop):
      self.assertEqual(exact(peer, 5), wire.pack_version_negotiate(3, 3))
      peer.sendall(metadata() + pack_session_token(123))
      self.assertEqual(exact(peer, 1), wire.pack_ready())
      initial_ready.set()
      while peer.recv(4096):
        pass
    def resume(peer, stop):
      self.assertEqual(exact(peer, 9), wire.pack_reconnect_request(123))
      peer.sendall(metadata())
      stalled.set()
      # 2026-09-10: cancel with unread handshake bytes can produce TCP reset
      # on Windows; both EOF and ECONNRESET prove the actual socket closed.
      # self.assertEqual(peer.recv(1), b'')
      try:
        self.assertEqual(peer.recv(1), b'')
      except ConnectionResetError:
        pass
    with Peer(initial, resume) as peer:
      client = ReconnectingFrameSyncClient('127.0.0.1', peer.port,
                                           lambda: [(0, wire.default_slot_input())])
      self.clients.append(client)
      client.connect()
      client.attach_logic(Replica())
      self.assertTrue(initial_ready.wait(1))
      client.client.close()
      self.assertTrue(stalled.wait(1))
      start = time.monotonic()
      for _ in range(1000):
        client.tick()
      self.assertLess(time.monotonic() - start, .15)
      self.assertEqual(client.stats()['state'], 'attempting')
      self.assertEqual(client.stats()['total_attempts'], 1)
      start = time.monotonic()
      client.close()
      self.assertLess(time.monotonic() - start, .5)
      self.assertFalse(client.stats()['worker_alive'])

  def test_close_during_active_engine_restore_keeps_payload_charged_until_return(self):
    client, server, replica = self.make()
    self.frame(client, server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    observed = []
    def during_restore():
      client.close()
      observed.append(client.stats())
    replica.on_restore = during_restore
    client.tick()
    self.assertEqual(observed[0]['state'], 'closed')
    self.assertTrue(observed[0]['active_restore'])
    self.assertGreater(observed[0]['snapshot_bytes'], 0)
    self.assertEqual(client.stats()['snapshot_bytes'], 0)
    self.assertEqual(client.stats()['restores'], 0)

  def test_throwing_give_up_callback_does_not_rearm(self):
    client, server, _ = self.make(reconnect_limits=ReconnectLimits(max_attempts=1))
    self.frame(client, server)
    calls = []
    def callback():
      calls.append(1)
      raise ValueError('callback failed')
    client.set_on_give_up(callback)
    server.stop()
    until(lambda: client.stats()['state'] == 'gave_up')
    with self.assertRaisesRegex(ValueError, 'callback failed'):
      client.tick()
    for _ in range(100):
      client.tick()
    self.assertEqual(calls, [1])

  def test_logic_failure_cannot_trigger_a_successful_resume_loop(self):
    client, server, _ = self.make()
    self.frame(client, server)
    def invalid_input():
      raise ValueError('input failed')
    client.logic._controlled_slots_callback = invalid_input
    # 2026-09-10: remove an unused expression from test construction.
    # self.frame(client, server) if False else None
    # Advance the already sampled waiting frame, then the next sample must fail.
    server.run_one_frame(timeout_ms=500)
    until(lambda: client.client.has_authoritative_frame())
    with self.assertRaisesRegex(ValueError, 'input failed'):
      client.run_one_tick()
    until(lambda: client.stats()['state'] == 'gave_up')
    self.assertEqual(client.failure_reason, 'logic_error')
    self.assertEqual(client.stats()['total_attempts'], 0)

  def test_close_refunds_prediction_without_another_manual_tick(self):
    client, _, _ = self.make()
    client.logic.limits = LogicLimits(prediction_frames=3)
    client.run_one_tick()
    self.assertGreater(client.logic.stats()['history_bytes'], 0)
    client.close()
    self.assertEqual(client.logic.stats()['history_bytes'], 0)
    self.assertEqual(client.logic.stats()['sampled_input_frames'], 0)

  def test_legacy_connect_uses_actual_host_token_and_same_snapshot_contract(self):
    client, server, _ = self.make(handshake='native')
    self.assertIsNone(client.client.session_token)
    client.set_session_token(server.get_session_tokens()[0])
    self.frame(client, server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    with self.assertRaises(RuntimeError):
      client.set_session_token(1)
    client.tick()
    until(lambda: client.client.resume_handback_complete)
    client.tick()
    self.frame(client, server)
    self.assertEqual(client.stats()['restores'], 1)

  def test_expired_pending_restore_does_not_mutate_engine(self):
    client, server, replica = self.make()
    self.frame(client, server)
    client.client.close()
    until(lambda: client.stats()['state'] == 'restoring')
    before = replica.get_state()
    # Serialize with the real attempt owner to test the UI/worker boundary.
    with client._condition:
      client._recovery_deadline = time.monotonic() - 1
      with self.assertRaisesRegex(ClientFailure, 'recovery_timeout'):
        client.tick()
    self.assertEqual(replica.get_state(), before)
    self.assertEqual(replica.restored, [])
    self.assertEqual(client.stats()['snapshot_bytes'], 0)


if __name__ == '__main__':
  unittest.main()
