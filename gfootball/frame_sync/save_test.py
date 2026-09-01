"""
Tests for the save and replay systems.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from save_system import SaveManager, SaveType, GameProgress
from replay import ReplayManager, Replay, ReplayEvent, ReplayEventType, ReplayFrame


class TestSaveManager(unittest.TestCase):
    """Test SaveManager class."""

    def setUp(self):
        self.manager = SaveManager()

    def test_create_slot(self):
        slot = self.manager.create_slot("s1", "Save 1", SaveType.PROGRESS)
        self.assertEqual(slot.slot_id, "s1")

    def test_save_and_load(self):
        self.manager.create_slot("s1", "Save 1")
        self.manager.save("s1", {"level": 5, "score": 1000})
        data = self.manager.load("s1")
        self.assertEqual(data["level"], 5)

    def test_delete_slot(self):
        self.manager.create_slot("s1", "Save 1")
        result = self.manager.delete_slot("s1")
        self.assertTrue(result)
        self.assertIsNone(self.manager.get_slot("s1"))

    def test_list_slots(self):
        self.manager.create_slot("s1", "Save 1", SaveType.PROGRESS)
        self.manager.create_slot("s2", "Save 2", SaveType.SETTINGS)
        slots = self.manager.list_slots(SaveType.PROGRESS)
        self.assertEqual(len(slots), 1)

    def test_export_import(self):
        self.manager.create_slot("s1", "Save 1")
        self.manager.save("s1", {"data": "test"})
        exported = self.manager.export_slot("s1")
        self.assertIsNotNone(exported)
        imported = self.manager.import_slot(exported)
        self.assertIsNotNone(imported)

    def test_storage_usage(self):
        self.manager.create_slot("s1", "Save 1")
        self.manager.save("s1", {"key": "value"})
        usage = self.manager.get_storage_usage()
        self.assertEqual(usage["slots_used"], 1)


class TestGameProgress(unittest.TestCase):
    """Test GameProgress class."""

    def setUp(self):
        self.progress = GameProgress()

    def test_get_set(self):
        self.progress.set("career.money", 5000)
        self.assertEqual(self.progress.get("career.money"), 5000)

    def test_update_stats(self):
        self.progress.update_stats(match_played=True, goal_scored=True, won=True)
        self.assertEqual(self.progress.get("stats.total_matches"), 1)
        self.assertEqual(self.progress.get("stats.total_goals"), 1)

    def test_unlock_team(self):
        result = self.progress.unlock_team("bayern")
        self.assertTrue(result)
        self.assertTrue(self.progress.is_team_unlocked("bayern"))

    def test_to_dict(self):
        data = self.progress.to_dict()
        self.assertIn("career", data)


class TestReplayManager(unittest.TestCase):
    """Test ReplayManager class."""

    def setUp(self):
        self.manager = ReplayManager()

    def test_start_stop_recording(self):
        replay = self.manager.start_recording("r1", "m1", "Team A", "Team B")
        self.assertTrue(self.manager.is_recording())
        result = self.manager.stop_recording()
        self.assertFalse(self.manager.is_recording())
        self.assertEqual(result.replay_id, "r1")

    def test_record_frame(self):
        self.manager.start_recording("r1", "m1", "Team A", "Team B")
        frame = ReplayFrame(frame_id=1, ball_pos=(10, 0, 5))
        self.manager.record_frame(frame)
        replay = self.manager.stop_recording()
        self.assertEqual(len(replay.frames), 1)

    def test_record_event(self):
        self.manager.start_recording("r1", "m1", "Team A", "Team B")
        event = ReplayEvent(
            event_type=ReplayEventType.GOAL,
            timestamp_ms=45000,
            frame_id=4500,
            player_id="p1",
        )
        self.manager.record_event(event)
        replay = self.manager.stop_recording()
        self.assertEqual(len(replay.events), 1)

    def test_get_highlights(self):
        replay = Replay("r1", "m1", "A", "B")
        replay.add_event(ReplayEvent(ReplayEventType.GOAL, 1000, 100))
        replay.add_event(ReplayEvent(ReplayEventType.FOUL, 2000, 200))
        highlights = replay.get_highlights()
        self.assertEqual(len(highlights), 1)

    def test_list_replays(self):
        self.manager.start_recording("r1", "m1", "A", "B")
        self.manager.stop_recording()
        self.manager.start_recording("r2", "m2", "C", "D")
        self.manager.stop_recording()
        replays = self.manager.list_replays()
        self.assertEqual(len(replays), 2)


if __name__ == "__main__":
    unittest.main()
