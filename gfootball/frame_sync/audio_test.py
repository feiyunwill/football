"""
Tests for the audio and commentary systems.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from audio_manager import AudioManager, AudioCategory, AudioState, VolumeSettings
from commentary import CommentarySystem, CommentaryEvent, CommentaryContext


class TestAudioManager(unittest.TestCase):
    """Test AudioManager class."""

    def setUp(self):
        self.audio = AudioManager()

    def test_load_track(self):
        track = self.audio.load_track("music1", "/path/to/music.mp3", AudioCategory.MUSIC)
        self.assertEqual(track.track_id, "music1")
        self.assertEqual(track.category, AudioCategory.MUSIC)

    def test_play_music(self):
        self.audio.load_track("music1", "/path/to/music.mp3", AudioCategory.MUSIC)
        result = self.audio.play_music("music1")
        self.assertTrue(result)
        self.assertEqual(self.audio._current_music, "music1")

    def test_stop_music(self):
        self.audio.load_track("music1", "/path/to/music.mp3", AudioCategory.MUSIC)
        self.audio.play_music("music1")
        result = self.audio.stop_music()
        self.assertTrue(result)
        self.assertIsNone(self.audio._current_music)

    def test_volume_control(self):
        self.audio.set_volume(AudioCategory.MUSIC, 0.5)
        self.assertEqual(self.audio.get_volume(AudioCategory.MUSIC), 0.5)

    def test_play_sfx(self):
        self.audio.load_track("sfx1", "/path/to/sfx.wav", AudioCategory.SFX)
        result = self.audio.play_sfx("sfx1")
        self.assertTrue(result)

    def test_get_playing_tracks(self):
        self.audio.load_track("music1", "/path/to/music.mp3", AudioCategory.MUSIC)
        self.audio.load_track("sfx1", "/path/to/sfx.wav", AudioCategory.SFX)
        self.audio.play_music("music1")
        self.audio.play_sfx("sfx1")
        playing = self.audio.get_playing_tracks()
        self.assertEqual(len(playing), 2)


class TestVolumeSettings(unittest.TestCase):
    """Test VolumeSettings class."""

    def test_default_volumes(self):
        settings = VolumeSettings()
        self.assertEqual(settings.master, 1.0)
        self.assertEqual(settings.music, 0.7)

    def test_set_volume(self):
        settings = VolumeSettings()
        settings.set_volume(AudioCategory.MUSIC, 0.3)
        self.assertEqual(settings.music, 0.3)

    def test_clamp_volume(self):
        settings = VolumeSettings()
        settings.set_volume(AudioCategory.MUSIC, 1.5)
        self.assertEqual(settings.music, 1.0)
        settings.set_volume(AudioCategory.MUSIC, -0.5)
        self.assertEqual(settings.music, 0.0)


class TestCommentarySystem(unittest.TestCase):
    """Test CommentarySystem class."""

    def setUp(self):
        self.commentary = CommentarySystem()

    def test_trigger_goal(self):
        context = CommentaryContext(event=CommentaryEvent.GOAL, minute=45)
        text = self.commentary.trigger_event(context)
        self.assertIsNotNone(text)
        self.assertIn("GOAL", text.upper() or "goal" in text.lower())

    def test_trigger_miss(self):
        context = CommentaryContext(event=CommentaryEvent.MISS, minute=30)
        text = self.commentary.trigger_event(context)
        self.assertIsNotNone(text)

    def test_disabled_commentary(self):
        self.commentary.set_enabled(False)
        context = CommentaryContext(event=CommentaryEvent.GOAL, minute=45)
        text = self.commentary.trigger_event(context)
        self.assertIsNone(text)

    def test_history(self):
        context = CommentaryContext(event=CommentaryEvent.GOAL, minute=45)
        self.commentary.trigger_event(context)
        self.commentary.trigger_event(context)
        history = self.commentary.get_history(limit=5)
        self.assertEqual(len(history), 2)

    def test_database_stats(self):
        db = self.commentary.get_database()
        self.assertGreater(db.get_line_count(), 0)
        self.assertGreater(db.get_event_count(CommentaryEvent.GOAL), 0)


if __name__ == "__main__":
    unittest.main()
