"""
Season and league management system.

This module provides:
- Season lifecycle management
- League tiers and promotion/relegation
- Season rewards
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SeasonStatus(Enum):
    """Season status states."""
    UPCOMING = "upcoming"
    ACTIVE = "active"
    FINISHED = "finished"


class LeagueTier(Enum):
    """League tiers."""
    BEGINNER = "beginner"
    AMATEUR = "amateur"
    SEMI_PRO = "semi_pro"
    PRO = "pro"
    ELITE = "elite"
    LEGEND = "legend"


# Promotion/relegation thresholds
LEAGUE_ORDER = [
    LeagueTier.BEGINNER,
    LeagueTier.AMATEUR,
    LeagueTier.SEMI_PRO,
    LeagueTier.PRO,
    LeagueTier.ELITE,
    LeagueTier.LEGEND,
]

PROMOTION_THRESHOLD = 3  # Top 3 promote
RELEGATION_THRESHOLD = -3  # Bottom 3 relegate


@dataclass
class SeasonRewards:
    """Rewards for a season."""
    tier_rewards: dict = field(default_factory=dict)
    participation_reward: int = 100
    champion_reward: int = 1000
    top10_reward: int = 500
    top50_reward: int = 200


@dataclass
class SeasonPlayerStats:
    """Player statistics for a season."""
    player_id: str
    games_played: int = 0
    games_won: int = 0
    games_lost: int = 0
    goals_scored: int = 0
    goals_conceded: int = 0
    points: int = 0
    rating_change: int = 0

    @property
    def win_rate(self) -> float:
        if self.games_played == 0:
            return 0.0
        return self.games_won / self.games_played

    @property
    def goal_difference(self) -> int:
        return self.goals_scored - self.goals_conceded

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "games_played": self.games_played,
            "games_won": self.games_won,
            "games_lost": self.games_lost,
            "goals_scored": self.goals_scored,
            "goals_conceded": self.goals_conceded,
            "points": self.points,
            "rating_change": self.rating_change,
        }


@dataclass
class Season:
    """A competitive season."""
    season_id: str
    name: str
    status: SeasonStatus = SeasonStatus.UPCOMING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_days: int = 30
    player_stats: dict[str, SeasonPlayerStats] = field(default_factory=dict)
    rewards: SeasonRewards = field(default_factory=SeasonRewards)
    created_at: float = field(default_factory=time.time)

    def start(self) -> None:
        """Start the season."""
        self.status = SeasonStatus.ACTIVE
        self.start_time = time.time()
        self.end_time = self.start_time + (self.duration_days * 86400)

    def finish(self) -> None:
        """Finish the season."""
        self.status = SeasonStatus.FINISHED
        self.end_time = time.time()

    def is_active(self) -> bool:
        """Check if season is currently active."""
        if self.status != SeasonStatus.ACTIVE:
            return False
        if self.end_time and time.time() > self.end_time:
            self.finish()
            return False
        return True

    def record_match(self, winner_id: str, loser_id: str,
                     winner_goals: int, loser_goals: int) -> None:
        """Record a match result for the season."""
        winner_stats = self._get_or_create_stats(winner_id)
        loser_stats = self._get_or_create_stats(loser_id)

        winner_stats.games_played += 1
        winner_stats.games_won += 1
        winner_stats.goals_scored += winner_goals
        winner_stats.goals_conceded += loser_goals
        winner_stats.points += 3

        loser_stats.games_played += 1
        loser_stats.games_lost += 1
        loser_stats.goals_scored += loser_goals
        loser_stats.goals_conceded += winner_goals

    def _get_or_create_stats(self, player_id: str) -> SeasonPlayerStats:
        """Get or create player stats for this season."""
        if player_id not in self.player_stats:
            self.player_stats[player_id] = SeasonPlayerStats(player_id=player_id)
        return self.player_stats[player_id]

    def get_leaderboard(self, limit: int = 50) -> list[SeasonPlayerStats]:
        """Get season leaderboard sorted by points."""
        stats = list(self.player_stats.values())
        stats.sort(key=lambda s: (-s.points, -s.goal_difference, -s.goals_scored))
        return stats[:limit]

    def get_rewards(self, player_id: str) -> dict:
        """Calculate rewards for a player based on final standing."""
        leaderboard = self.get_leaderboard()
        rank = next(
            (i + 1 for i, s in enumerate(leaderboard) if s.player_id == player_id),
            None
        )

        if not rank:
            return {"participation": self.rewards.participation_reward}

        rewards = {"participation": self.rewards.participation_reward}

        if rank == 1:
            rewards["champion"] = self.rewards.champion_reward
        elif rank <= 10:
            rewards["top10"] = self.rewards.top10_reward
        elif rank <= 50:
            rewards["top50"] = self.rewards.top50_reward

        return rewards

    def to_dict(self) -> dict:
        return {
            "season_id": self.season_id,
            "name": self.name,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_days": self.duration_days,
            "player_count": len(self.player_stats),
        }


class SeasonManager:
    """Manager for seasons."""

    def __init__(self):
        self._seasons: dict[str, Season] = {}
        self._current_season: Optional[str] = None

    def create_season(self, season_id: str, name: str,
                      duration_days: int = 30) -> Season:
        """Create a new season."""
        season = Season(
            season_id=season_id,
            name=name,
            duration_days=duration_days,
        )
        self._seasons[season_id] = season
        return season

    def start_season(self, season_id: str) -> bool:
        """Start a season."""
        season = self._seasons.get(season_id)
        if not season or season.status != SeasonStatus.UPCOMING:
            return False

        if self._current_season:
            current = self._seasons.get(self._current_season)
            if current and current.is_active():
                return False

        season.start()
        self._current_season = season_id
        return True

    def finish_season(self, season_id: str) -> bool:
        """Finish a season."""
        season = self._seasons.get(season_id)
        if not season:
            return False

        season.finish()
        if self._current_season == season_id:
            self._current_season = None
        return True

    def get_current_season(self) -> Optional[Season]:
        """Get the current active season."""
        if self._current_season:
            return self._seasons.get(self._current_season)
        return None

    def get_season(self, season_id: str) -> Optional[Season]:
        """Get a specific season."""
        return self._seasons.get(season_id)

    def list_seasons(self) -> list[dict]:
        """List all seasons."""
        return [s.to_dict() for s in self._seasons.values()]

    def record_match(self, winner_id: str, loser_id: str,
                     winner_goals: int, loser_goals: int) -> bool:
        """Record a match in the current season."""
        season = self.get_current_season()
        if not season or not season.is_active():
            return False

        season.record_match(winner_id, loser_id, winner_goals, loser_goals)
        return True
