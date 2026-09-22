"""Real GameEnv v4 multiplayer/record/end integration; no fallback or skip."""
from pathlib import Path
import tempfile
import time
import unittest

from gfootball.frame_sync.match_archive import engine_digest, playback
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.protocol import SlotInput


class NativeMultiplayerTest(unittest.TestCase):
  transport = 'tcp'

  def test_gameenv_host_join_authority_end_and_native_recording(self):
    with tempfile.TemporaryDirectory() as directory:
      record = str(Path(directory) / 'native-match.replay')
      # 2026-09-10: the same real-engine acceptance is required for each transport.
      # host = HostedMatch(scenario='11_vs_11_stochastic', port=0, record_path=record,
      host = HostedMatch(scenario='11_vs_11_stochastic', port=0, record_path=record, transport=self.transport,
                         input_provider=lambda frame: SlotInput(.5, 0, 0))
      player = None
      try:
        host.start()
        # 2026-09-10: use the selected real transport on both endpoints.
        # player = NetworkPlayer('127.0.0.1', host.port, input_provider=lambda frame: SlotInput(-.5, .25, 0))
        player = NetworkPlayer('127.0.0.1', host.port, transport=self.transport, input_provider=lambda frame: SlotInput(-.5, .25, 0))
        player.start()
        deadline = time.monotonic() + 10
        while host.frame < 5:
          player.tick()
          host.advance()
          self.assertLess(time.monotonic(), deadline)
          time.sleep(.001)
        host.server.finish_match()
        while not player.stats()['ended']:
          player.tick()
          host.player.tick()
          self.assertLess(time.monotonic(), deadline)
          time.sleep(.001)
        player.flush_end_ack()
        self.assertTrue(host.finish())
        self.assertEqual(player.client.logic.stats()['history_bytes'], 0)
        expected = engine_digest(player.env)
        self.assertEqual(expected, host.server._call(lambda: engine_digest(host.server._runtime.env)))
        host.close()
      finally:
        if player is not None:
          player.close()
        host.close(finalize=False)
      self.assertEqual(playback(record)['digest'], expected)


if __name__ == '__main__':
  unittest.main()
