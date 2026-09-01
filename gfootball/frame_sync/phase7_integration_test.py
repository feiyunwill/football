"""
Integration tests for Phase 7 commercial features.

Tests all modules working together:
- Lobby + Matchmaking + Player Profile
- Ranking + Season
- Audio + Commentary
- Tutorial + Challenges
- Content + Save System
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from lobby import Lobby
from matchmaking import Matchmaker
from player_profile import ProfileManager
from chat import ChatManager
from ranking import RankingManager, LeaderboardType
from season import SeasonManager
from audio_manager import AudioManager, AudioCategory
from commentary import CommentarySystem, CommentaryEvent, CommentaryContext
from tutorial import TutorialSystem, TrainingMode, ChallengeType
from challenges import ChallengeManager
from content_manager import ContentManager
from save_system import SaveManager, SaveType, GameProgress
from replay import ReplayManager


class TestLobbyIntegration(unittest.TestCase):
    """Integration tests for lobby, matchmaking, and profiles."""

    def setUp(self):
        self.lobby = Lobby()
        self.matchmaker = Matchmaker()
        self.profiles = ProfileManager()
        self.chat = ChatManager()

    def test_full_multiplayer_flow(self):
        # Register players
        self.profiles.create_profile("p1", "Alice")
        self.profiles.create_profile("p2", "Bob")

        # Join lobby
        self.lobby.register_player("p1", "Alice", 1200)
        self.lobby.register_player("p2", "Bob", 1150)

        # Create room
        room = self.lobby.create_room("p1", "Match Room")
        self.assertIsNotNone(room)

        # Join room
        result = self.lobby.join_room("p2", room.room_id)
        self.assertTrue(result)

        # Chat
        chat_room = self.chat.create_room(room.room_id)
        chat_room.join("p1")
        chat_room.join("p2")
        msg = self.chat.send_to_room(room.room_id, "p1", "Alice", "Ready?")
        self.assertIsNotNone(msg)

        # Record match result
        self.profiles.record_match("p1", "p2", 3, 1)

        # Check stats
        p1 = self.profiles.get_profile("p1")
        self.assertEqual(p1.stats.games_won, 1)

    def test_matchmaking_flow(self):
        # Queue players
        self.matchmaker.enqueue("p1", 1000)
        self.matchmaker.enqueue("p2", 1050)

        # Find match
        match = self.matchmaker.find_match("p1")
        self.assertEqual(match, "p2")


class TestRankingIntegration(unittest.TestCase):
    """Integration tests for ranking and season."""

    def setUp(self):
        self.ranking = RankingManager()
        self.season = SeasonManager()
        self.ranking.create_board("global", LeaderboardType.GLOBAL)

    def test_season_with_ranking(self):
        # Start season
        self.season.create_season("s1", "Season 1")
        self.season.start_season("s1")

        # Record matches
        self.season.record_match("p1", "p2", 3, 1)
        self.season.record_match("p1", "p3", 2, 0)

        # Update rankings
        season = self.season.get_current_season()
        for player_id, stats in season.player_stats.items():
            self.ranking.update_player_rating(
                "global", player_id, player_id,
                1000 + stats.points * 10,
                stats.games_played,
                stats.win_rate
            )

        # Check leaderboard
        top = self.ranking.get_global_top(5)
        self.assertGreater(len(top), 0)
        self.assertEqual(top[0].player_id, "p1")


class TestAudioIntegration(unittest.TestCase):
    """Integration tests for audio and commentary."""

    def setUp(self):
        self.audio = AudioManager()
        self.commentary = CommentarySystem()

    def test_match_commentary(self):
        # Load audio
        self.audio.load_track("goal_sfx", "goal.wav", AudioCategory.SFX)
        self.audio.load_track("music", "music.wav", AudioCategory.MUSIC)

        # Play sounds
        self.audio.play_sfx("goal_sfx")
        self.audio.play_music("music")

        # Trigger commentary
        context = CommentaryContext(event=CommentaryEvent.GOAL, minute=45)
        text = self.commentary.trigger_event(context)
        self.assertIsNotNone(text)

        # Check status
        status = self.audio.get_status()
        self.assertEqual(status["playing_tracks"], 2)


class TestTutorialIntegration(unittest.TestCase):
    """Integration tests for tutorial and challenges."""

    def setUp(self):
        self.tutorial = TutorialSystem()
        self.training = TrainingMode()
        self.challenges = ChallengeManager()

    def test_new_player_journey(self):
        # Start tutorial
        instruction = self.tutorial.start_tutorial("new_player")
        self.assertEqual(instruction.step.value, "move")

        # Complete tutorial steps
        for _ in range(7):
            self.tutorial.complete_step("new_player")
        self.assertTrue(self.tutorial.is_completed("new_player"))

        # Try training
        from tutorial import TrainingResult
        result = TrainingResult(
            player_id="new_player",
            mode=ChallengeType.SHOOTING,
            score=8,
            targets_hit=8,
            targets_total=10,
            time_seconds=45.0,
            completed=True,
        )
        self.training.record_result(result)

        # Try challenge
        challenge_result = self.challenges.attempt_challenge(
            "new_player", "shooting_easy", 6, 50.0
        )
        self.assertTrue(challenge_result.completed)


class TestContentSaveIntegration(unittest.TestCase):
    """Integration tests for content and save system."""

    def setUp(self):
        self.content = ContentManager()
        self.save = SaveManager()
        self.progress = GameProgress()

    def test_content_with_progress(self):
        # Get team
        team = self.content.get_team("real_madrid")
        self.assertIsNotNone(team)

        # Unlock team
        self.progress.unlock_team("real_madrid")
        self.assertTrue(self.progress.is_team_unlocked("real_madrid"))

        # Save progress
        self.save.create_slot("slot1", "Career Save", SaveType.PROGRESS)
        self.save.save("slot1", self.progress.to_dict())

        # Load progress
        loaded_data = self.save.load("slot1")
        self.assertIsNotNone(loaded_data)

        # Update stats
        self.progress.update_stats(match_played=True, goal_scored=True, won=True)
        self.assertEqual(self.progress.get("stats.total_matches"), 1)


class TestEndToEndMatch(unittest.TestCase):
    """End-to-end match simulation test."""

    def test_complete_match_flow(self):
        # Setup
        lobby = Lobby()
        profiles = ProfileManager()
        ranking = RankingManager()
        season = SeasonManager()
        replay = ReplayManager()
        save = SaveManager()
        commentary = CommentarySystem()

        # Create players
        profiles.create_profile("home", "Home Team")
        profiles.create_profile("away", "Away Team")

        # Register in lobby
        lobby.register_player("home", "Home Team", 1000)
        lobby.register_player("away", "Away Team", 1000)

        # Create room and start match
        room = lobby.create_room("home", "Match Room")
        lobby.join_room("away", room.room_id)

        # Start season and recording
        season.create_season("s1", "Season 1")
        season.start_season("s1")
        replay.start_recording("replay_1", "match_1", "Home", "Away")

        # Simulate match events
        commentary.trigger_event(CommentaryContext(event=CommentaryEvent.MATCH_START, minute=0))
        commentary.trigger_event(CommentaryContext(event=CommentaryEvent.GOAL, minute=23))
        commentary.trigger_event(CommentaryContext(event=CommentaryEvent.HALF_TIME, minute=45))
        commentary.trigger_event(CommentaryContext(event=CommentaryEvent.GOAL, minute=67))
        commentary.trigger_event(CommentaryContext(event=CommentaryEvent.FULL_TIME, minute=90))

        # Record match result
        season.record_match("home", "away", 2, 0)
        profiles.record_match("home", "away", 2, 0)

        # Save match
        save.create_slot("match_1", "Match Result", SaveType.REPLAY)
        save.save("match_1", {"winner": "home", "score": "2-0"})

        # Stop recording
        replay.stop_recording()

        # Verify
        self.assertEqual(profiles.get_profile("home").stats.games_won, 1)
        self.assertEqual(len(replay.list_replays()), 1)
        self.assertIsNotNone(save.load("match_1"))


if __name__ == "__main__":
    unittest.main()
