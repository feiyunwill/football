"""Actual matches and files through shared admission, with explicit oracles."""
from pathlib import Path
import tempfile
import time
import unittest

from gfootball.engine_pool import EnginePool, EngineKey, EngineCapacityError
from gfootball.owned_engine import create_owned_engine
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import engine_digest, playback
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.protocol import SlotInput
from gfootball.frame_sync.test_match_archive import MatchOracle


class OwnedMatchTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.pool = EnginePool(max_live=3, idle_headless=0, idle_rendering=0)
    self.engines = []
    self.key = EngineKey.current(1280, 720)

  def tearDown(self):
    self.pool.close()
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertEqual(self.pool.stats()['leased'], 0)
    self.assertTrue(all(engine.closed == 1 for engine in self.engines), [engine.closed for engine in self.engines])

  def factory(self, settings):
    def initialize():
      env = MatchOracle(settings)
      self.engines.append(env)
      return env
    return create_owned_engine(self.key, initialize, pool=self.pool)

  def wait(self, predicate, pump):
    deadline = time.monotonic() + 4
    while not predicate():
      pump()
      self.assertLess(time.monotonic(), deadline)
      time.sleep(.003)

  def multiplayer(self, transport):
    path = str(self.root / 'match.replay')
    with HostedMatch(transport=transport, engine_factory=self.factory, record_path=path,
                     input_provider=lambda frame: SlotInput(.5, 0, 1)) as host:
      self.assertEqual(self.pool.stats()['live'], 2)
      with NetworkPlayer('127.0.0.1', host.port, transport=transport, engine_factory=self.factory,
                         input_provider=lambda frame: SlotInput(-.5, .25, 4)) as player:
        self.assertEqual(self.pool.stats()['live'], 3)
        with self.assertRaises(EngineCapacityError):
          self.pool.acquire(self.key, lambda: self.fail('Saturation reached another factory'))
        pump = lambda: (host.player.tick(), player.tick())
        self.wait(host.server.participants_ready, pump)
        for _ in range(3):
          pump()
          self.assertTrue(host.advance())
          self.wait(lambda: player.client.logic.get_last_confirmed_frame_id() == host.frame - 1, pump)
        host.server.finish_match()
        self.wait(lambda: player.stats()['ended'] and host.player.stats()['ended'], pump)
        player.flush_end_ack()
        self.assertTrue(host.finish())
        expected = engine_digest(player.env)
        self.assertEqual(expected, host.server._call(lambda: engine_digest(host.server._runtime.env)))
      self.assertEqual(self.pool.stats()['live'], 2)
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertEqual(playback(path, engine_factory=self.factory)['digest'], expected)
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_tcp_host_join_end_and_recording_share_live_engine_budget(self):
    self.multiplayer('tcp')

  def test_udp_host_join_end_and_recording_share_live_engine_budget(self):
    self.multiplayer('udp')

  def test_local_save_continuation_and_playback_refund_every_lease(self):
    save, replay = str(self.root / 'match.save'), str(self.root / 'match.replay')
    with LocalPlayer(engine_factory=self.factory, record_path=replay, save_path=save) as player:
      self.assertEqual(self.pool.stats()['live'], 2)
      for _ in range(3):
        player.step(SlotInput(.5, .25, 4))
      expected = player.save()['digest']
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertEqual(playback(replay, engine_factory=self.factory)['digest'], expected)
    with LocalPlayer(engine_factory=self.factory, resume_path=save) as resumed:
      self.assertEqual(self.pool.stats()['live'], 2)
      resumed.step(SlotInput(0, 0, 0))
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_replica_capacity_failure_closes_authority_without_replacing_record(self):
    self.pool.close()
    self.pool = EnginePool(max_live=1, idle_headless=0, idle_rendering=0)
    path = self.root / 'old.replay'
    path.write_bytes(b'previous complete recording')
    player = LocalPlayer(engine_factory=self.factory, record_path=str(path))
    try:
      with self.assertRaises(EngineCapacityError):
        player.start()
      self.assertTrue(player.stats()['closed'])
      self.assertEqual(len(self.engines), 1)
      self.assertEqual(self.pool.stats()['live'], 0)
      self.assertEqual(path.read_bytes(), b'previous complete recording')
    finally:
      player.stop(finalize=False)

  def test_running_failure_releases_both_leases_and_preserves_old_file(self):
    path = self.root / 'old.replay'
    path.write_bytes(b'previous complete recording')
    failure = ValueError('Actual input callback failure')
    def controls(frame):
      raise failure
    player = LocalPlayer(engine_factory=self.factory, record_path=str(path), input_provider=controls)
    try:
      player.start()
      with self.assertRaises(ValueError) as caught:
        player.run(1, realtime=False)
      self.assertIs(caught.exception, failure)
      self.assertEqual(self.pool.stats()['live'], 0)
      self.assertEqual(path.read_bytes(), b'previous complete recording')
    finally:
      player.stop(finalize=False)


if __name__ == '__main__':
  unittest.main()
