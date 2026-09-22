# Copyright 2026 Google LLC
"""Actual GameEnv over Python cookie/epoch UDP. Explicit selection; no fallback or skip.
Not a native C++ UDP server interoperability test."""
import unittest

from gfootball.frame_sync.client_udp import ReconnectingFrameSyncUDPClient, ReconnectLimits
from gfootball.frame_sync.client_logic import LogicLimits
from gfootball.frame_sync.protocol import SlotInput
from gfootball.frame_sync.server_udp import FrameSyncUDPServer
from gfootball.frame_sync.server_runtime import ServerSettings, native_engine
from gfootball.frame_sync.test_tcp_client_budget import until


class UDPResumeNativeTest(unittest.TestCase):
  def test_gameenv_automatic_token_snapshot_handback_and_thirteen_frames(self):
    server = FrameSyncUDPServer('127.0.0.1', 0, left_agents=1, right_agents=0,
                              state_hash_interval=1, game_engine_random_seed=42)
    client = replica = None
    try:
      server.start()
      client = ReconnectingFrameSyncUDPClient('127.0.0.1', server.listen_port,
                  lambda: [(0, SlotInput(.5, -.25, 4))],
                  reconnect_limits=ReconnectLimits(base_seconds=.05, max_seconds=.1))
      self.assertEqual(client.connect(), ((42, 1, 0), [0]))
      replica = native_engine(ServerSettings(left_agents=1, right_agents=0, game_engine_random_seed=42))
      client.attach_logic(replica, limits=LogicLimits(prediction_frames=0))
      until(server.all_clients_ready)

      def check_frame():
        client.run_one_tick()
        frame, _ = server.run_one_frame(timeout_ms=1000)
        until(lambda: client.client.has_authoritative_frame())
        client.run_one_tick()
        self.assertEqual(client.logic.get_last_confirmed_frame_id(), frame)
        # 2026-09-10: inspect the actual authority on its engine owner thread.
        # self.assertEqual(replica.get_state_digest(), server.get_env().get_state_digest())
        self.assertEqual(replica.get_state_digest(),
                         server._call(lambda: server._runtime.env.get_state_digest()))

      for _ in range(5):
        check_frame()
      client.client.close()
      until(lambda: client.stats()['state'] == 'restoring', timeout=10)
      self.assertFalse(server.all_clients_ready())
      for _ in range(3):
        server.run_one_frame(timeout_ms=0)
      client.tick()
      self.assertEqual(client.logic.get_current_frame_id(), 5)
      until(lambda: client.client.resume_handback_complete)
      client.tick()
      until(lambda: client.client.stats()['authority_frames'] == 3)
      client.run_one_tick()
      self.assertEqual(client.logic.get_last_confirmed_frame_id(), 7)
      # 2026-09-10: inspect the actual authority on its engine owner thread.
      # self.assertEqual(replica.get_state_digest(), server.get_env().get_state_digest())
      self.assertEqual(replica.get_state_digest(),
                       server._call(lambda: server._runtime.env.get_state_digest()))
      for _ in range(5):
        check_frame()
      self.assertEqual(server.get_frame_id(), 13)
      self.assertEqual(client.logic.stats()['verified_hashes'], 8)
      self.assertEqual(client.stats()['restores'], 1)
    finally:
      if client is not None:
        client.close()
      if replica is not None:
        replica.close()
      server.stop()


if __name__ == '__main__':
  unittest.main()
