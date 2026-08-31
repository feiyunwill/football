"""
Player profile and statistics management.

This module provides:
- Player profile CRUD
- Statistics tracking
- Achievement system
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlayerStats:
    """Player game statistics."""
    games_played: int = 0
    games_won: int = 0
    games_lost: int = 0
    games_drawn: int = 0
    goals_scored: int = 0
    goals_conceded: int = 0
    assists: int = 0
    clean_sheets: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    longest_win_streak: int = 0
    current_win_streak: int = 0

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        if self.games_played == 0:
            return 0.0
        return self.games_won / self.games_played

    @property
    def goal_difference(self) -> int:
        """Calculate goal difference."""
        return self.goals_scored - self.goals_conceded

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "games_played": self.games_played,
            "games_won": self.games_won,
            "games_lost": self.games_lost,
            "games_drawn": self.games_drawn,
            "goals_scored": self.goals_scored,
            "goals_conceded": self.goals_conceded,
            "assists": self.assists,
            "clean_sheets": self.clean_sheets,
            "yellow_cards": self.yellow_cards,
            "red_cards": self.red_cards,
            "longest_win_streak": self.longest_win_streak,
            "current_win_streak": self.current_win_streak,
        }


@dataclass
class Achievement:
    """Player achievement."""
    achievement_id: str
    name: str
    description: str
    unlocked_at: Optional[float] = None


@dataclass
class PlayerProfile:
    """Complete player profile."""
    player_id: str
    name: str
    rating: int = 1000
    level: int = 1
    experience: int = 0
    stats: PlayerStats = field(default_factory=PlayerStats)
    achievements: list[Achievement] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_login: float = field(default_factory=time.time)
    avatar_url: Optional[str] = None
    title: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get display name with title if available."""
        if self.title:
            return f"[{self.title}] {self.name}"
        return self.name

    def add_experience(self, amount: int) -> bool:
        """Add experience and check for level up.

        Returns:
            True if level up occurred
        """
        self.experience += amount
        exp_needed = self._exp_for_level(self.level + 1)

        if self.experience >= exp_needed:
            self.level += 1
            return True
        return False

    def _exp_for_level(self, level: int) -> int:
        """Calculate experience needed for a level."""
        return int(100 * (1.5 ** (level - 1)))

    def record_achievement(self, achievement: Achievement) -> bool:
        """Record a new achievement.

        Returns:
            True if achievement was newly unlocked
        """
        if any(a.achievement_id == achievement.achievement_id for a in self.achievements):
            return False

        achievement.unlocked_at = time.time()
        self.achievements.append(achievement)
        return True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "player_id": self.player_id,
            "name": self.name,
            "rating": self.rating,
            "level": self.level,
            "experience": self.experience,
            "stats": self.stats.to_dict(),
            "achievements": [
                {"id": a.achievement_id, "name": a.name, "unlocked_at": a.unlocked_at}
                for a in self.achievements
            ],
            "created_at": self.created_at,
            "last_login": self.last_login,
            "avatar_url": self.avatar_url,
            "title": self.title,
        }


class ProfileManager:
    """Manager for player profiles."""

    def __init__(self):
        self._profiles: dict[str, PlayerProfile] = {}

    def create_profile(self, player_id: str, name: str,
                       avatar_url: Optional[str] = None) -> PlayerProfile:
        """Create a new player profile."""
        if player_id in self._profiles:
            return self._profiles[player_id]

        profile = PlayerProfile(
            player_id=player_id,
            name=name,
            avatar_url=avatar_url,
        )
        self._profiles[player_id] = profile
        return profile

    def get_profile(self, player_id: str) -> Optional[PlayerProfile]:
        """Get a player profile."""
        return self._profiles.get(player_id)

    def update_profile(self, player_id: str, **kwargs) -> bool:
        """Update player profile fields."""
        profile = self._profiles.get(player_id)
        if not profile:
            return False

        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        return True

    def delete_profile(self, player_id: str) -> bool:
        """Delete a player profile."""
        if player_id in self._profiles:
            del self._profiles[player_id]
            return True
        return False

    def record_match(self, winner_id: str, loser_id: str,
                     winner_goals: int, loser_goals: int,
                     draw: bool = False) -> None:
        """Record match results for both players."""
        winner = self._profiles.get(winner_id)
        loser = self._profiles.get(loser_id)

        if winner:
            winner.stats.games_played += 1
            winner.stats.goals_scored += winner_goals
            winner.stats.goals_conceded += loser_goals
            winner.last_login = time.time()

            if draw:
                winner.stats.games_drawn += 1
            elif winner_id == winner_id:
                winner.stats.games_won += 1
                winner.stats.current_win_streak += 1
                winner.stats.longest_win_streak = max(
                    winner.stats.longest_win_streak,
                    winner.stats.current_win_streak
                )
            else:
                winner.stats.games_lost += 1
                winner.stats.current_win_streak = 0

            if loser_goals == 0:
                winner.stats.clean_sheets += 1

        if loser:
            loser.stats.games_played += 1
            loser.stats.goals_scored += loser_goals
            loser.stats.goals_conceded += winner_goals
            loser.last_login = time.time()

            if draw:
                loser.stats.games_drawn += 1
            else:
                loser.stats.games_lost += 1
                loser.stats.current_win_streak = 0

    def get_leaderboard(self, limit: int = 10,
                        sort_by: str = "rating") -> list[PlayerProfile]:
        """Get leaderboard sorted by specified field."""
        profiles = list(self._profiles.values())

        if sort_by == "rating":
            profiles.sort(key=lambda p: p.rating, reverse=True)
        elif sort_by == "level":
            profiles.sort(key=lambda p: p.level, reverse=True)
        elif sort_by == "win_rate":
            profiles.sort(key=lambda p: p.stats.win_rate, reverse=True)
        elif sort_by == "goals":
            profiles.sort(key=lambda p: p.stats.goals_scored, reverse=True)

        return profiles[:limit]

    def search_players(self, query: str) -> list[PlayerProfile]:
        """Search players by name."""
        query_lower = query.lower()
        return [
            p for p in self._profiles.values()
            if query_lower in p.name.lower()
        ]

    def get_player_count(self) -> int:
        """Get total number of players."""
        return len(self._profiles)
