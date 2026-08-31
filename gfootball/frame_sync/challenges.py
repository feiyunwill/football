"""
Skill challenges and achievements system.

This module provides:
- Timed challenges
- Score-based challenges
- Achievement tracking
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChallengeDifficulty(Enum):
    """Challenge difficulty levels."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    LEGENDARY = "legendary"


@dataclass
class ChallengeConfig:
    """Configuration for a challenge."""
    challenge_id: str
    name: str
    description: str
    difficulty: ChallengeDifficulty
    challenge_type: str
    time_limit_seconds: int = 60
    target_score: int = 100
    reward_xp: int = 50
    reward_title: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "challenge_id": self.challenge_id,
            "name": self.name,
            "difficulty": self.difficulty.value,
            "time_limit_seconds": self.time_limit_seconds,
            "target_score": self.target_score,
            "reward_xp": self.reward_xp,
        }


@dataclass
class ChallengeResult:
    """Result of a challenge attempt."""
    player_id: str
    challenge_id: str
    score: int
    time_seconds: float
    completed: bool
    reward_xp: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "challenge_id": self.challenge_id,
            "score": self.score,
            "time_seconds": self.time_seconds,
            "completed": self.completed,
            "reward_xp": self.reward_xp,
        }


class ChallengeManager:
    """Manages skill challenges."""

    def __init__(self):
        self._challenges: dict[str, ChallengeConfig] = {}
        self._results: dict[str, list[ChallengeResult]] = {}
        self._load_default_challenges()

    def _load_default_challenges(self) -> None:
        """Load default challenges."""
        self._challenges["shooting_easy"] = ChallengeConfig(
            challenge_id="shooting_easy",
            name="Sharp Shooter",
            description="Score 5 goals in 60 seconds",
            difficulty=ChallengeDifficulty.EASY,
            challenge_type="shooting",
            time_limit_seconds=60,
            target_score=5,
            reward_xp=50,
        )
        self._challenges["shooting_hard"] = ChallengeConfig(
            challenge_id="shooting_hard",
            name="Goal Machine",
            description="Score 10 goals in 60 seconds",
            difficulty=ChallengeDifficulty.HARD,
            challenge_type="shooting",
            time_limit_seconds=60,
            target_score=10,
            reward_xp=150,
            reward_title="Goal Machine",
        )
        self._challenges["passing_easy"] = ChallengeConfig(
            challenge_id="passing_easy",
            name="Pass Master",
            description="Complete 20 passes in 60 seconds",
            difficulty=ChallengeDifficulty.EASY,
            challenge_type="passing",
            time_limit_seconds=60,
            target_score=20,
            reward_xp=50,
        )
        self._challenges["dribbling_easy"] = ChallengeConfig(
            challenge_id="dribbling_easy",
            name="Dribble King",
            description="Dribble past 5 defenders in 45 seconds",
            difficulty=ChallengeDifficulty.EASY,
            challenge_type="dribbling",
            time_limit_seconds=45,
            target_score=5,
            reward_xp=75,
        )

    def get_challenge(self, challenge_id: str) -> Optional[ChallengeConfig]:
        """Get a challenge configuration."""
        return self._challenges.get(challenge_id)

    def list_challenges(self, difficulty: Optional[ChallengeDifficulty] = None
                       ) -> list[ChallengeConfig]:
        """List all challenges, optionally filtered by difficulty."""
        challenges = list(self._challenges.values())
        if difficulty:
            challenges = [c for c in challenges if c.difficulty == difficulty]
        return challenges

    def attempt_challenge(self, player_id: str, challenge_id: str,
                         score: int, time_seconds: float) -> Optional[ChallengeResult]:
        """Record a challenge attempt."""
        config = self._challenges.get(challenge_id)
        if not config:
            return None

        completed = score >= config.target_score
        reward = config.reward_xp if completed else 0

        result = ChallengeResult(
            player_id=player_id,
            challenge_id=challenge_id,
            score=score,
            time_seconds=time_seconds,
            completed=completed,
            reward_xp=reward,
        )

        if player_id not in self._results:
            self._results[player_id] = []
        self._results[player_id].append(result)

        return result

    def get_player_best(self, player_id: str, challenge_id: str) -> Optional[ChallengeResult]:
        """Get a player's best result for a challenge."""
        results = self._results.get(player_id, [])
        challenge_results = [r for r in results if r.challenge_id == challenge_id]
        if not challenge_results:
            return None
        return max(challenge_results, key=lambda r: r.score)

    def get_player_completed(self, player_id: str) -> list[str]:
        """Get list of challenge IDs a player has completed."""
        results = self._results.get(player_id, [])
        return list(set(r.challenge_id for r in results if r.completed))

    def get_leaderboard(self, challenge_id: str, limit: int = 10
                       ) -> list[tuple[str, int]]:
        """Get leaderboard for a challenge."""
        best_scores: dict[str, int] = {}
        for player_id, results in self._results.items():
            challenge_results = [r for r in results if r.challenge_id == challenge_id]
            if challenge_results:
                best_scores[player_id] = max(r.score for r in challenge_results)

        sorted_scores = sorted(best_scores.items(), key=lambda x: -x[1])
        return sorted_scores[:limit]

    def get_total_challenges(self) -> int:
        """Get total number of challenges."""
        return len(self._challenges)
