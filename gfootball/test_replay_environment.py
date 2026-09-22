# 2026-09-09: actual environment/native action bindings; never native substitutes.
# Run with python_replay_probe.py --environment; --native also executes GameEnv.
import copy
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest import mock
import zlib

import numpy as np

from gfootball.env import config, football_action_set, football_env, football_env_core, replay_support, script_helpers
from gfootball.env.players import replay
from gfootball.replay_io import ReplayExhausted, ReplayFormatError


class ReplayEnvironmentTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-replay-env-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.path = self.directory / 'input,with=delimiters.dump'
    self.values = dict(level='tests.corner_test', action_set='full',
                       players=['agent:left_players=2', 'lazy:right_players=2'],
                       replay_path=str(self.path), physics_steps_per_frame=10,
                       tracesdir=str(self.directory), display_game_stats=False,
                       render_resolution_x=64, render_resolution_y=48)
    self.actions = [football_action_set.action_left, football_action_set.action_right,
                    football_action_set.action_top, football_action_set.action_bottom]
    with self.path.open('wb') as stream:
      for frame in range(2):
        debug = dict(frame_cnt=frame, action=self.actions if frame == 0 else list(reversed(self.actions)))
        if frame == 0:
          debug['config'] = self.values
        pickle.dump(dict(observation={'ball': np.zeros(3), 'score': [0, 0]}, debug=debug), stream, protocol=4)

  def player(self, pool, *, left=0, right=0, left_offset=0, right_offset=0):
    value = replay.Player(dict(index=0, left_players=left, right_players=right,
                                _left_action_offset=left_offset, _right_action_offset=right_offset,
                                _replay_sources=pool), config.Config(self.values))
    self.addCleanup(value.close)
    return value

  def names(self, actions):
    self.assertTrue(all(type(value) is football_action_set.CoreAction for value in actions))
    return [value._name for value in actions]

  def test_right_before_left_and_multi_controller_offsets_use_actual_core_actions(self):
    pool = replay_support.make_pool(config.Config(self.values))
    self.addCleanup(pool.close)
    right = self.player(pool, right=2)
    left = self.player(pool, left=2)
    for expected in (self.actions, list(reversed(self.actions))):
      self.assertEqual(self.names(right.take_action([])), self.names(expected[2:]))
      self.assertEqual(self.names(left.take_action([])), self.names(expected[:2]))
    self.assertEqual(pool.stats()['sources'], 1)
    with self.assertRaises(ReplayExhausted):
      left.take_action([])
    right.reset()
    left.reset()
    self.assertEqual(self.names(right.take_action([])), self.names(self.actions[2:]))
    self.assertEqual(self.names(left.take_action([])), self.names(self.actions[:2]))
    right.close()
    left.close()
    self.assertEqual(pool.stats()['sources'], 0)
    self.path.rename(self.directory / 'released.dump')

  def test_standalone_player_preserves_absolute_index_and_owns_reader_cleanup(self):
    player = replay.Player(dict(index=2, left_players=0, right_players=2, path=str(self.path)),
                            config.Config(self.values))
    self.addCleanup(player.close)
    self.assertEqual(self.names(player.take_action([])), self.names(self.actions[2:]))
    player.reset()
    self.assertEqual(self.names(player.take_action([])), self.names(self.actions[2:]))
    player.close()
    self.assertTrue(player._pool.stats()['closed'])

  def test_layout_rejects_negative_huge_and_excessive_total_player_counts(self):
    for key in ('replay_limits', 'observation_limits', 'directory_limits'):
      with self.assertRaises(ValueError):
        script_helpers.ScriptHelpers(**{key: False})
    for spec in (['agent:left_players=-1'], ['agent:left_players=1000000000'],
                 ['lazy:left_players=6', 'lazy:left_players=6'], ['lazy'] * 23):
      with self.assertRaises(ValueError):
        replay_support.recorded_layout({'players': spec})
    self.assertEqual(replay_support.recorded_layout({'players': []}), (0, 0))

  def test_helper_legacy_load_is_mutable_and_text_export_preserves_native_actions(self):
    helper = script_helpers.ScriptHelpers()
    values = helper.load_dump(self.path)
    self.assertEqual(self.names(values[0]['debug']['action']), self.names(self.actions))
    values[0]['observation']['ball'][0] = 99
    values[0]['debug']['action'][0]._name = 'changed'
    again = helper.load_dump(self.path)
    self.assertEqual(again[0]['observation']['ball'][0], 0)
    self.assertEqual(again[0]['debug']['action'][0]._name, self.actions[0]._name)
    report = self.directory / 'out.txt'
    helper.dump_to_txt(self.path, report, False)
    self.assertNotIn("'debug'", report.read_text(encoding='utf-8'))

  def test_helper_copies_overrides_and_cleans_converted_file_if_factory_fails(self):
    helper = script_helpers.ScriptHelpers()
    updates = dict(players=['lazy:left_players=2', 'lazy:right_players=2'],
                   recording_limits={'trace_steps': 20})
    unchanged = copy.deepcopy(updates)
    captured = []
    original = OSError('native construction failure')

    def failing_factory(cfg):
      captured.append(cfg)
      self.assertTrue(Path(cfg['replay_path']).is_file())
      self.assertEqual(cfg['players'], unchanged['players'])
      self.assertEqual(cfg['physics_steps_per_frame'], 5)
      self.assertEqual(len(helper.load_dump(cfg['replay_path'])), 14)
      raise original

    with mock.patch.object(script_helpers.football_env, 'FootballEnv', failing_factory):
      with self.assertRaises(OSError) as caught:
        helper.replay(self.path, fps=20, config_update=updates, render=False)
    self.assertIs(caught.exception, original)
    self.assertEqual(updates, unchanged)
    self.assertFalse(Path(captured[0]['replay_path']).parent.exists())

  def test_actual_environment_closes_constructed_players_if_core_factory_fails(self):
    values = dict(self.values, players=['replay:right_players=2', 'replay:left_players=2'])
    captured = []
    original = OSError('core construction failure')
    actual_make_pool = replay_support.make_pool

    def observed_pool(cfg):
      pool = actual_make_pool(cfg)
      captured.append(pool)
      return pool

    with mock.patch.object(replay_support, 'make_pool', observed_pool):
      with mock.patch.object(football_env_core, 'FootballEnvCore', side_effect=original):
        with self.assertRaises(OSError) as caught:
          football_env.FootballEnv(config.Config(values))
    self.assertIs(caught.exception, original)
    self.assertEqual(len(captured), 1)
    self.assertTrue(captured[0].stats()['closed'])
    self.assertEqual(captured[0].stats()['sources'], 0)
    self.path.rename(self.directory / 'closed.dump')


