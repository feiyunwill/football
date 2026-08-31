"""
Tests for the lobby system.
"""

import sys
import os
import unittest

# Add frame_sync to path for direct imports
sys.path.insert(0, os.path.dirname(__file__))

from lobby import Lobby, PlayerStatus, RoomStatus
from matchmaking import Matchmaker, EloCalculator
from player_profile import ProfileManager, PlayerStats
from chat import ChatManager, MessageType


class TestLobby(unittest.TestCase):
    """Test Lobby class."""

    def setUp(self):
        self.lobby = Lobby()

    def test_register_player(self):
        player = self.lobby.register_player("p1", "Alice", 1200)
        self.assertEqual(player.player_id, "p1")
        self.assertEqual(player.name, "Alice")
        self.assertEqual(player.rating, 1200)

    def test_unregister_player(self):
        self.lobby.register_player("p1", "Alice")
        self.lobby.unregister_player("p1")
        self.assertIsNone(self.lobby.get_player("p1"))

    def test_create_room(self):
        self.lobby.register_player("p1", "Alice")
        room = self.lobby.create_room("p1", "Test Room")
        self.assertIsNotNone(room)
        self.assertEqual(room.host_id, "p1")
        self.assertIn("p1", room.players)

    def test_join_room(self):
        self.lobby.register_player("p1", "Alice")
        self.lobby.register_player("p2", "Bob")
        room = self.lobby.create_room("p1", "Test Room")
        result = self.lobby.join_room("p2", room.room_id)
        self.assertTrue(result)
        self.assertIn("p2", room.players)

    def test_leave_room(self):
        self.lobby.register_player("p1", "Alice")
        self.lobby.register_player("p2", "Bob")
        room = self.lobby.create_room("p1", "Test Room")
        self.lobby.join_room("p2", room.room_id)
        self.lobby.leave_room("p2")
        self.assertNotIn("p2", room.players)

    def test_match_queue(self):
        self.lobby.register_player("p1", "Alice", 1000)
        self.lobby.register_player("p2", "Bob", 1050)
        self.lobby.join_match_queue("p1")
        self.lobby.join_match_queue("p2")
        match = self.lobby.find_match("p1")
        self.assertEqual(match, "p2")


class TestMatchmaking(unittest.TestCase):
    """Test Matchmaking class."""

    def setUp(self):
        self.matchmaker = Matchmaker(max_rating_diff=200)

    def test_enqueue(self):
        result = self.matchmaker.enqueue("p1", 1000)
        self.assertTrue(result)
        self.assertEqual(self.matchmaker.queue_size, 1)

    def test_find_match(self):
        self.matchmaker.enqueue("p1", 1000)
        self.matchmaker.enqueue("p2", 1050)
        match = self.matchmaker.find_match("p1")
        self.assertEqual(match, "p2")

    def test_elo_calculator(self):
        calc = EloCalculator(k_factor=32)
        new_winner, new_loser = calc.calculate_new_ratings(1000, 1000)
        self.assertGreater(new_winner, 1000)
        self.assertLess(new_loser, 1000)


class TestProfileManager(unittest.TestCase):
    """Test ProfileManager class."""

    def setUp(self):
        self.manager = ProfileManager()

    def test_create_profile(self):
        profile = self.manager.create_profile("p1", "Alice")
        self.assertEqual(profile.player_id, "p1")
        self.assertEqual(profile.name, "Alice")

    def test_record_match(self):
        self.manager.create_profile("p1", "Alice")
        self.manager.create_profile("p2", "Bob")
        self.manager.record_match("p1", "p2", 3, 1)
        profile = self.manager.get_profile("p1")
        self.assertEqual(profile.stats.games_played, 1)
        self.assertEqual(profile.stats.goals_scored, 3)

    def test_leaderboard(self):
        self.manager.create_profile("p1", "Alice").rating = 1200
        self.manager.create_profile("p2", "Bob").rating = 1000
        board = self.manager.get_leaderboard(limit=2)
        self.assertEqual(board[0].player_id, "p1")


class TestChatManager(unittest.TestCase):
    """Test ChatManager class."""

    def setUp(self):
        self.chat = ChatManager()

    def test_create_room(self):
        room = self.chat.create_room("room1")
        self.assertIsNotNone(room)
        self.assertEqual(room.room_id, "room1")

    def test_send_message(self):
        room = self.chat.create_room("room1")
        room.join("p1")
        msg = self.chat.send_to_room("room1", "p1", "Alice", "Hello!")
        self.assertIsNotNone(msg)
        self.assertEqual(msg.content, "Hello!")

    def test_direct_message(self):
        msg = self.chat.send_direct_message("p1", "Alice", "p2", "Hi Bob!")
        self.assertIsNotNone(msg)
        dms = self.chat.get_direct_messages("p1", "p2")
        self.assertEqual(len(dms), 1)


if __name__ == "__main__":
    unittest.main()
