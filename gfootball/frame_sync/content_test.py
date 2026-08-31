"""
Tests for the content management system.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from content_manager import ContentManager, Team, Player, Stadium, League, LeagueType


class TestContentManager(unittest.TestCase):
    """Test ContentManager class."""

    def setUp(self):
        self.manager = ContentManager()

    def test_list_teams(self):
        teams = self.manager.list_teams()
        self.assertGreater(len(teams), 0)

    def test_get_team(self):
        team = self.manager.get_team("real_madrid")
        self.assertIsNotNone(team)
        self.assertEqual(team.name, "Real Madrid")

    def test_filter_teams_by_country(self):
        teams = self.manager.list_teams(country="Spain")
        self.assertGreater(len(teams), 0)
        for team in teams:
            self.assertEqual(team.country, "Spain")

    def test_team_players(self):
        team = self.manager.get_team("real_madrid")
        self.assertGreater(team.squad_size, 0)

    def test_list_stadiums(self):
        stadiums = self.manager.list_stadiums()
        self.assertGreater(len(stadiums), 0)

    def test_get_stadium(self):
        stadium = self.manager.get_stadium("santiago_bernabeu")
        self.assertIsNotNone(stadium)
        self.assertEqual(stadium.capacity, 81044)

    def test_list_leagues(self):
        leagues = self.manager.list_leagues()
        self.assertGreater(len(leagues), 0)

    def test_get_league(self):
        league = self.manager.get_league("la_liga")
        self.assertIsNotNone(league)
        self.assertIn("real_madrid", league.teams)

    def test_content_summary(self):
        summary = self.manager.get_content_summary()
        self.assertGreater(summary["teams"], 0)
        self.assertGreater(summary["stadiums"], 0)


class TestTeam(unittest.TestCase):
    """Test Team class."""

    def test_add_player(self):
        team = Team("t1", "Test Team", "England", "PL")
        player = Player("p1", "Test Player", "ST", "England", 25, 80)
        team.add_player(player)
        self.assertEqual(team.squad_size, 1)

    def test_get_player(self):
        team = Team("t1", "Test Team", "England", "PL")
        player = Player("p1", "Test Player", "ST", "England", 25, 80)
        team.add_player(player)
        found = team.get_player("p1")
        self.assertIsNotNone(found)


if __name__ == "__main__":
    unittest.main()
