"""
Save/load system for game progress and settings.

This module provides:
- Game progress saving
- Settings persistence
- Data serialization
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SaveType(Enum):
    """Types of save data."""
    PROGRESS = "progress"
    SETTINGS = "settings"
    REPLAY = "replay"
    CUSTOM = "custom"


@dataclass
class SaveSlot:
    """A save slot."""
    slot_id: str
    name: str
    save_type: SaveType
    data: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "name": self.name,
            "save_type": self.save_type.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "size_bytes": self.size_bytes,
        }


class SaveManager:
    """Manages save/load operations."""

    def __init__(self):
        self._slots: dict[str, SaveSlot] = {}
        self._max_slots: int = 10

    def create_slot(self, slot_id: str, name: str,
                    save_type: SaveType = SaveType.CUSTOM) -> SaveSlot:
        """Create a new save slot."""
        if len(self._slots) >= self._max_slots:
            raise ValueError(f"Maximum save slots ({self._max_slots}) reached")

        slot = SaveSlot(slot_id=slot_id, name=name, save_type=save_type)
        self._slots[slot_id] = slot
        return slot

    def save(self, slot_id: str, data: dict, name: Optional[str] = None) -> bool:
        """Save data to a slot."""
        slot = self._slots.get(slot_id)
        if not slot:
            return False

        slot.data = data.copy()
        slot.updated_at = time.time()
        slot.size_bytes = len(json.dumps(data).encode())
        if name:
            slot.name = name

        return True

    def load(self, slot_id: str) -> Optional[dict]:
        """Load data from a slot."""
        slot = self._slots.get(slot_id)
        if not slot:
            return None
        return slot.data.copy()

    def delete_slot(self, slot_id: str) -> bool:
        """Delete a save slot."""
        if slot_id in self._slots:
            del self._slots[slot_id]
            return True
        return False

    def get_slot(self, slot_id: str) -> Optional[SaveSlot]:
        """Get slot info."""
        return self._slots.get(slot_id)

    def list_slots(self, save_type: Optional[SaveType] = None) -> list[SaveSlot]:
        """List all save slots."""
        slots = list(self._slots.values())
        if save_type:
            slots = [s for s in slots if s.save_type == save_type]
        return slots

    def export_slot(self, slot_id: str) -> Optional[str]:
        """Export a slot as JSON string."""
        slot = self._slots.get(slot_id)
        if not slot:
            return None
        return json.dumps(slot.to_dict() | {"data": slot.data}, indent=2)

    def import_slot(self, json_str: str) -> Optional[SaveSlot]:
        """Import a slot from JSON string."""
        try:
            data = json.loads(json_str)
            slot = SaveSlot(
                slot_id=data["slot_id"],
                name=data["name"],
                save_type=SaveType(data["save_type"]),
                data=data.get("data", {}),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
            )
            self._slots[slot.slot_id] = slot
            return slot
        except (json.JSONDecodeError, KeyError):
            return None

    def get_storage_usage(self) -> dict:
        """Get storage usage statistics."""
        total_size = sum(s.size_bytes for s in self._slots.values())
        return {
            "slots_used": len(self._slots),
            "slots_max": self._max_slots,
            "total_bytes": total_size,
            "total_kb": total_size / 1024,
        }


class GameProgress:
    """Manages game progress data."""

    def __init__(self):
        self._progress: dict[str, Any] = {
            "career": {
                "current_team": None,
                "season": 0,
                "money": 0,
                "trophies": [],
            },
            "unlocks": {
                "teams": ["real_madrid", "barcelona"],
                "stadiums": ["santiago_bernabeu"],
                "challenges": [],
            },
            "stats": {
                "total_matches": 0,
                "total_goals": 0,
                "total_wins": 0,
                "playtime_seconds": 0,
            },
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a progress value by key path (e.g., 'career.money')."""
        keys = key.split(".")
        value = self._progress
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set a progress value by key path."""
        keys = key.split(".")
        target = self._progress
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def update_stats(self, match_played: bool = False, goal_scored: bool = False,
                    won: bool = False, playtime_seconds: int = 0) -> None:
        """Update game statistics."""
        if match_played:
            self._progress["stats"]["total_matches"] += 1
        if goal_scored:
            self._progress["stats"]["total_goals"] += 1
        if won:
            self._progress["stats"]["total_wins"] += 1
        self._progress["stats"]["playtime_seconds"] += playtime_seconds

    def unlock_team(self, team_id: str) -> bool:
        """Unlock a team."""
        if team_id not in self._progress["unlocks"]["teams"]:
            self._progress["unlocks"]["teams"].append(team_id)
            return True
        return False

    def is_team_unlocked(self, team_id: str) -> bool:
        """Check if a team is unlocked."""
        return team_id in self._progress["unlocks"]["teams"]

    def to_dict(self) -> dict:
        """Get full progress as dictionary."""
        return self._progress.copy()

    def from_dict(self, data: dict) -> None:
        """Load progress from dictionary."""
        self._progress = data
