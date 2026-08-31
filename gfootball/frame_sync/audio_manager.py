"""
Audio management system for game sounds and music.

This module provides:
- Audio resource management
- Music playback control
- Sound effects playback
- Volume control
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable


class AudioCategory(Enum):
    """Audio categories for volume control."""
    MASTER = "master"
    MUSIC = "music"
    SFX = "sfx"
    COMMENTARY = "commentary"
    UI = "ui"
    AMBIENT = "ambient"


class AudioState(Enum):
    """Audio playback states."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    FADE_IN = "fade_in"
    FADE_OUT = "fade_out"


@dataclass
class AudioTrack:
    """Represents an audio track."""
    track_id: str
    file_path: str
    category: AudioCategory
    duration_ms: int = 0
    loop: bool = False
    volume: float = 1.0
    state: AudioState = AudioState.STOPPED
    position_ms: int = 0
    fade_in_ms: int = 0
    fade_out_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "file_path": self.file_path,
            "category": self.category.value,
            "duration_ms": self.duration_ms,
            "loop": self.loop,
            "volume": self.volume,
            "state": self.state.value,
            "position_ms": self.position_ms,
        }


@dataclass
class VolumeSettings:
    """Volume settings for each category."""
    master: float = 1.0
    music: float = 0.7
    sfx: float = 1.0
    commentary: float = 0.8
    ui: float = 0.9
    ambient: float = 0.6

    def get_volume(self, category: AudioCategory) -> float:
        """Get volume for a category."""
        volumes = {
            AudioCategory.MASTER: self.master,
            AudioCategory.MUSIC: self.music,
            AudioCategory.SFX: self.sfx,
            AudioCategory.COMMENTARY: self.commentary,
            AudioCategory.UI: self.ui,
            AudioCategory.AMBIENT: self.ambient,
        }
        return volumes.get(category, 1.0)

    def set_volume(self, category: AudioCategory, value: float) -> None:
        """Set volume for a category (0.0 to 1.0)."""
        value = max(0.0, min(1.0, value))
        if category == AudioCategory.MASTER:
            self.master = value
        elif category == AudioCategory.MUSIC:
            self.music = value
        elif category == AudioCategory.SFX:
            self.sfx = value
        elif category == AudioCategory.COMMENTARY:
            self.commentary = value
        elif category == AudioCategory.UI:
            self.ui = value
        elif category == AudioCategory.AMBIENT:
            self.ambient = value

    def to_dict(self) -> dict:
        return {
            "master": self.master,
            "music": self.music,
            "sfx": self.sfx,
            "commentary": self.commentary,
            "ui": self.ui,
            "ambient": self.ambient,
        }


class AudioManager:
    """Manages audio playback and resources."""

    def __init__(self):
        self._tracks: dict[str, AudioTrack] = {}
        self._volume = VolumeSettings()
        self._music_queue: list[str] = []
        self._current_music: Optional[str] = None
        self._sfx_pool: dict[str, list[str]] = {}
        self._callbacks: dict[str, Callable] = {}

    def load_track(self, track_id: str, file_path: str,
                   category: AudioCategory, duration_ms: int = 0,
                   loop: bool = False) -> AudioTrack:
        """Load an audio track."""
        track = AudioTrack(
            track_id=track_id,
            file_path=file_path,
            category=category,
            duration_ms=duration_ms,
            loop=loop,
        )
        self._tracks[track_id] = track
        return track

    def unload_track(self, track_id: str) -> bool:
        """Unload an audio track."""
        if track_id in self._tracks:
            del self._tracks[track_id]
            return True
        return False

    def play_music(self, track_id: str, fade_in_ms: int = 500) -> bool:
        """Play a music track."""
        track = self._tracks.get(track_id)
        if not track or track.category != AudioCategory.MUSIC:
            return False

        if self._current_music and self._current_music != track_id:
            self.stop_music(fade_out_ms=300)

        track.state = AudioState.PLAYING
        track.position_ms = 0
        track.fade_in_ms = fade_in_ms
        self._current_music = track_id
        return True

    def stop_music(self, fade_out_ms: int = 500) -> bool:
        """Stop the current music."""
        if not self._current_music:
            return False

        track = self._tracks.get(self._current_music)
        if track:
            track.state = AudioState.STOPPED
            track.position_ms = 0

        self._current_music = None
        return True

    def pause_music(self) -> bool:
        """Pause the current music."""
        if not self._current_music:
            return False

        track = self._tracks.get(self._current_music)
        if track:
            track.state = AudioState.PAUSED
        return True

    def resume_music(self) -> bool:
        """Resume paused music."""
        if not self._current_music:
            return False

        track = self._tracks.get(self._current_music)
        if track and track.state == AudioState.PAUSED:
            track.state = AudioState.PLAYING
            return True
        return False

    def queue_music(self, track_id: str) -> bool:
        """Add a track to the music queue."""
        if track_id in self._tracks:
            self._music_queue.append(track_id)
            return True
        return False

    def play_sfx(self, track_id: str) -> bool:
        """Play a sound effect."""
        track = self._tracks.get(track_id)
        if not track or track.category != AudioCategory.SFX:
            return False

        track.state = AudioState.PLAYING
        track.position_ms = 0
        return True

    def play_ui_sound(self, track_id: str) -> bool:
        """Play a UI sound."""
        track = self._tracks.get(track_id)
        if not track or track.category != AudioCategory.UI:
            return False

        track.state = AudioState.PLAYING
        track.position_ms = 0
        return True

    def set_volume(self, category: AudioCategory, volume: float) -> None:
        """Set volume for a category."""
        self._volume.set_volume(category, volume)

    def get_volume(self, category: AudioCategory) -> float:
        """Get volume for a category."""
        return self._volume.get_volume(category)

    def get_volume_settings(self) -> VolumeSettings:
        """Get all volume settings."""
        return self._volume

    def set_volume_settings(self, settings: VolumeSettings) -> None:
        """Set all volume settings."""
        self._volume = settings

    def get_playing_tracks(self) -> list[AudioTrack]:
        """Get all currently playing tracks."""
        return [t for t in self._tracks.values() if t.state == AudioState.PLAYING]

    def get_track(self, track_id: str) -> Optional[AudioTrack]:
        """Get a track by ID."""
        return self._tracks.get(track_id)

    def register_callback(self, event: str, callback: Callable) -> None:
        """Register a callback for audio events."""
        self._callbacks[event] = callback

    def update(self, delta_ms: int) -> None:
        """Update audio state (call each frame)."""
        for track in self._tracks.values():
            if track.state == AudioState.PLAYING:
                track.position_ms += delta_ms
                if track.fade_in_ms > 0:
                    track.fade_in_ms -= delta_ms
                if track.duration_ms > 0 and track.position_ms >= track.duration_ms:
                    if track.loop:
                        track.position_ms = 0
                    else:
                        track.state = AudioState.STOPPED
                        if "on_track_end" in self._callbacks:
                            self._callbacks["on_track_end"](track.track_id)

    def get_status(self) -> dict:
        """Get audio system status."""
        return {
            "current_music": self._current_music,
            "music_queue_size": len(self._music_queue),
            "playing_tracks": len(self.get_playing_tracks()),
            "volume": self._volume.to_dict(),
        }
