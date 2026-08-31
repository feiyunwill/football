"""
Matchmaking system with ELO-based rating.

This module provides:
- ELO rating calculation
- Match quality assessment
- Queue management with rating-based matching
"""

import time
from dataclasses import dataclass, field
from typing import Optional


# ELO constants
DEFAULT_K_FACTOR = 32
DEFAULT_INITIAL_RATING = 1000
MAX_RATING_DIFF = 400


@dataclass
class MatchResult:
    """Result of a completed match."""
    winner_id: str
    loser_id: str
    winner_rating_before: int
    loser_rating_before: int
    winner_rating_after: int
    loser_rating_after: int
    timestamp: float = field(default_factory=time.time)


class EloCalculator:
    """ELO rating calculator."""

    def __init__(self, k_factor: int = DEFAULT_K_FACTOR):
        self.k_factor = k_factor

    def expected_score(self, rating_a: int, rating_b: int) -> float:
        """Calculate expected score for player A against player B."""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / MAX_RATING_DIFF))

    def calculate_new_ratings(self, winner_rating: int, loser_rating: int,
                              draw: bool = False) -> tuple[int, int]:
        """Calculate new ratings after a match.

        Returns:
            Tuple of (winner_new_rating, loser_new_rating) or (rating_a, rating_b) if draw
        """
        if draw:
            expected_a = self.expected_score(winner_rating, loser_rating)
            expected_b = 1.0 - expected_a
            new_a = int(winner_rating + self.k_factor * (0.5 - expected_a))
            new_b = int(loser_rating + self.k_factor * (0.5 - expected_b))
            return new_a, new_b

        expected_winner = self.expected_score(winner_rating, loser_rating)
        expected_loser = 1.0 - expected_winner

        new_winner = int(winner_rating + self.k_factor * (1.0 - expected_winner))
        new_loser = int(loser_rating + self.k_factor * (0.0 - expected_loser))

        return new_winner, new_loser


@dataclass
class QueueEntry:
    """Entry in the matchmaking queue."""
    player_id: str
    rating: int
    queued_at: float = field(default_factory=time.time)
    priority: int = 0


class Matchmaker:
    """Matchmaking queue manager."""

    def __init__(self, max_rating_diff: int = 200, expand_rate: float = 10):
        self._queue: list[QueueEntry] = []
        self._max_rating_diff = max_rating_diff
        self._expand_rate = expand_rate
        self._elo = EloCalculator()

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def enqueue(self, player_id: str, rating: int) -> bool:
        """Add a player to the matchmaking queue."""
        if any(e.player_id == player_id for e in self._queue):
            return False

        entry = QueueEntry(player_id=player_id, rating=rating)
        self._queue.append(entry)
        return True

    def dequeue(self, player_id: str) -> bool:
        """Remove a player from the matchmaking queue."""
        for i, entry in enumerate(self._queue):
            if entry.player_id == player_id:
                self._queue.pop(i)
                return True
        return False

    def find_match(self, player_id: str) -> Optional[str]:
        """Find a match for the given player.

        Uses expanding rating window based on wait time.
        """
        player_entry = None
        for entry in self._queue:
            if entry.player_id == player_id:
                player_entry = entry
                break

        if not player_entry:
            return None

        wait_time = time.time() - player_entry.queued_at
        current_max_diff = self._max_rating_diff + int(wait_time * self._expand_rate)

        best_match = None
        best_diff = float('inf')

        for entry in self._queue:
            if entry.player_id == player_id:
                continue

            rating_diff = abs(player_entry.rating - entry.rating)
            if rating_diff <= current_max_diff and rating_diff < best_diff:
                best_diff = rating_diff
                best_match = entry.player_id

        if best_match:
            self._queue = [e for e in self._queue
                          if e.player_id not in (player_id, best_match)]

        return best_match

    def find_best_match(self) -> Optional[tuple[str, str]]:
        """Find the best match pair in the queue.

        Returns:
            Tuple of (player1_id, player2_id) or None
        """
        if len(self._queue) < 2:
            return None

        sorted_queue = sorted(self._queue, key=lambda e: e.rating)

        best_pair = None
        best_diff = float('inf')

        for i in range(len(sorted_queue)):
            for j in range(i + 1, len(sorted_queue)):
                diff = abs(sorted_queue[i].rating - sorted_queue[j].rating)
                if diff < best_diff:
                    best_diff = diff
                    best_pair = (sorted_queue[i].player_id, sorted_queue[j].player_id)

        if best_pair:
            self._queue = [e for e in self._queue
                          if e.player_id not in best_pair]

        return best_pair

    def get_queue_info(self) -> list[dict]:
        """Get information about the current queue."""
        return [
            {
                "player_id": e.player_id,
                "rating": e.rating,
                "wait_time": time.time() - e.queued_at,
            }
            for e in self._queue
        ]

    def process_match_result(self, winner_id: str, loser_id: str,
                             winner_rating: int, loser_rating: int,
                             draw: bool = False) -> MatchResult:
        """Process a match result and return rating changes."""
        new_winner, new_loser = self._elo.calculate_new_ratings(
            winner_rating, loser_rating, draw
        )

        return MatchResult(
            winner_id=winner_id,
            loser_id=loser_id,
            winner_rating_before=winner_rating,
            loser_rating_before=loser_rating,
            winner_rating_after=new_winner,
            loser_rating_after=new_loser,
        )
