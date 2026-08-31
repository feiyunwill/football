"""
Ranking and leaderboard system.

This module provides:
- Global leaderboards
- Regional leaderboards
- Friend leaderboards
- Season rankings
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LeaderboardType(Enum):
    """Types of leaderboards."""
    GLOBAL = "global"
    REGIONAL = "regional"
    FRIEND = "friend"
    SEASON = "season"


class RankTier(Enum):
    """Player rank tiers based on rating."""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"
    MASTER = "master"
    GRANDMASTER = "grandmaster"


# Rating thresholds for tiers
TIER_THRESHOLDS = {
    RankTier.BRONZE: 0,
    RankTier.SILVER: 800,
    RankTier.GOLD: 1000,
    RankTier.PLATINUM: 1200,
    RankTier.DIAMOND: 1400,
    RankTier.MASTER: 1600,
    RankTier.GRANDMASTER: 1800,
}


@dataclass
class RankingEntry:
    """A single entry in a leaderboard."""
    player_id: str
    player_name: str
    rating: int
    rank: int = 0
    games_played: int = 0
    win_rate: float = 0.0
    last_updated: float = field(default_factory=time.time)

    @property
    def tier(self) -> RankTier:
        """Get the player's rank tier based on rating."""
        result = RankTier.BRONZE
        for tier, threshold in TIER_THRESHOLDS.items():
            if self.rating >= threshold:
                result = tier
        return result

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "rating": self.rating,
            "rank": self.rank,
            "tier": self.tier.value,
            "games_played": self.games_played,
            "win_rate": self.win_rate,
        }


@dataclass
class Leaderboard:
    """A leaderboard containing ranked players."""
    board_id: str
    board_type: LeaderboardType
    entries: list[RankingEntry] = field(default_factory=list)
    max_entries: int = 1000
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_entry(self, entry: RankingEntry) -> None:
        """Add or update an entry in the leaderboard."""
        existing = next((e for e in self.entries if e.player_id == entry.player_id), None)
        if existing:
            existing.rating = entry.rating
            existing.games_played = entry.games_played
            existing.win_rate = entry.win_rate
            existing.last_updated = time.time()
        else:
            self.entries.append(entry)

        self._sort_and_rank()
        self.last_updated = time.time()

    def remove_entry(self, player_id: str) -> bool:
        """Remove an entry from the leaderboard."""
        for i, entry in enumerate(self.entries):
            if entry.player_id == player_id:
                self.entries.pop(i)
                self._sort_and_rank()
                return True
        return False

    def get_entry(self, player_id: str) -> Optional[RankingEntry]:
        """Get a specific player's entry."""
        return next((e for e in self.entries if e.player_id == player_id), None)

    def get_top(self, count: int = 10) -> list[RankingEntry]:
        """Get the top N players."""
        return self.entries[:count]

    def get_rank(self, player_id: str) -> Optional[int]:
        """Get a player's rank (1-based)."""
        entry = self.get_entry(player_id)
        return entry.rank if entry else None

    def get_player周围(self, player_id: str, range_count: int = 5) -> list[RankingEntry]:
        """Get players around a specific player."""
        entry = self.get_entry(player_id)
        if not entry:
            return []

        idx = self.entries.index(entry)
        start = max(0, idx - range_count)
        end = min(len(self.entries), idx + range_count + 1)
        return self.entries[start:end]

    def _sort_and_rank(self) -> None:
        """Sort entries by rating and assign ranks."""
        self.entries.sort(key=lambda e: (-e.rating, e.last_updated))
        for i, entry in enumerate(self.entries):
            entry.rank = i + 1

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "board_id": self.board_id,
            "board_type": self.board_type.value,
            "entries": [e.to_dict() for e in self.entries[:100]],
            "total_entries": len(self.entries),
            "last_updated": self.last_updated,
        }


class RankingManager:
    """Manager for all leaderboards."""

    def __init__(self):
        self._boards: dict[str, Leaderboard] = {}
        self._player_boards: dict[str, set[str]] = {}

    def create_board(self, board_id: str, board_type: LeaderboardType,
                     max_entries: int = 1000) -> Leaderboard:
        """Create a new leaderboard."""
        if board_id not in self._boards:
            self._boards[board_id] = Leaderboard(
                board_id=board_id,
                board_type=board_type,
                max_entries=max_entries,
            )
        return self._boards[board_id]

    def get_board(self, board_id: str) -> Optional[Leaderboard]:
        """Get a leaderboard."""
        return self._boards.get(board_id)

    def delete_board(self, board_id: str) -> bool:
        """Delete a leaderboard."""
        if board_id in self._boards:
            del self._boards[board_id]
            return True
        return False

    def update_player_rating(self, board_id: str, player_id: str,
                             player_name: str, rating: int,
                             games_played: int = 0, win_rate: float = 0.0
                             ) -> bool:
        """Update a player's rating on a leaderboard."""
        board = self._boards.get(board_id)
        if not board:
            return False

        entry = RankingEntry(
            player_id=player_id,
            player_name=player_name,
            rating=rating,
            games_played=games_played,
            win_rate=win_rate,
        )
        board.add_entry(entry)

        if player_id not in self._player_boards:
            self._player_boards[player_id] = set()
        self._player_boards[player_id].add(board_id)

        return True

    def get_player_rank(self, board_id: str, player_id: str) -> Optional[int]:
        """Get a player's rank on a specific board."""
        board = self._boards.get(board_id)
        return board.get_rank(player_id) if board else None

    def get_player_boards(self, player_id: str) -> list[str]:
        """Get all boards a player is on."""
        return list(self._player_boards.get(player_id, set()))

    def get_global_top(self, count: int = 10) -> list[RankingEntry]:
        """Get the global top players."""
        global_board = self._boards.get("global")
        return global_board.get_top(count) if global_board else []

    def list_boards(self) -> list[dict]:
        """List all leaderboards."""
        return [
            {"board_id": b.board_id, "type": b.board_type.value, "entries": len(b.entries)}
            for b in self._boards.values()
        ]
