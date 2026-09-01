"""
Replay system for recording and playback.

This module provides:
- Match recording
- Replay playback
- Highlight detection
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ReplayEventType(Enum):
    """Types of events in a replay."""
    GOAL = "goal"
    SAVE = "save"
    FOUL = "foul"
    CARD = "card"
    SUBSTITUTION = "substitution"
    MATCH_START = "match_start"
    MATCH_END = "match_end"


@dataclass
class ReplayEvent:
    """A single event in a replay."""
    event_type: ReplayEventType
    timestamp_ms: int
    frame_id: int
    player_id: Optional[str] = None
    team_id: Optional[str] = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "timestamp_ms": self.timestamp_ms,
            "frame_id": self.frame_id,
            "player_id": self.player_id,
            "team_id": self.team_id,
        }


@dataclass
class ReplayFrame:
    """A single frame of replay data."""
    frame_id: int
    ball_pos: tuple[float, float, float] = (0, 0, 0)
    player_positions: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    inputs: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "frame_id": self.frame_id,
            "ball_pos": self.ball_pos,
        }


@dataclass
class Replay:
    """A match replay."""
    replay_id: str
    match_id: str
    team_home: str
    team_away: str
    score_home: int = 0
    score_away: int = 0
    duration_ms: int = 0
    frames: list[ReplayFrame] = field(default_factory=list)
    events: list[ReplayEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_frame(self, frame: ReplayFrame) -> None:
        self.frames.append(frame)

    def add_event(self, event: ReplayEvent) -> None:
        self.events.append(event)

    def get_highlights(self) -> list[ReplayEvent]:
        """Get highlight events (goals, great saves, etc.)."""
        highlight_types = {ReplayEventType.GOAL, ReplayEventType.SAVE}
        return [e for e in self.events if e.event_type in highlight_types]

    def get_duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    def to_dict(self) -> dict:
        return {
            "replay_id": self.replay_id,
            "match_id": self.match_id,
            "team_home": self.team_home,
            "team_away": self.team_away,
            "score": f"{self.score_home}-{self.score_away}",
            "duration_seconds": self.get_duration_seconds(),
            "frames": len(self.frames),
            "events": len(self.events),
        }


class ReplayManager:
    """Manages replay recording and storage."""

    def __init__(self):
        self._replays: dict[str, Replay] = {}
        self._current_recording: Optional[Replay] = None
        self._max_replays: int = 50

    def start_recording(self, replay_id: str, match_id: str,
                       team_home: str, team_away: str) -> Replay:
        """Start recording a new replay."""
        if self._current_recording:
            self.stop_recording()

        replay = Replay(
            replay_id=replay_id,
            match_id=match_id,
            team_home=team_home,
            team_away=team_away,
        )
        self._current_recording = replay
        return replay

    def stop_recording(self) -> Optional[Replay]:
        """Stop current recording and save."""
        if not self._current_recording:
            return None

        replay = self._current_recording
        self._current_recording = None

        if len(self._replays) >= self._max_replays:
            oldest = min(self._replays.keys(), key=lambda k: self._replays[k].created_at)
            del self._replays[oldest]

        self._replays[replay.replay_id] = replay
        return replay

    def record_frame(self, frame: ReplayFrame) -> None:
        """Record a frame during active recording."""
        if self._current_recording:
            self._current_recording.add_frame(frame)

    def record_event(self, event: ReplayEvent) -> None:
        """Record an event during active recording."""
        if self._current_recording:
            self._current_recording.add_event(event)

    def set_score(self, home: int, away: int) -> None:
        """Set current score during recording."""
        if self._current_recording:
            self._current_recording.score_home = home
            self._current_recording.score_away = away

    def get_replay(self, replay_id: str) -> Optional[Replay]:
        """Get a stored replay."""
        return self._replays.get(replay_id)

    def delete_replay(self, replay_id: str) -> bool:
        """Delete a replay."""
        if replay_id in self._replays:
            del self._replays[replay_id]
            return True
        return False

    def list_replays(self) -> list[Replay]:
        """List all stored replays."""
        return list(self._replays.values())

    def get_latest_replays(self, count: int = 10) -> list[Replay]:
        """Get most recent replays."""
        replays = sorted(self._replays.values(), key=lambda r: r.created_at, reverse=True)
        return replays[:count]

    def is_recording(self) -> bool:
        return self._current_recording is not None

    def get_storage_info(self) -> dict:
        total_frames = sum(len(r.frames) for r in self._replays.values())
        return {
            "replay_count": len(self._replays),
            "total_frames": total_frames,
            "is_recording": self.is_recording(),
        }
