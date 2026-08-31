"""
Chat system for lobby and in-game communication.

This module provides:
- Room-based chat
- Direct messages
- Chat history
- Message filtering
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageType(Enum):
    """Chat message types."""
    TEXT = "text"
    SYSTEM = "system"
    EMOTE = "emote"
    COMMAND = "command"


@dataclass
class ChatMessage:
    """A chat message."""
    message_id: str
    sender_id: str
    sender_name: str
    content: str
    message_type: MessageType = MessageType.TEXT
    room_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    edited: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "message_type": self.message_type.value,
            "room_id": self.room_id,
            "timestamp": self.timestamp,
            "edited": self.edited,
        }


class ChatFilter:
    """Simple chat message filter."""

    def __init__(self):
        self._blocked_words: set[str] = set()
        self._blocked_patterns: list[str] = []

    def add_blocked_word(self, word: str) -> None:
        """Add a word to the block list."""
        self._blocked_words.add(word.lower())

    def add_blocked_pattern(self, pattern: str) -> None:
        """Add a regex pattern to the block list."""
        self._blocked_patterns.append(pattern)

    def is_allowed(self, message: str) -> bool:
        """Check if a message is allowed."""
        msg_lower = message.lower()

        for word in self._blocked_words:
            if word in msg_lower:
                return False

        return True

    def filter_message(self, message: str) -> str:
        """Filter a message, returning cleaned version."""
        if not self.is_allowed(message):
            return "[message filtered]"
        return message


class ChatRoom:
    """A chat room for a specific game room or channel."""

    def __init__(self, room_id: str, max_history: int = 100):
        self.room_id = room_id
        self._members: set[str] = set()
        self._history: list[ChatMessage] = []
        self._max_history = max_history
        self._message_counter = 0

    def join(self, player_id: str) -> None:
        """Add a player to the chat room."""
        self._members.add(player_id)

    def leave(self, player_id: str) -> None:
        """Remove a player from the chat room."""
        self._members.discard(player_id)

    def get_members(self) -> set[str]:
        """Get all members in the chat room."""
        return self._members.copy()

    def add_message(self, sender_id: str, sender_name: str,
                    content: str, message_type: MessageType = MessageType.TEXT,
                    chat_filter: Optional[ChatFilter] = None) -> ChatMessage:
        """Add a message to the chat room."""
        if chat_filter:
            content = chat_filter.filter_message(content)

        self._message_counter += 1
        message = ChatMessage(
            message_id=f"{self.room_id}_{self._message_counter}",
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            message_type=message_type,
            room_id=self.room_id,
        )

        self._history.append(message)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return message

    def get_history(self, limit: int = 50) -> list[ChatMessage]:
        """Get recent chat history."""
        return self._history[-limit:]

    def get_history_since(self, timestamp: float) -> list[ChatMessage]:
        """Get messages since a specific timestamp."""
        return [m for m in self._history if m.timestamp > timestamp]


class ChatManager:
    """Manager for all chat rooms and direct messages."""

    def __init__(self):
        self._rooms: dict[str, ChatRoom] = {}
        self._direct_messages: dict[str, list[ChatMessage]] = {}
        self._filter = ChatFilter()
        self._dm_counter = 0

    def create_room(self, room_id: str) -> ChatRoom:
        """Create a new chat room."""
        if room_id not in self._rooms:
            self._rooms[room_id] = ChatRoom(room_id)
        return self._rooms[room_id]

    def delete_room(self, room_id: str) -> bool:
        """Delete a chat room."""
        if room_id in self._rooms:
            del self._rooms[room_id]
            return True
        return False

    def get_room(self, room_id: str) -> Optional[ChatRoom]:
        """Get a chat room."""
        return self._rooms.get(room_id)

    def send_to_room(self, room_id: str, sender_id: str, sender_name: str,
                     content: str, message_type: MessageType = MessageType.TEXT
                     ) -> Optional[ChatMessage]:
        """Send a message to a chat room."""
        room = self._rooms.get(room_id)
        if not room:
            return None

        if sender_id not in room.get_members():
            return None

        return room.add_message(
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            message_type=message_type,
            chat_filter=self._filter,
        )

    def send_direct_message(self, sender_id: str, sender_name: str,
                            recipient_id: str, content: str) -> ChatMessage:
        """Send a direct message to another player."""
        self._dm_counter += 1
        message = ChatMessage(
            message_id=f"dm_{self._dm_counter}",
            sender_id=sender_id,
            sender_name=sender_name,
            content=self._filter.filter_message(content),
            message_type=MessageType.TEXT,
        )

        dm_key = self._get_dm_key(sender_id, recipient_id)
        if dm_key not in self._direct_messages:
            self._direct_messages[dm_key] = []
        self._direct_messages[dm_key].append(message)

        return message

    def get_direct_messages(self, player1_id: str, player2_id: str,
                            limit: int = 50) -> list[ChatMessage]:
        """Get direct message history between two players."""
        dm_key = self._get_dm_key(player1_id, player2_id)
        messages = self._direct_messages.get(dm_key, [])
        return messages[-limit:]

    def _get_dm_key(self, player1_id: str, player2_id: str) -> str:
        """Generate a consistent key for DM conversation."""
        return "_".join(sorted([player1_id, player2_id]))

    def add_blocked_word(self, word: str) -> None:
        """Add a word to the chat filter."""
        self._filter.add_blocked_word(word)

    def add_blocked_pattern(self, pattern: str) -> None:
        """Add a pattern to the chat filter."""
        self._filter.add_blocked_pattern(pattern)

    def get_room_count(self) -> int:
        """Get total number of chat rooms."""
        return len(self._rooms)