class ReplayGameEnvTest(unittest.TestCase):
  """Runs actual GameEnv; synthetic source/driver tests cannot replace this."""
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-replay-native-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)

  def test_real_corner_record_replay_matches_all_observations_and_rewards(self):
    values = dict(level='tests.corner_test', action_set='full', dump_full_episodes=True,
                   players=['agent:left_players=2', 'bot:right_players=1', 'lazy:right_players=1'],
                   tracesdir=str(self.directory), render_resolution_x=64, render_resolution_y=48,
                   write_video=False, display_game_stats=False)
    cfg = config.Config(values)
    env = football_env.FootballEnv(cfg)
    self.addCleanup(env.close, finalize=False)
    success = False
    try:
      env.reset()
      for step in range(1, 1001):
        _, _, done, _ = env.step([(step + player) % len(football_action_set.get_action_set(cfg)) for player in range(2)])
        if done:
          success = True
          break
      self.assertTrue(success, 'Corner scenario exceeded 1000 environment steps')
    finally:
      env.close(finalize=success)
    originals = set(self.directory.glob('episode_done*.dump'))
    self.assertEqual(len(originals), 1)
    helper = script_helpers.ScriptHelpers()
    updates = dict(dump_full_episodes=True, display_game_stats=False)
    expected_updates = copy.deepcopy(updates)
    result = helper.replay(next(iter(originals)), directory=str(self.directory),
                            config_update=updates, render=False)
    self.assertTrue(result['episode_done'])
    self.assertEqual(updates, expected_updates)
    produced = set(self.directory.glob('episode_done*.dump')) - originals
    self.assertEqual(len(produced), 1)
    before = helper.load_dump(next(iter(originals)))
    after = helper.load_dump(next(iter(produced)))
    self.assertEqual(len(before), len(after))
    self.assertEqual([row['debug']['frame_cnt'] for row in before], list(range(len(before))))
    # Preserve the legacy script test's Adler32 comparison and compare each row.
    hashes = []
    for records in (before, after):
      digest = 0
      for row in records:
        del row['debug']
        digest = zlib.adler32(str(tuple(sorted(row.items()))).encode(), digest)
      hashes.append(digest)
    self.assertEqual(hashes[0], hashes[1])
    for frame, (expected, actual) in enumerate(zip(before, after)):
      self.assertEqual(set(expected), set(actual))
      self.assertEqual(set(expected['observation']), set(actual['observation']))
      for name in expected['observation']:
        np.testing.assert_equal(actual['observation'][name], expected['observation'][name], err_msg='%d:%s' % (frame, name))
      for name in set(expected) - {'observation'}:
        self.assertEqual(actual[name], expected[name])

  # 2026-09-09: this case proves engine cadence, player rewind is covered above.
  # def test_reused_engine_adopts_changed_physics_cadence_and_reset_rewinds_players(self):
  def test_reused_engine_adopts_changed_physics_cadence_across_reset(self):
    values = dict(level='tests.corner_test', players=['lazy'], physics_steps_per_frame=10,
                   render_resolution_x=64, render_resolution_y=48, tracesdir=str(self.directory),
                   write_video=False, dump_full_episodes=False)
    first = football_env.FootballEnv(config.Config(values))
    first_core = first._env._env
    first.close()
    second = football_env.FootballEnv(config.Config(dict(values, physics_steps_per_frame=5)))
    self.addCleanup(second.close, finalize=False)
    self.assertIs(second._env._env, first_core)
    self.assertEqual(second._env._env.game_config.physics_steps_per_frame, 5)
    second.reset()
    self.assertEqual(second._env._env.game_config.physics_steps_per_frame, 5)
    second.step([])
    second.close()


if __name__ == '__main__':
  unittest.main()
