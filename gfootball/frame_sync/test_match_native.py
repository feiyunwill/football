"""Actual GameEnv local play, persistent continuation and replay. Never skipped."""
from pathlib import Path
import tempfile
import unittest

from gfootball.frame_sync.local_play import LocalPlayer
from gfootball.frame_sync.match_archive import playback
from gfootball.frame_sync.protocol import SlotInput


class MatchNativeTest(unittest.TestCase):
  def test_scenario_builder_mutates_native_teams_and_preserves_sequence_assignment(self):
    import gc
    import gfootball_engine as game
    from gfootball.frame_sync.server import get_scenario_config
    scenario = get_scenario_config('11_vs_11_stochastic', 1, 0, 42)
    self.assertEqual((len(scenario.left_team), len(scenario.right_team)), (11, 11))
    self.assertIsInstance(scenario.left_team, game.FormationEntryVec)
    self.assertEqual(scenario.left_team[0].role, game.e_PlayerRole_GK)
    team = scenario.left_team
    team[1].controllable = False
    self.assertFalse(scenario.left_team[1].controllable)
    entry = game.FormationEntry(-.5, .2, game.e_PlayerRole_CF, False, True)
    team.append(entry)
    self.assertEqual(len(scenario.left_team), 12)
    team.pop()
    self.assertEqual(len(scenario.left_team), 11)
    scenario.right_team = [entry]
    self.assertEqual(len(scenario.right_team), 1)
    self.assertEqual(scenario.right_team[0].role, game.e_PlayerRole_CF)
    with self.assertRaises((TypeError, RuntimeError)):
      scenario.right_team = [entry, object()]
    self.assertEqual(len(scenario.right_team), 1)
    del scenario
    gc.collect()
    self.assertEqual(len(team), 11)
    self.assertEqual(team[0].role, game.e_PlayerRole_GK)

  def test_actual_native_identity_includes_loaded_core_and_configuration(self):
    import sys
    from gfootball.frame_sync.match_identity import loaded_native_files, native_match_engine
    from gfootball.frame_sync.server_runtime import ServerSettings
    from gfootball.frame_sync.save_data import SaveFormatError
    env = native_match_engine(ServerSettings())
    try:
      value = env.get_snapshot_identity()
      # 2026-09-10: application snapshots now contain rollbackable terminal policy.
      # self.assertEqual(value['backend'], 'gfootball.GameEnv.FSTA2.headless10')
      # 2026-09-10: identified physics is shared by logic and render copies.
      # self.assertEqual(value['backend'], 'gfootball.GameEnv.FSTA2.match1.headless10')
      # 2026-09-13: actual binding identity names v7 physical frame duration.
      # self.assertEqual(value['backend'], 'gfootball.GameEnv.FSTA2.match1.physics10')
      self.assertEqual(value['backend'], 'gfootball.GameEnv.FSTA2.match1.physics2.cadence50')
      files = loaded_native_files(sys.modules['_gameplayfootball'].__file__)
      self.assertTrue(any(name.startswith('binary/libfootball_engine.so') for name, _ in files))
      self.assertTrue(any(name.startswith('binary/_gameplayfootball.') for name, _ in files))
      env.game_config.physics_steps_per_frame = 11
      with self.assertRaisesRegex(SaveFormatError, 'configuration changed'):
        env.get_snapshot_identity()
      # 2026-09-10: changing cadence after handshake cannot advance native physics.
      before = env.get_state_digest()
      with self.assertRaisesRegex(SaveFormatError, 'configuration changed'):
        env.step_with_input(bytes(10))
      self.assertEqual(env.get_state_digest(), before)
    finally:
      env.close()

  def test_gameenv_local_save_continue_and_two_native_replays(self):
    with tempfile.TemporaryDirectory() as directory:
      save = str(Path(directory) / 'match.save')
      original = str(Path(directory) / 'original.jsonl')
      resumed = str(Path(directory) / 'resumed.jsonl')
      def controls(frame):
        return SlotInput(.5 if frame % 2 else -.25, .125, 4 if frame % 3 == 0 else 8)
      first = LocalPlayer(record_path=original, save_path=save)
      try:
        first.start()
        for frame in range(5):
          first.step(controls(frame))
        first.save()
        for frame in range(5, 13):
          first.step(controls(frame))
        expected = first.stats()['last']['digest']
        first.stop()
      finally:
        first.stop(finalize=False)
      self.assertEqual(playback(original)['digest'], expected)
      second = LocalPlayer(resume_path=save, record_path=resumed,
                           input_provider=lambda frame: controls(frame + 5))
      try:
        second.start()
        second.run(8, realtime=False)
        self.assertEqual(second.stats()['last']['digest'], expected)
      finally:
        second.stop(finalize=False)
      self.assertEqual(playback(resumed)['digest'], expected)


if __name__ == '__main__':
  unittest.main()
