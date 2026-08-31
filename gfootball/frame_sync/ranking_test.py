"""
Tests for the ranking and season systems.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from ranking import RankingManager, LeaderboardType, RankTier
from season import SeasonManager, SeasonStatus, LeagueTier


class TestRankingManager(unittest.TestCase):
    """Test RankingManager class."""

    def setUp(self):
        self.manager = RankingManager()
        self.manager.create_board("global", LeaderboardType.GLOBAL)

    def test_create_board(self):
        board = self.manager.create_board("test", LeaderboardType.GLOBAL)
        self.assertIsNotNone(board)
        self.assertEqual(board.board_id, "test")

    def test_update_rating(self):
        result = self.manager.update_player_rating(
            "global", "p1", "Alice", 1200, 10, 0.7
        )
        self.assertTrue(result)

    def test_get_rank(self):
        self.manager.update_player_rating("global", "p1", "Alice", 1200)
        self.manager.update_player_rating("global", "p2", "Bob", 1000)
        rank = self.manager.get_player_rank("global", "p1")
        self.assertEqual(rank, 1)

    def test_global_top(self):
        self.manager.update_player_rating("global", "p1", "Alice", 1200)
        self.manager.update_player_rating("global", "p2", "Bob", 1000)
        self.manager.update_player_rating("global", "p3", "Charlie", 1400)
        top = self.manager.get_global_top(2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0].player_name, "Charlie")

    def test_rank_tier(self):
        from ranking import RankingEntry
        entry = RankingEntry("p1", "Alice", 1500)
        self.assertEqual(entry.tier, RankTier.DIAMOND)


class TestSeasonManager(unittest.TestCase):
    """Test SeasonManager class."""

    def setUp(self):
        self.manager = SeasonManager()

    def test_create_season(self):
        season = self.manager.create_season("s1", "Season 1")
        self.assertEqual(season.season_id, "s1")
        self.assertEqual(season.status, SeasonStatus.UPCOMING)

    def test_start_season(self):
        self.manager.create_season("s1", "Season 1")
        result = self.manager.start_season("s1")
        self.assertTrue(result)
        season = self.manager.get_current_season()
        self.assertIsNotNone(season)
        self.assertEqual(season.status, SeasonStatus.ACTIVE)

    def test_record_match(self):
        self.manager.create_season("s1", "Season 1")
        self.manager.start_season("s1")
        result = self.manager.record_match("p1", "p2", 3, 1)
        self.assertTrue(result)
        season = self.manager.get_current_season()
        stats = season.player_stats["p1"]
        self.assertEqual(stats.games_won, 1)
        self.assertEqual(stats.points, 3)

    def test_finish_season(self):
        self.manager.create_season("s1", "Season 1")
        self.manager.start_season("s1")
        self.manager.finish_season("s1")
        self.assertIsNone(self.manager.get_current_season())

    def test_leaderboard(self):
        self.manager.create_season("s1", "Season 1")
        self.manager.start_season("s1")
        self.manager.record_match("p1", "p2", 3, 1)
        self.manager.record_match("p1", "p3", 2, 0)
        season = self.manager.get_current_season()
        board = season.get_leaderboard()
        self.assertEqual(len(board), 3)  # p1, p2, p3 all have stats
        self.assertEqual(board[0].player_id, "p1")  # p1 has most points


if __name__ == "__main__":
    unittest.main()
