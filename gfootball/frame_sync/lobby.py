"""
Lobby system for multiplayer matchmaking and room management.

This module provides:
- Room creation and management
- Player matching
- Game session coordination
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RoomStatus(Enum):
    """Room status states."""
    WAITING = "waiting"
    STARTING = "starting"
    IN_GAME = "in_game"
    FINISHED = "finished"


class PlayerStatus(Enum):
    """Player status in lobby."""
    IDLE = "idle"
    IN_ROOM = "in_room"
    IN_MATCH = "in_match"
    IN_GAME = "in_game"


@dataclass
class PlayerInfo:
    """Player information in lobby."""
    player_id: str
    name: str
    rating: int = 1000
    status: PlayerStatus = PlayerStatus.IDLE
    room_id: Optional[str] = None
    last_active: float = field(default_factory=time.time)


@dataclass
class RoomInfo:
    """Room information."""
    room_id: str
    host_id: str
    room_name: str
    status: RoomStatus = RoomStatus.WAITING
    max_players: int = 2
    players: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    settings: dict = field(default_factory=dict)


class Lobby:
    """Main lobby manager for multiplayer games."""

    def __init__(self):
        self._players: dict[str, PlayerInfo] = {}
        self._rooms: dict[str, RoomInfo] = {}
        self._match_queue: list[str] = []

    def register_player(self, player_id: str, name: str, rating: int = 1000) -> PlayerInfo:
        """Register a player in the lobby."""
        if player_id in self._players:
            self._players[player_id].last_active = time.time()
            return self._players[player_id]

        player = PlayerInfo(player_id=player_id, name=name, rating=rating)
        self._players[player_id] = player
        return player

    def unregister_player(self, player_id: str) -> None:
        """Remove a player from the lobby."""
        if player_id in self._players:
            player = self._players[player_id]
            if player.room_id:
                self.leave_room(player_id)
            if player_id in self._match_queue:
                self._match_queue.remove(player_id)
            del self._players[player_id]

    def create_room(self, host_id: str, room_name: str, max_players: int = 2,
                    settings: Optional[dict] = None) -> Optional[RoomInfo]:
        """Create a new room."""
        if host_id not in self._players:
            return None

        host = self._players[host_id]
        if host.room_id:
            return None

        room_id = str(uuid.uuid4())[:8]
        room = RoomInfo(
            room_id=room_id,
            host_id=host_id,
            room_name=room_name,
            max_players=max_players,
            settings=settings or {}
        )
        room.players.append(host_id)
        self._rooms[room_id] = room

        host.room_id = room_id
        host.status = PlayerStatus.IN_ROOM

        return room

    def join_room(self, player_id: str, room_id: str) -> bool:
        """Join an existing room."""
        if player_id not in self._players or room_id not in self._rooms:
            return False

        player = self._players[player_id]
        room = self._rooms[room_id]

        if player.room_id:
            return False
        if room.status != RoomStatus.WAITING:
            return False
        if len(room.players) >= room.max_players:
            return False

        room.players.append(player_id)
        player.room_id = room_id
        player.status = PlayerStatus.IN_ROOM
        return True

    def leave_room(self, player_id: str) -> bool:
        """Leave a room."""
        if player_id not in self._players:
            return False

        player = self._players[player_id]
        if not player.room_id:
            return False

        room_id = player.room_id
        if room_id not in self._rooms:
            player.room_id = None
            player.status = PlayerStatus.IDLE
            return False

        room = self._rooms[room_id]
        if player_id in room.players:
            room.players.remove(player_id)

        player.room_id = None
        player.status = PlayerStatus.IDLE

        if not room.players:
            del self._rooms[room_id]
        elif player_id == room.host_id:
            room.host_id = room.players[0]

        return True

    def get_room(self, room_id: str) -> Optional[RoomInfo]:
        """Get room information."""
        return self._rooms.get(room_id)

    def get_player(self, player_id: str) -> Optional[PlayerInfo]:
        """Get player information."""
        return self._players.get(player_id)

    def list_rooms(self, status: Optional[RoomStatus] = None) -> list[RoomInfo]:
        """List available rooms."""
        rooms = list(self._rooms.values())
        if status:
            rooms = [r for r in rooms if r.status == status]
        return rooms

    def join_match_queue(self, player_id: str) -> bool:
        """Join the matchmaking queue."""
        if player_id not in self._players:
            return False

        player = self._players[player_id]
        if player.room_id or player_id in self._match_queue:
            return False

        self._match_queue.append(player_id)
        player.status = PlayerStatus.IN_MATCH
        return True

    def leave_match_queue(self, player_id: str) -> bool:
        """Leave the matchmaking queue."""
        if player_id not in self._match_queue:
            return False

        self._match_queue.remove(player_id)
        player = self._players.get(player_id)
        if player:
            player.status = PlayerStatus.IDLE
        return True

    def find_match(self, player_id: str, max_rating_diff: int = 200) -> Optional[str]:
        """Find a matching player for the given player."""
        if player_id not in self._players:
            return None

        player = self._players[player_id]
        for other_id in self._match_queue:
            if other_id == player_id:
                continue

            other = self._players.get(other_id)
            if not other:
                continue

            rating_diff = abs(player.rating - other.rating)
            if rating_diff <= max_rating_diff:
                self._match_queue.remove(player_id)
                self._match_queue.remove(other_id)
                player.status = PlayerStatus.IN_ROOM
                other.status = PlayerStatus.IN_ROOM
                return other_id

        return None

    def get_match_queue_size(self) -> int:
        """Get the current match queue size."""
        return len(self._match_queue)

    def cleanup_stale_players(self, timeout_seconds: float = 300) -> int:
        """Remove players that haven't been active for a while."""
        now = time.time()
        stale = [
            pid for pid, p in self._players.items()
            if now - p.last_active > timeout_seconds
        ]
        for pid in stale:
            self.unregister_player(pid)
        return len(stale)
