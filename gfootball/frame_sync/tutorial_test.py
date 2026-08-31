"""
Tests for the tutorial and challenges systems.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from tutorial import TutorialSystem, TrainingMode, ChallengeType, TutorialStep
from challenges import ChallengeManager, ChallengeDifficulty


class TestTutorialSystem(unittest.TestCase):
    """Test TutorialSystem class."""

    def setUp(self):
        self.tutorial = TutorialSystem()

    def test_start_tutorial(self):
        instruction = self.tutorial.start_tutorial("p1")
        self.assertEqual(instruction.step, TutorialStep.MOVE)

    def test_complete_step(self):
        self.tutorial.start_tutorial("p1")
        next_step = self.tutorial.complete_step("p1")
        self.assertEqual(next_step.step, TutorialStep.PASS)

    def test_progress_tracking(self):
        self.tutorial.start_tutorial("p1")
        self.tutorial.complete_step("p1")
        self.tutorial.complete_step("p1")
        progress = self.tutorial.get_progress("p1")
        self.assertEqual(len(progress.completed_steps), 2)

    def test_completion_rate(self):
        self.tutorial.start_tutorial("p1")
        self.tutorial.complete_step("p1")
        rate = self.tutorial.get_completion_rate("p1")
        self.assertGreater(rate, 0)

    def test_full_completion(self):
        self.tutorial.start_tutorial("p1")
        for _ in range(7):
            self.tutorial.complete_step("p1")
        self.assertTrue(self.tutorial.is_completed("p1"))


class TestTrainingMode(unittest.TestCase):
    """Test TrainingMode class."""

    def setUp(self):
        self.training = TrainingMode()

    def test_get_config(self):
        config = self.training.get_config(ChallengeType.SHOOTING)
        self.assertIsNotNone(config)
        self.assertEqual(config.mode, ChallengeType.SHOOTING)

    def test_record_result(self):
        from tutorial import TrainingResult
        result = TrainingResult(
            player_id="p1",
            mode=ChallengeType.SHOOTING,
            score=8,
            targets_hit=8,
            targets_total=10,
            time_seconds=45.0,
            completed=True,
        )
        self.training.record_result(result)
        best = self.training.get_best_score("p1", ChallengeType.SHOOTING)
        self.assertEqual(best, 8)


class TestChallengeManager(unittest.TestCase):
    """Test ChallengeManager class."""

    def setUp(self):
        self.manager = ChallengeManager()

    def test_list_challenges(self):
        challenges = self.manager.list_challenges()
        self.assertGreater(len(challenges), 0)

    def test_get_challenge(self):
        challenge = self.manager.get_challenge("shooting_easy")
        self.assertIsNotNone(challenge)
        self.assertEqual(challenge.name, "Sharp Shooter")

    def test_attempt_challenge(self):
        result = self.manager.attempt_challenge("p1", "shooting_easy", 6, 50.0)
        self.assertIsNotNone(result)
        self.assertTrue(result.completed)
        self.assertEqual(result.reward_xp, 50)

    def test_failed_challenge(self):
        result = self.manager.attempt_challenge("p1", "shooting_easy", 3, 50.0)
        self.assertFalse(result.completed)
        self.assertEqual(result.reward_xp, 0)

    def test_player_best(self):
        self.manager.attempt_challenge("p1", "shooting_easy", 6, 50.0)
        self.manager.attempt_challenge("p1", "shooting_easy", 8, 45.0)
        best = self.manager.get_player_best("p1", "shooting_easy")
        self.assertEqual(best.score, 8)

    def test_leaderboard(self):
        self.manager.attempt_challenge("p1", "shooting_easy", 6, 50.0)
        self.manager.attempt_challenge("p2", "shooting_easy", 8, 45.0)
        board = self.manager.get_leaderboard("shooting_easy")
        self.assertEqual(len(board), 2)


if __name__ == "__main__":
    unittest.main()
