"""
Commentary system for match events.

This module provides:
- Commentary event triggering
- Commentary line management
- Multi-language support
"""

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CommentaryEvent(Enum):
    """Types of commentary events."""
    GOAL = "goal"
    MISS = "miss"
    SAVE = "save"
    FOUL = "foul"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    PENALTY = "penalty"
    FREE_KICK = "free_kick"
    CORNER = "corner"
    OFFSIDE = "offside"
    SUBSTITUTION = "substitution"
    HALF_TIME = "half_time"
    FULL_TIME = "full_time"
    EXTRA_TIME = "extra_time"
    PENALTY_SHOOTOUT = "penalty_shootout"
    MATCH_START = "match_start"
    NEAR_MISS = "near_miss"
    GREAT_SAVE = "great_save"
    TACKLE = "tackle"
    CROSS = "cross"


@dataclass
class CommentaryLine:
    """A single commentary line."""
    line_id: str
    event: CommentaryEvent
    text: str
    language: str = "en"
    priority: int = 0
    cooldown_ms: int = 5000
    last_used: float = 0

    def can_use(self) -> bool:
        """Check if this line can be used (cooldown check)."""
        return time.time() - (self.last_used / 1000) > (self.cooldown_ms / 1000)

    def mark_used(self) -> None:
        """Mark this line as used."""
        self.last_used = time.time() * 1000


@dataclass
class CommentaryContext:
    """Context for generating commentary."""
    event: CommentaryEvent
    minute: int = 0
    score_left: int = 0
    score_right: int = 0
    player_name: Optional[str] = None
    team_name: Optional[str] = None
    is_home_team: bool = True
    is_important: bool = False


class CommentaryDatabase:
    """Database of commentary lines."""

    def __init__(self):
        self._lines: dict[str, CommentaryLine] = {}
        self._by_event: dict[CommentaryEvent, list[CommentaryLine]] = {}
        self._counter = 0

    def add_line(self, event: CommentaryEvent, text: str,
                 language: str = "en", priority: int = 0,
                 cooldown_ms: int = 5000) -> CommentaryLine:
        """Add a commentary line."""
        self._counter += 1
        line = CommentaryLine(
            line_id=f"line_{self._counter}",
            event=event,
            text=text,
            language=language,
            priority=priority,
            cooldown_ms=cooldown_ms,
        )
        self._lines[line.line_id] = line

        if event not in self._by_event:
            self._by_event[event] = []
        self._by_event[event].append(line)

        return line

    def get_lines_for_event(self, event: CommentaryEvent,
                           language: str = "en") -> list[CommentaryLine]:
        """Get available lines for an event."""
        lines = self._by_event.get(event, [])
        return [l for l in lines if l.language == language and l.can_use()]

    def get_random_line(self, event: CommentaryEvent,
                       language: str = "en") -> Optional[CommentaryLine]:
        """Get a random available line for an event."""
        available = self.get_lines_for_event(event, language)
        if not available:
            return None
        return random.choice(available)

    def get_line_count(self) -> int:
        """Get total number of lines."""
        return len(self._lines)

    def get_event_count(self, event: CommentaryEvent) -> int:
        """Get number of lines for a specific event."""
        return len(self._by_event.get(event, []))


class CommentarySystem:
    """Main commentary system."""

    def __init__(self):
        self._database = CommentaryDatabase()
        self._current_commentary: Optional[str] = None
        self._commentary_history: list[tuple[float, str]] = []
        self._enabled = True
        self._language = "en"

        self._load_default_lines()

    def _load_default_lines(self) -> None:
        """Load default commentary lines."""
        # Goals
        self._database.add_line(CommentaryEvent.GOAL, "GOAL! What a fantastic finish!", priority=10)
        self._database.add_line(CommentaryEvent.GOAL, "And it's in the back of the net!", priority=9)
        self._database.add_line(CommentaryEvent.GOAL, "What a strike! Beautiful goal!", priority=8)
        self._database.add_line(CommentaryEvent.GOAL, "The keeper had no chance there!", priority=7)

        # Misses
        self._database.add_line(CommentaryEvent.MISS, "Oh, he's put it wide!", priority=8)
        self._database.add_line(CommentaryEvent.MISS, "That was a great chance, but it's gone over!", priority=7)
        self._database.add_line(CommentaryEvent.NEAR_MISS, "So close! Just inches away!", priority=9)

        # Saves
        self._database.add_line(CommentaryEvent.SAVE, "Great save by the goalkeeper!", priority=8)
        self._database.add_line(CommentaryEvent.GREAT_SAVE, "What a save! Absolutely brilliant!", priority=10)

        # Cards
        self._database.add_line(CommentaryEvent.YELLOW_CARD, "That's a yellow card from the referee.", priority=7)
        self._database.add_line(CommentaryEvent.RED_CARD, "It's a red card! He's been sent off!", priority=10)

        # Fouls
        self._database.add_line(CommentaryEvent.FOUL, "That's a foul, referee signals a free kick.", priority=6)

        # Set pieces
        self._database.add_line(CommentaryEvent.PENALTY, "It's a penalty! Big moment in the match!", priority=10)
        self._database.add_line(CommentaryEvent.FREE_KICK, "Free kick in a dangerous position.", priority=7)
        self._database.add_line(CommentaryEvent.CORNER, "Corner kick coming up.", priority=5)

        # Match events
        self._database.add_line(CommentaryEvent.HALF_TIME, "And that's half time!", priority=9)
        self._database.add_line(CommentaryEvent.FULL_TIME, "Full time! What a match!", priority=10)
        self._database.add_line(CommentaryEvent.MATCH_START, "And we're underway!", priority=9)

        # Gameplay
        self._database.add_line(CommentaryEvent.TACKLE, "Good tackling there.", priority=5)
        self._database.add_line(CommentaryEvent.CROSS, "Looking for the cross...", priority=5)
        self._database.add_line(CommentaryEvent.OFFSIDE, "The flag is up for offside.", priority=6)

    def trigger_event(self, context: CommentaryContext) -> Optional[str]:
        """Trigger a commentary event and return the commentary text."""
        if not self._enabled:
            return None

        line = self._database.get_random_line(context.event, self._language)
        if not line:
            return None

        text = self._format_line(line.text, context)
        line.mark_used()

        self._current_commentary = text
        self._commentary_history.append((time.time(), text))

        if len(self._commentary_history) > 100:
            self._commentary_history = self._commentary_history[-100:]

        return text

    def _format_line(self, template: str, context: CommentaryContext) -> str:
        """Format a commentary line with context."""
        text = template
        if context.player_name:
            text = text.replace("{player}", context.player_name)
        if context.team_name:
            text = text.replace("{team}", context.team_name)
        return text

    def set_language(self, language: str) -> None:
        """Set commentary language."""
        self._language = language

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable commentary."""
        self._enabled = enabled

    def get_current_commentary(self) -> Optional[str]:
        """Get the current commentary text."""
        return self._current_commentary

    def get_history(self, limit: int = 10) -> list[str]:
        """Get recent commentary history."""
        return [text for _, text in self._commentary_history[-limit:]]

    def get_database(self) -> CommentaryDatabase:
        """Get the commentary database."""
        return self._database

    def get_status(self) -> dict:
        """Get commentary system status."""
        return {
            "enabled": self._enabled,
            "language": self._language,
            "total_lines": self._database.get_line_count(),
            "current_commentary": self._current_commentary,
        }
