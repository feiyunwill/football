"""Actual preference files and menu actions with explicit engine factories."""
import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from gfootball.frame_sync import main_menu
from gfootball.frame_sync.client_reconnect import ReconnectLimits
from gfootball.frame_sync.menu_options import MenuOptions, load_options, save_options
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.test_match_archive import MatchOracle


class MenuOptionsTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.path = self.root / 'preferences.save'

  def test_defaults_do_not_create_files_and_roundtrip_in_fresh_process(self):
    self.assertEqual(load_options(self.path), MenuOptions())
    self.assertFalse(self.path.exists())
    options = replace(MenuOptions(), frames=19, host='localhost', port=33333, seed=123,
                      record_path=str(self.root / 'out.replay'))
    save_options(options, self.path)
    self.assertEqual(load_options(self.path), options)
    script = ('import sys,json;from gfootball.frame_sync.menu_options import load_options;'
              'v=load_options(sys.argv[1]);assert "gfootball_engine" not in sys.modules;print(json.dumps(v.payload()))')
    result = subprocess.run([sys.executable, '-c', script, str(self.path)], capture_output=True, text=True, timeout=5)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(json.loads(result.stdout), options.payload())

  def test_invalid_values_cannot_replace_previous_settings(self):
    save_options(MenuOptions(), self.path)
    before = self.path.read_bytes()
    for field, value in [('frames', True), ('frames', -1), ('port', 0), ('port', 65536),
                          ('local_left', 12), ('host_right', -1), ('seed', 2**32),
                          ('record_path', '\0bad'), ('host', ''), ('host_scenario', '')]:
      with self.assertRaises(ValueError):
        save_options(replace(MenuOptions(), **{field: value}), self.path)
      self.assertEqual(self.path.read_bytes(), before)

  def test_failed_publication_preserves_previous_settings(self):
    save_options(MenuOptions(), self.path)
    before = self.path.read_bytes()
    with mock.patch('gfootball.frame_sync.save_store.os.replace', side_effect=OSError('settings write failure')):
      with self.assertRaises(OSError):
        save_options(replace(MenuOptions(), seed=13), self.path)
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(load_options(self.path), MenuOptions())

  def test_corrupt_settings_are_not_silently_replaced(self):
    self.path.write_bytes(b'corrupt preferences')
    with self.assertRaises(SaveFormatError):
      load_options(self.path)
    with self.assertRaises(SaveFormatError):
      save_options(MenuOptions(), self.path)
    self.assertEqual(self.path.read_bytes(), b'corrupt preferences')

  def test_settings_menu_persists_real_values_and_clears_optional_paths(self):
    save_options(replace(MenuOptions(), record_path='old.replay', frames=19), self.path)
    values = ['', '', '', '', '', '', '77', 'localhost', '33333', '23', '-', str(self.root / 'match.save')]
    with mock.patch.object(main_menu, '_settings_path', str(self.path)), mock.patch('builtins.input', side_effect=values), contextlib.redirect_stdout(io.StringIO()):
      result = main_menu.menu_settings()
    self.assertEqual(load_options(self.path), result)
    self.assertEqual((result.seed, result.port, result.frames, result.record_path), (77, 33333, 23, None))

  def test_host_menu_runs_actual_host_and_uses_preference_defaults(self):
    import gfootball.frame_sync.multiplayer_runtime as runtime
    record, save = str(self.root / 'host.replay'), str(self.root / 'host.save')
    save_options(replace(MenuOptions(), host_right=0, frames=2, record_path=record, save_path=save), self.path)
    engines = []
    def factory(settings):
      env = MatchOracle(settings)
      engines.append(env)
      return env
    def host(**options):
      return HostedMatch(**options, engine_factory=factory)
    with mock.patch.object(main_menu, '_settings_path', str(self.path)), mock.patch.object(runtime, 'HostedMatch', host), mock.patch('builtins.input', side_effect=['', '', '', '', '0', '', '', '']), contextlib.redirect_stdout(io.StringIO()):
      result = main_menu.menu_host_game()
    self.assertEqual(result['frame'], 2)
    self.assertTrue(result['closed'])
    self.assertTrue(result['end_acknowledged'])
    self.assertTrue(Path(record).is_file() and Path(save).is_file())
    self.assertTrue(all(engine.closed == 1 for engine in engines))

  def test_join_menu_plays_against_actual_host_until_end_notification(self):
    import gfootball.frame_sync.multiplayer_runtime as runtime
    ports, errors, engines = queue.Queue(maxsize=1), [], []
    reconnect = ReconnectLimits(base_seconds=.01, max_seconds=.03, recovery_seconds=.2)
    def factory(settings):
      env = MatchOracle(settings)
      engines.append(env)
      return env
    def host_worker():
      host = HostedMatch(engine_factory=factory, port=0, reconnect_limits=reconnect)
      try:
        ports.put(host.start())
        host.run(3, realtime=False, lobby_timeout=3)
      except BaseException as error:
        errors.append(repr(error))
      finally:
        host.close(finalize=False)
    worker = threading.Thread(target=host_worker, name='football-match-test-host')
    worker.start()
    port = ports.get(timeout=3)
    def player(*args, **options):
      return NetworkPlayer(*args, **options, engine_factory=factory, reconnect_limits=reconnect)
    try:
      with mock.patch.object(main_menu, '_settings_path', str(self.path)), mock.patch.object(runtime, 'NetworkPlayer', player), mock.patch('builtins.input', side_effect=['127.0.0.1', str(port), '100']), contextlib.redirect_stdout(io.StringIO()):
        result = main_menu.menu_join_game()
    finally:
      worker.join(6)
    self.assertFalse(worker.is_alive())
    self.assertEqual(errors, [])
    self.assertTrue(result['ended'])
    self.assertEqual(result['final_frame'], 3)
    self.assertTrue(all(engine.closed == 1 for engine in engines))

  def test_main_reports_action_failure_and_restores_settings_scope(self):
    previous = main_menu._settings_path
    with mock.patch.object(sys, 'argv', ['menu', '--mode', 'host', '--settings-file', str(self.path)]), mock.patch('builtins.input', return_value='bad integer'), contextlib.redirect_stdout(io.StringIO()):
      self.assertEqual(main_menu.main(), 1)
    self.assertEqual(main_menu._settings_path, previous)

  def test_saved_defaults_drive_actual_continuation_and_replay_menus(self):
    import gfootball.frame_sync.local_play as facade
    import gfootball.frame_sync.match_archive as archive
    from gfootball.frame_sync.local_runtime import LocalPlayer
    save, replay = str(self.root / 'match.save'), str(self.root / 'continued.replay')
    engines = []
    def factory(settings):
      engine = MatchOracle(settings)
      engines.append(engine)
      return engine
    first = LocalPlayer(save_path=save, engine_factory=factory)
    try:
      first.start()
      first.run(1, realtime=False)
    finally:
      first.stop(finalize=False)
    save_options(replace(MenuOptions(), frames=2, save_path=save, record_path=replay), self.path)
    def local(**options):
      return LocalPlayer(**options, engine_factory=factory)
    with mock.patch.object(main_menu, '_settings_path', str(self.path)), mock.patch.object(facade, 'LocalPlayer', local), mock.patch('builtins.input', side_effect=['', '', '']), contextlib.redirect_stdout(io.StringIO()):
      result = main_menu.menu_resume_match()
    self.assertEqual(result['frames'], 2)
    with mock.patch.object(main_menu, '_settings_path', str(self.path)), mock.patch.object(archive, 'native_engine', factory), mock.patch('builtins.input', return_value=''), contextlib.redirect_stdout(io.StringIO()):
      replayed = main_menu.menu_replay_match()
    self.assertEqual(replayed['frames'], 2)
    self.assertTrue(replayed['verified'])
    self.assertTrue(all(engine.closed == 1 for engine in engines))


if __name__ == '__main__':
  unittest.main()
