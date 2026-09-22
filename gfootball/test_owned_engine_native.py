"""Required real Core/GameEnv admission checks; no fallback or skipped imports."""
import tempfile
import unittest
from unittest import mock

from gfootball import owned_engine
from gfootball.engine_pool import EnginePool, EngineCapacityError
from gfootball.env import config, football_env_core
from gfootball.frame_sync import match_identity, server, server_runtime


class OwnedEngineNativeTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.pool = EnginePool(max_live=2, idle_headless=1, idle_rendering=0)
    self.addCleanup(self.pool.close)
    for module in (football_env_core, owned_engine):
      patch = mock.patch.object(module, 'ENGINE_POOL', self.pool)
      patch.start()
      self.addCleanup(patch.stop)
    self.values = dict(level='tests.corner_test', players=[], physics_steps_per_frame=10,
        render_resolution_x=1280, render_resolution_y=720, tracesdir=directory.name,
        display_game_stats=False, write_video=False, dump_full_episodes=False)

  def core(self):
    core = football_env_core.FootballEnvCore(config.Config(self.values))
    self.addCleanup(core.close, finalize=False)
    return core

  def test_actual_core_and_direct_match_share_capacity_before_identity_io(self):
    core = self.core()
    env = server_runtime.native_engine(server_runtime.ServerSettings())
    try:
      self.assertEqual(self.pool.stats()['live'], 2)
      expected = core._env.get_state_digest()
      with mock.patch.object(match_identity, 'fingerprint', side_effect=AssertionError('Saturation reached file hashing')):
        with self.assertRaises(EngineCapacityError):
          match_identity.native_match_engine(server_runtime.ServerSettings())
      self.assertEqual(core._env.get_state_digest(), expected)
      method = env.get_info
      raw = env._lease.resource
      env.close()
      with self.assertRaisesRegex(RuntimeError, 'closed'):
        method()
      with self.assertRaises(RuntimeError):
        raw.get_info()
      core.step([])
      self.assertEqual(self.pool.stats()['live'], 1)
    finally:
      env.close()

  def test_direct_match_retires_matching_cached_actual_core(self):
    core = self.core()
    raw = core._env
    core.close()
    self.assertEqual(self.pool.stats()['idle_headless'], 1)
    with server_runtime.native_engine(server_runtime.ServerSettings()) as env:
      self.assertEqual(self.pool.stats()['live'], 1)
      self.assertEqual(self.pool.stats()['idle_headless'], 0)
      with self.assertRaises(RuntimeError):
        raw.get_info()
      self.assertEqual(env.game_config.physics_steps_per_frame, 10)
      self.assertIsNotNone(env.get_info())
    self.assertEqual(self.pool.stats()['live'], 0)

  def test_native_reset_failure_refunds_reservation_and_allows_new_match(self):
    original = server.get_scenario_config
    def invalid(*args):
      scenario = original(*args)
      scenario.left_agents = 12
      return scenario
    # The actual binding starts its default context, then rejects this invalid
    # scenario in reset. The real factory must close that context on failure.
    with mock.patch.object(server, 'get_scenario_config', invalid):
      with self.assertRaises((ValueError, RuntimeError)):
        server_runtime.native_engine(server_runtime.ServerSettings())
    self.assertEqual(self.pool.stats()['live'], 0)
    with server_runtime.native_engine(server_runtime.ServerSettings()) as env:
      self.assertIsNotNone(env.get_info())
      self.assertEqual(self.pool.stats()['live'], 1)
    self.assertEqual(self.pool.stats()['live'], 0)
