"""Required actual GameEnv completion checks; no fake modules or skipped tests."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from gfootball.frame_sync import server
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import engine_digest, playback, read_checkpoint
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.protocol import default_slot_input


class MatchCompletionNativeTest(unittest.TestCase):
  def setUp(self):
    original = server.get_scenario_config
    def short_scenario(*args):
      scenario = original(*args)  # The real native ScenarioConfig and builder.
      scenario.game_duration = 3
      scenario.end_episode_on_score = False
      scenario.end_episode_on_out_of_play = False
      scenario.end_episode_on_possession_change = False
      return scenario
    patch = mock.patch.object(server, 'get_scenario_config', short_scenario)
    patch.start()
    self.addCleanup(patch.stop)

  def test_real_gameenv_completed_checkpoint_and_replay(self):
    from gfootball_engine import GameState
    with tempfile.TemporaryDirectory() as directory:
      save, record = str(Path(directory) / 'end.save'), str(Path(directory) / 'end.replay')
      with LocalPlayer(save_path=save, record_path=record) as player:
        self.assertEqual(player.replica.get_info().step, -1)
        # 2026-09-13: same ten simulated second bound at 50 Hz, including kickoff.
        # result = player.run(100, realtime=False)
        result = player.run(500, realtime=False)
      self.assertTrue(result['ended'])
      # 2026-09-13: same ten simulated seconds; terminal duration must still be reached.
      # self.assertLess(result['frames'], 100)
      self.assertLess(result['frames'], 500)
      expected = read_checkpoint(save)['digest']
      self.assertEqual(playback(record)['digest'], expected)
      with LocalPlayer(resume_path=save) as resumed:
        self.assertEqual(resumed.replica.state, GameState.game_done)
        self.assertEqual(resumed.replica.get_match_end_reason(), 'duration')
        self.assertEqual(resumed.run(10, realtime=False)['frames'], 0)

  def multiplayer(self, transport):
    with tempfile.TemporaryDirectory() as directory:
      record = str(Path(directory) / 'natural.replay')
      with HostedMatch(transport=transport, record_path=record,
                       input_provider=lambda _: default_slot_input()) as host:
        with NetworkPlayer('127.0.0.1', host.port, transport=transport,
                           input_provider=lambda _: default_slot_input()) as player:
          deadline = time.monotonic() + 15
          while not host.server.stats()['finished']:
            player.tick()
            host.advance()
            self.assertLess(time.monotonic(), deadline)
            # 2026-09-13: same ten simulated seconds at the new product cadence.
            # self.assertLess(host.frame, 100)
            self.assertLess(host.frame, 500)
            time.sleep(.001)
          while not player.stats()['ended'] or not host.player.stats()['ended']:
            player.tick()
            host.player.tick()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.001)
          player.flush_end_ack()
          self.assertTrue(host.finish())
          self.assertEqual(player.env.get_match_end_reason(), 'duration')
          expected = engine_digest(player.env)
          self.assertEqual(expected, host.server._call(lambda: engine_digest(host.server._runtime.env)))
      self.assertEqual(playback(record)['digest'], expected)

  def test_real_gameenv_tcp_natural_end_and_ack(self):
    self.multiplayer('tcp')

  def test_real_gameenv_udp_natural_end_and_ack(self):
    self.multiplayer('udp')
