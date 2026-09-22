"""Required actual GameEnv/SDL/OpenGL acceptance; never skipped or substituted."""
import ctypes
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from gfootball.engine_pool import ENGINE_POOL
from gfootball.frame_sync.graphical_input import InputBuffer
from gfootball.frame_sync.graphical_runtime import run_graphical
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_control import PAUSED, RUNNING
from gfootball.frame_sync.match_archive import engine_digest
from gfootball.frame_sync.match_identity import engine_identity, native_match_display, native_match_engine
from gfootball.frame_sync.protocol import pack_slot_input, default_slot_input
from gfootball.frame_sync.server_runtime import ServerSettings


def push_sdl_quit():
  """Use only the SDL2 already mapped into this process; do not initialize SDL."""
  if ctypes.sizeof(ctypes.c_void_p) != 8 or os.name != 'posix':
    raise RuntimeError('Native SDL acceptance requires Linux 64-bit')
  with open('/proc/self/maps', 'rb') as stream:
    data = stream.read(4 * 1024 * 1024 + 1)
  if len(data) > 4 * 1024 * 1024:
    raise RuntimeError('Mapping capacity exceeded')
  libraries = set()
  for line in data.splitlines():
    fields = line.split(None, 5)
    if len(fields) == 6 and fields[5].startswith(b'/'):
      name = os.fsdecode(fields[5])
      if Path(name).name.startswith(('libSDL2-2.0.so', 'libSDL2.so')):
        libraries.add(name)
  if len(libraries) != 1:
    raise RuntimeError('Expected one actual mapped SDL2 implementation')
  library = ctypes.CDLL(libraries.pop(), mode=os.RTLD_NOLOAD | os.RTLD_LOCAL)
  class Event(ctypes.Union):
    _fields_ = [('type', ctypes.c_uint32), ('padding', ctypes.c_uint8 * 56), ('alignment', ctypes.c_void_p)]
  if ctypes.sizeof(Event) != 56:
    raise RuntimeError('Unexpected SDL2 event ABI')
  library.SDL_PushEvent.argtypes = [ctypes.POINTER(Event)]
  library.SDL_PushEvent.restype = ctypes.c_int
  event = Event()
  event.type = 0x100  # SDL_QUIT; no keyboard-state or focus emulation.
  if library.SDL_PushEvent(ctypes.byref(event)) != 1:
    raise RuntimeError('SDL quit event was not admitted')


