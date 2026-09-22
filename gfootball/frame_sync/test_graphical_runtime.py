"""Real sockets, archives and owner scheduling; explicit non-native display oracle."""
from collections import deque
import contextlib
import io
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from gfootball.engine_pool import EnginePool, EngineKey
from gfootball.owned_engine import create_owned_engine
from gfootball.frame_sync.graphical_runtime import run_graphical
from gfootball.frame_sync.match_archive import playback
from gfootball.frame_sync.match_lifecycle import MatchLifecycleEngine
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.test_match_lifecycle import TerminalOracle


class DisplayOracle(TerminalOracle):
  def __init__(self, settings):
    super().__init__(settings)
    self.drawn = deque(maxlen=64)
    self.polls = 0
    self.input = dict(keys=('w', 'z'))
    self.render_error = self.close_error = False
    self.visible_pose = self.previous_pose = 0.0
    self.interpolation_count = 0
    self.statuses = deque(maxlen=32)

  def set_match_status(self, text):
    self.check()
    if len(text) > 96 or any(not 32 <= ord(c) <= 126 for c in text):
      raise ValueError('Invalid HUD status')
    self.statuses.append(text)

  def render(self):
    self.check()
    if self.render_error and self.frames > 0:
      raise RuntimeError('Injected display failure')
    self.drawn.append((self.frames, self.state))
    self.visible_pose = float(self.frames)

  def save_render_state(self, from_display=False):
    self.check()
    self.previous_pose = self.visible_pose if from_display else float(self.frames)

  def render_interpolated(self, alpha):
    self.render()
    self.visible_pose = self.previous_pose * (1 - alpha) + self.frames * alpha
    self.interpolation_count += 1

  def poll_input(self):
    self.check()
    self.polls += 1
    return dict(self.input)

  def close(self):
    super().close()
    if self.close_error:
      raise RuntimeError('Injected display cleanup failure')


class GraphicalRuntimeTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.pool = EnginePool(max_live=4, idle_headless=0, idle_rendering=0)
    self.key = EngineKey.current(1280, 720)
    self.engines, self.workers, self.errors = [], [], []
    self.display = None

  def tearDown(self):
    for thread in self.workers:
      thread.join(8)
      self.assertFalse(thread.is_alive())
    self.assertFalse(self.errors)
    self.pool.close()
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertTrue(all(env.closed == 1 for env in self.engines), [env.closed for env in self.engines])
    self.assertFalse(any(t.name == 'football-graphical-logic' for t in threading.enumerate()))

  def factory(self, settings):
    def initialize():
      env = TerminalOracle(settings)
      self.engines.append(env)
      return MatchLifecycleEngine(env, normal_mode=0, done_state=1)
    return create_owned_engine(self.key, initialize, pool=self.pool)

  def display_factory(self, settings, identity):
    self.assertIs(threading.current_thread(), threading.main_thread())
    def initialize():
      self.display = DisplayOracle(settings)
      self.engines.append(self.display)
      return MatchLifecycleEngine(self.display, normal_mode=0, done_state=1)
    return create_owned_engine(self.key, initialize, rendering=True, pool=self.pool)

  def run_match(self, mode='local', **kwargs):
    # 2026-09-10: assert the actual coordinator selected interpolation and settled its final pose.
    # return run_graphical(mode, engine_factory=self.factory, display_factory=self.display_factory, **kwargs)
    result = run_graphical(mode, engine_factory=self.factory, display_factory=self.display_factory, **kwargs)
    self.assertTrue(result['presentation']['interpolation'])
    self.assertEqual(self.display.visible_pose, float(self.display.frames))
    return result

  def spawn(self, target):
    def owned():
      try:
        target()
      except BaseException as error:
        self.errors.append(error)
    thread = threading.Thread(target=owned, name='football-graphical-test-peer')
    self.workers.append(thread)
    thread.start()

  def test_local_natural_end_display_save_resume_and_verified_replay(self):
    replay, save = str(self.root / 'match.replay'), str(self.root / 'match.save')
    result = self.run_match(max_frames=100, options=dict(record_path=replay, save_path=save))
    self.assertEqual(result['match']['frames'], 5)
    self.assertEqual(self.display.drawn[-1], (5, 1))
    self.assertGreater(result['presentation']['render_count'], result['presentation']['restore_count'])
    self.assertTrue(all(env.owner is not threading.main_thread() for env in self.engines if env is not self.display))
    expected = playback(replay, engine_factory=self.factory)
    result = self.run_match(options=dict(resume_path=save), max_frames=10)
    self.assertEqual(result['match']['frames'], 0)
    self.assertEqual(self.display.drawn[-1], (5, 1))
    result = self.run_match('replay', options=dict(path=replay))
    self.assertEqual(result['match'], expected)
    self.assertEqual(self.display.drawn[-1], (5, 1))

  def test_window_quit_before_first_input_finalizes_zero_frame_replay(self):
    replay = str(self.root / 'empty.replay')
    result = self.run_match(options=dict(record_path=replay),
                           on_ready=lambda info: setattr(self.display, 'input', dict(quit=True)))
    self.assertEqual(result['match']['frames'], 0)
    self.assertTrue(playback(replay, engine_factory=self.factory)['verified'])
    result = self.run_match('replay', options=dict(path=replay))
    self.assertTrue(result['match']['verified'])
    self.assertEqual(result['match']['frames'], 0)

  def test_replay_window_cancellation_never_claims_full_verification(self):
    replay = str(self.root / 'match.replay')
    self.run_match(max_frames=3, options=dict(record_path=replay))
    before = Path(replay).read_bytes()
    result = self.run_match('replay', options=dict(path=replay),
                           on_ready=lambda info: setattr(self.display, 'input', dict(quit=True)))
    self.assertTrue(result['match']['cancelled'])
    self.assertFalse(result['match']['verified'])
    self.assertEqual(Path(replay).read_bytes(), before)

  def test_mismatch_rejected_before_display_restore_and_closes_worker(self):
    def display(settings, identity):
      env = self.display_factory(settings, identity)
      self.display.identity['resources'] = 'c' * 64
      return env
    with self.assertRaisesRegex(ValueError, 'incompatible'):
      run_graphical(engine_factory=self.factory, display_factory=display, max_frames=1)
    self.assertEqual(self.display.restores, 0)

  def test_render_and_cleanup_failures_preserve_primary_and_previous_output(self):
    path = self.root / 'match.replay'
    path.write_bytes(b'previous output')
    def ready(info):
      self.display.render_error = self.display.close_error = True
    with self.assertRaisesRegex(RuntimeError, 'Injected display failure'):
      self.run_match(options=dict(record_path=str(path)), on_ready=ready)
    self.assertEqual(path.read_bytes(), b'previous output')

  def test_input_failure_is_propagated_and_all_owners_close(self):
    with self.assertRaisesRegex(ValueError, 'Unknown input key'):
      self.run_match(max_frames=2, on_ready=lambda info: setattr(self.display, 'input', dict(keys=('unknown',))))

  def test_startup_failure_does_not_allocate_display(self):
    def failed(settings):
      raise RuntimeError('Injected startup failure')
    with self.assertRaisesRegex(RuntimeError, 'Injected startup failure'):
      run_graphical(engine_factory=failed, display_factory=self.display_factory, max_frames=1)
    self.assertIsNone(self.display)

  def host_case(self, transport):
    results = []
    def ready(info):
      def join():
        with NetworkPlayer(port=info['port'], transport=transport, engine_factory=self.factory) as peer:
          results.append(peer.run(100))
      self.spawn(join)
    result = self.run_match('host', max_frames=100, options=dict(left=1, right=1, transport=transport), on_ready=ready)
    for thread in self.workers:
      thread.join(8)
    self.assertEqual(result['match']['frame'], 5)
    self.assertTrue(result['match']['end_acknowledged'])
    self.assertEqual(self.display.drawn[-1], (5, 1))
    self.assertTrue(results[0]['ended'])

  def test_tcp_graphical_host_and_real_join(self):
    self.host_case('tcp')

  def test_udp_graphical_host_and_real_join(self):
    self.host_case('udp')

  def join_case(self, transport):
    port = queue.Queue(maxsize=1)
    results = []
    def host():
      with HostedMatch(transport=transport, engine_factory=self.factory) as match:
        port.put_nowait(match.port)
        results.append(match.run(100))
    self.spawn(host)
    result = self.run_match('join', max_frames=100, options=dict(port=port.get(timeout=4), transport=transport))
    for thread in self.workers:
      thread.join(8)
    self.assertTrue(result['match']['ended'])
    self.assertEqual(self.display.drawn[-1], (5, 1))
    self.assertTrue(results[0]['end_acknowledged'])

  def test_tcp_graphical_join_and_real_host(self):
    self.join_case('tcp')

  def test_udp_graphical_join_and_real_host(self):
    self.join_case('udp')

  def test_main_thread_required_before_allocating_any_engine(self):
    caught = []
    def run():
      try:
        self.run_match(max_frames=1)
      except RuntimeError as error:
        caught.append(str(error))
    self.spawn(run)
    self.workers[-1].join(3)
    self.assertEqual(caught, ['Graphical matches require the main thread'])
    self.assertFalse(self.engines)

  def test_menu_graphics_local_resume_replay_use_actual_files_and_restore_scope(self):
    from gfootball.frame_sync import main_menu, graphical_runtime
    save, replay = str(self.root / 'menu.save'), str(self.root / 'menu.replay')
    original = graphical_runtime.run_graphical
    def graphical(*args, **kwargs):
      return original(*args, engine_factory=self.factory, display_factory=self.display_factory, **kwargs)
    settings = str(self.root / 'settings.save')
    previous = main_menu._graphics
    with mock.patch.object(graphical_runtime, 'run_graphical', graphical), contextlib.redirect_stdout(io.StringIO()):
      with mock.patch.object(sys, 'argv', ['menu', '--graphics', '--mode', 'local', '--settings-file', settings]), mock.patch(
          'builtins.input', side_effect=['', '', '', '', replay, save, '2']):
        self.assertEqual(main_menu.main(), 0)
      self.assertEqual(main_menu._graphics, previous)
      with mock.patch.object(sys, 'argv', ['menu', '--graphics', '--mode', 'resume', '--settings-file', settings]), mock.patch(
          'builtins.input', side_effect=[save, '-', '1']):
        self.assertEqual(main_menu.main(), 0)
      with mock.patch.object(sys, 'argv', ['menu', '--graphics', '--mode', 'replay', '--settings-file', settings]), mock.patch(
          'builtins.input', return_value=replay):
        self.assertEqual(main_menu.main(), 0)
      with mock.patch.object(sys, 'argv', ['menu', '--graphics', '--mode', 'local', '--settings-file', settings]), mock.patch(
          'builtins.input', side_effect=['', 'invalid number']):
        self.assertEqual(main_menu.main(), 1)
    self.assertEqual(main_menu._graphics, previous)
    self.assertEqual(playback(replay, engine_factory=self.factory)['frames'], 2)
    self.assertTrue(Path(save).is_file())

  def test_display_identity_allows_only_the_original_render_role(self):
    from gfootball.frame_sync.match_identity import NativeMatchEngine
    from gfootball.frame_sync.server_runtime import ServerSettings
    env = TerminalOracle(ServerSettings())
    # 2026-09-13: adapter fixture represents negotiated v7 physics.
    # env.game_config = SimpleNamespace(render=True, physics_steps_per_frame=10,
    env.game_config = SimpleNamespace(render=True, physics_steps_per_frame=2,
                                     render_resolution_x=1280, render_resolution_y=720)
    self.engines.append(env)
    try:
      adapter = NativeMatchEngine(env, env.get_snapshot_identity, env.identity, rendering=True)
      self.assertEqual(adapter.get_snapshot_identity(), env.identity)
      env.game_config.render = False
      with self.assertRaisesRegex(ValueError, 'configuration changed'):
        adapter.get_snapshot_identity()
    finally:
      env.close()


if __name__ == '__main__':
  unittest.main()
