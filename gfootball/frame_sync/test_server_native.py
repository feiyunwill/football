# 2026-09-10: actual native GameEnv server/client identity, never an engine substitute.
# Requires the installed native engine and environment dependencies in Linux.
import socket
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client import FrameSyncClient
from gfootball.frame_sync.server import FrameSyncServer
from gfootball.frame_sync.server_runtime import native_engine
from gfootball.frame_sync.test_server_budget import until, packet, next_kind


class ServerNativeTest(unittest.TestCase):
  def server(self, **options):
    values = dict(listen_host='127.0.0.1', listen_port=0,
                   scenario_name='tests.11_vs_11_deterministic', state_hash_interval=1)
    values.update(options)
    result = FrameSyncServer(**values)
    self.addCleanup(result.stop)
    result.start()
    return result

  def replica(self, server):
    env = native_engine(server._runtime.settings)
    self.addCleanup(env.close)
    return env

  def test_real_engine_authority_and_canonical_hash_match_independent_replica(self):
    server = self.server(right_agents=1)
    replica = self.replica(server)
    clients = [FrameSyncClient('127.0.0.1', server.listen_port) for _ in range(2)]
    for slot, client in enumerate(clients):
      self.addCleanup(client.close)
      self.assertEqual(client.connect(), ((42, 1, 1), [slot]))
      client.send_ready()
    until(server.all_clients_ready)
    for frame in range(25):
      expected = [wire.SlotInput(.5, 0, 0), wire.SlotInput(-.5, 0, 0)]
      for slot, client in enumerate(clients):
        client.send_frame_entries(frame, [(slot, expected[slot])])
      _, actual = server.run_one_frame()
      self.assertEqual(actual, expected)
      replica.step_with_input(b''.join(wire.pack_slot_input(value) for value in actual))
      digest = replica.get_state_digest()
      for client in clients:
        until(client.has_authoritative_frame)
        self.assertEqual(client.pop_authoritative_frame(), (frame, actual))
        until(lambda: frame in client._buffers.hashes)
        self.assertTrue(client.check_state_hash(frame, digest))

  def test_real_resume_snapshot_restores_replica_before_handback_and_hash_checks(self):
    server = self.server()
    original = FrameSyncClient('127.0.0.1', server.listen_port)
    self.addCleanup(original.close)
    original.connect()
    original.send_ready()
    until(server.all_clients_ready)
    token = server.get_session_tokens()[0]
    for frame in range(3):
      original.send_frame_entries(frame, [(0, wire.SlotInput(.5, 0, 0))])
      server.run_one_frame()
      until(original.has_authoritative_frame)
      original.pop_authoritative_frame()
    original.close()
    until(lambda: server.stats()['bots'] == (0,))
    for _ in range(3):
      server.run_one_frame(timeout_ms=0)
    peer = socket.create_connection(('127.0.0.1', server.listen_port), timeout=3)
    self.addCleanup(peer.close)
    peer.sendall(wire.pack_reconnect_request(token))
    self.assertEqual(packet(peer)[0], wire.MessageType.SessionStart)
    self.assertEqual(packet(peer)[0], wire.MessageType.SlotAssignment)
    frame, state = wire.unpack_state_snapshot(packet(peer))
    self.assertEqual(frame, 6)
    replica = self.replica(server)
    replica.set_state(state)
    peer.sendall(wire.pack_ready())
    self.assertEqual(next_kind(peer, wire.MessageType.HandbackNotify)[0], wire.MessageType.HandbackNotify)
    for expected_frame in range(frame, frame + 10):
      peer.sendall(wire.pack_client_frame_input(expected_frame, [(0, wire.SlotInput(-.5, 0, 0))]))
      server.run_one_frame()
      actual_frame, inputs = wire.unpack_authoritative_frame(next_kind(peer, wire.MessageType.AuthoritativeFrame))
      self.assertEqual(actual_frame, expected_frame)
      replica.step_with_input(b''.join(wire.pack_slot_input(value) for value in inputs))
      frame_hash = wire.unpack_state_hash(next_kind(peer, wire.MessageType.StateHash))
      self.assertEqual(frame_hash, (expected_frame, wire.compute_state_hash(replica.get_state_digest())))


if __name__ == '__main__':
  unittest.main()