class GraphicalNativeTest(unittest.TestCase):
  def tearDown(self):
    self.assertEqual(ENGINE_POOL.stats()['live'], 0)

  def test_actual_local_pause_and_persistent_hud_do_not_change_physics(self):
    with LocalPlayer() as match:
      match.step()
      before = engine_digest(match.replica)
      paused = match.pause()
      self.assertEqual(paused.phase, PAUSED)
      with native_match_display(match._settings, engine_identity(match.replica)) as display:
        snapshot = match.replica.get_state('')
        display.set_state(snapshot)
        display.set_match_status('')
        display.render()
        plain = display.get_frame()
        text = 'Paused - K: resume - Esc: quit'
        display.set_match_status(text)
        display.render()
        caption = display.get_frame()
        self.assertNotEqual(plain, caption, 'Actual in-game HUD must change visible pixels')
        for _ in range(5):
          self.assertIsNone(match.step())
          display.set_state(snapshot)
          display.set_match_status(text)
          display.render()
          self.assertEqual(display.get_frame(), caption)
          self.assertEqual(engine_digest(display), before)
          self.assertEqual(engine_digest(match.replica), before)
        for invalid in ('x' * 97, 'pause\nresume', '\x00', '\u4e2d'):
          with self.assertRaises(ValueError):
            display.set_match_status(invalid)
          self.assertEqual(engine_digest(display), before)
        with self.assertRaises(RuntimeError):
          match.replica.set_match_status(text)
        display.set_match_status('')
        display.render()
        self.assertEqual(display.get_frame(), plain)
      self.assertEqual(match.server._call(lambda: engine_digest(match.server._runtime.env)), before)
      self.assertEqual(match.resume().phase, RUNNING)
      self.assertEqual(engine_digest(match.replica), before)
      self.assertEqual(match.step()['frame'], 1)

  def test_real_display_restores_lifecycle_and_renders_nonempty_rgb(self):
    with native_match_engine(ServerSettings()) as logic:
      identity = engine_identity(logic)
      with native_match_display(ServerSettings(), identity) as display:
        self.assertTrue(display.game_config.render)
        self.assertFalse(logic.game_config.render)
        for _ in range(3):
          logic.step_with_input(pack_slot_input(default_slot_input()))
          display.set_state(logic.get_state(''))
          expected = engine_digest(logic)
          self.assertEqual(engine_digest(display), expected)
          for _ in range(2):
            display.render()
            self.assertEqual(engine_digest(display), expected)
          frame = np.frombuffer(display.get_frame(), dtype=np.uint8)
          self.assertEqual(frame.size, 1280 * 720 * 3)
          self.assertGreater(float(frame.std()), 1.)
          self.assertGreater(float(frame.mean()), 1.)
          self.assertLess(float(frame.mean()), 254.)
          InputBuffer().feed(**display.poll_input())
        push_sdl_quit()
        self.assertTrue(display.poll_input()['quit'])

  def test_real_graphical_match_resume_and_replay(self):
    with tempfile.TemporaryDirectory() as directory:
      save, replay = str(Path(directory) / 'match.save'), str(Path(directory) / 'match.replay')
      played = run_graphical(max_frames=3, options=dict(save_path=save, record_path=replay))
      self.assertEqual(played['match']['frames'], 3)
      self.assertEqual(played['match']['pacing']['ticks'], 3)
      # 2026-09-13: v7 product loop uses a 20 ms grid; preserve the old expectation.
      # self.assertEqual(played['match']['pacing']['period_ns'], 100_000_000)
      self.assertEqual(played['match']['pacing']['period_ns'], 20_000_000)
      self.assertGreater(played['presentation']['render_count'], 0)
      replayed = run_graphical('replay', options=dict(path=replay))
      self.assertTrue(replayed['match']['verified'])
      self.assertEqual(replayed['match']['digest'], played['match']['last']['digest'])
      resumed = run_graphical(max_frames=2, options=dict(resume_path=save))
      self.assertEqual(resumed['match']['frames'], 2)

  def test_real_sdl_window_quit_stops_unbounded_match(self):
    result = run_graphical(on_ready=lambda info: push_sdl_quit())
    self.assertTrue(result['match']['closed'])
    self.assertEqual(result['match']['frames'], 0)

  def test_actual_skeleton_ball_camera_interpolation_changes_pixels_without_physics(self):
    from gfootball.frame_sync.protocol import SlotInput
    with native_match_engine(ServerSettings()) as logic:
      with native_match_display(ServerSettings(), engine_identity(logic)) as display:
        display.set_state(logic.get_state(''))
        display.render()
        distinct_interval = False
        for _ in range(4):
          display.save_render_state()
          for _ in range(5):
            logic.step_with_input(pack_slot_input(SlotInput(.8, .3, 4)))
          display.set_state(logic.get_state(''))
          expected = engine_digest(logic)
          images = []
          for alpha in (0., .5, 1.):
            display.render_interpolated(alpha)
            self.assertEqual(engine_digest(display), expected)
            frame = display.get_frame()
            self.assertEqual(len(frame), 1280 * 720 * 3)
            self.assertGreater(float(np.frombuffer(frame, dtype=np.uint8).std()), 1.)
            images.append(hashlib.sha256(frame).hexdigest())
          distinct_interval |= len(set(images)) == 3
        self.assertTrue(distinct_interval, 'Actual interpolated renders must contain different intermediate pixels')
        for alpha in (float('nan'), float('inf'), -.01, 1.01):
          with self.assertRaises(ValueError):
            display.render_interpolated(alpha)
        before = display.get_frame()
        display.save_render_state(from_display=True)
        display.render_interpolated(0.)
        self.assertEqual(display.get_frame(), before)
        self.assertEqual(engine_digest(display), expected)
        with self.assertRaises(RuntimeError):
          logic.save_render_state()


if __name__ == '__main__':
  unittest.main()
