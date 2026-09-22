"""Actual local TCP/files/menu integration with an explicit independent engine oracle."""
import contextlib
import copy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.local_play import LocalPlayer
from gfootball.frame_sync.match_archive import (
    MAX_SNAPSHOT, MatchRecorder, capture, decode_checkpoint, engine_digest,
    playback, read_checkpoint, write_checkpoint,
)
from gfootball.frame_sync.replay_data import ReplayCapacityError, ReplayFormatError, ReplayFrame, ReplayLimits
from gfootball.frame_sync.replay_store import Replay
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.server_runtime import ServerSettings


class MatchOracle:
  """Adler32 reducer and deterministic positions; explicitly not native GameEnv."""
  def __init__(self, settings):
    self.owner = threading.current_thread()
    self.slots = settings.left_agents + settings.right_agents
    self.frames, self.digest, self.closed = 0, 1, 0
    self.fail_step = self.fail_restore = False
    # 2026-09-10: Declare the explicit oracle format instead of impersonating GameEnv.
    # self.padding = 0
    self.padding = 0
    self.restores = 0
    self.identity = dict(backend="test.MatchOracle.adler32.v1", abi="struct-le-u32x2",
                         implementation="a" * 64, resources="b" * 64)

  def check(self):
    if threading.current_thread() is not self.owner:
      raise AssertionError('Engine operation left its owner thread')

  def step_with_input(self, data):
    self.check()
    if self.fail_step:
      raise RuntimeError('Injected engine step failure')
    if len(data) != self.slots * 10:
      raise AssertionError('Incorrect native input byte count')
    self.digest = zlib.adler32(data, self.digest)
    self.frames += 1

  def get_snapshot_identity(self):
    self.check()
    return dict(self.identity)

  def get_state(self, unused=''):
    self.check()
    return struct.pack('<II', self.frames, self.digest) + bytes(self.padding)

  def get_state_digest(self):
    return self.get_state()

  # 2026-09-10: Observe whether mismatches cross the deserialization boundary.
  # def set_state(self, data):
  #   self.check()
  def set_state(self, data):
    self.check()
    self.restores += 1
    if self.fail_restore:
      raise RuntimeError('Injected engine restore failure')
    if len(data) < 8:
      raise RuntimeError('Malformed oracle state')
    self.frames, self.digest = struct.unpack_from('<II', data)
    self.padding = len(data) - 8

  def get_info(self):
    self.check()
    return SimpleNamespace(ball_position=(self.frames / 100, self.digest / 2**32, 0),
        left_team=[SimpleNamespace(position=(self.frames / 200, 0, 0))],
        right_team=[SimpleNamespace(position=(-self.frames / 200, 0, 0))],
        left_goals=self.frames // 3, right_goals=0)

  def close(self):
    self.check()
    self.closed += 1


class MatchIntegrationTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name)
    self.replay = str(self.root / 'match.jsonl')
    self.save = str(self.root / 'match.save')
    self.engines, self.players = [], []

  def factory(self, settings):
    engine = MatchOracle(settings)
    self.engines.append(engine)
    return engine

  def player(self, **options):
    options.setdefault('engine_factory', self.factory)
    player = LocalPlayer(**options)
    self.players.append(player)
    return player

  def tearDown(self):
    errors = []
    for player in self.players:
      try:
        player.stop(finalize=False)
      except BaseException as error:
        errors.append(error)
    self.assertTrue(all(engine.closed == 1 for engine in self.engines), [engine.closed for engine in self.engines])
    if errors:
      raise errors[0]

  def trace(self, frame):
    return wire.SlotInput(.5 if frame % 2 else -.25, .125, 4 if frame % 3 == 0 else 8)

  def test_play_save_reload_continue_and_both_replays_match(self):
    first = self.player(record_path=self.replay, save_path=self.save)
    first.start()
    for frame in range(3):
      first.step(self.trace(frame))
    checkpoint = first.save()
    for frame in range(3, 6):
      first.step(self.trace(frame))
    expected = first.stats()['last']['digest']
    first.stop()
    self.assertEqual(playback(self.replay, engine_factory=self.factory)['digest'], expected)
    second_path = str(self.root / 'continued.jsonl')
    second = self.player(resume_path=self.save, record_path=second_path, seed=999,
                         input_provider=lambda frame: self.trace(frame + 3))
    second.start()
    self.assertEqual(second.replica.frames, 3)
    self.assertEqual(engine_digest(second.replica), checkpoint['digest'])
    result = second.run(3, realtime=False)
    self.assertTrue(result['closed'])
    self.assertFalse(result['running'])
    self.assertEqual(result['last']['digest'], expected)
    self.assertEqual(playback(second_path, engine_factory=self.factory)['digest'], expected)

  def test_maximum_snapshot_chunks_and_real_file_round_trip(self):
    def factory(settings):
      engine = self.factory(settings)
      engine.padding = MAX_SNAPSHOT - 8
      return engine
    player = self.player(engine_factory=factory, record_path=self.replay, save_path=self.save)
    player.start()
    player.run(2, realtime=False)
    checkpoint = read_checkpoint(self.save)
    self.assertEqual(checkpoint['size'], MAX_SNAPSHOT)
    self.assertEqual(len(checkpoint['chunks']), 43)
    self.assertEqual(len(decode_checkpoint(checkpoint)[1]), MAX_SNAPSHOT)
    self.assertTrue(playback(self.replay, engine_factory=factory)['verified'])
    self.assertGreater(Path(self.save).stat().st_size, 1024 * 1024)
    with Path(self.replay).open('r', encoding='utf-8') as stream:
      self.assertEqual(json.loads(stream.readline())['version'], 2)

  def test_zero_frame_continuation_preserves_existing_score(self):
    first = self.player(save_path=self.save)
    first.start()
    first.run(3, realtime=False)
    second = self.player(resume_path=self.save, record_path=self.replay)
    second.start()
    second.stop()
    result = playback(self.replay, engine_factory=self.factory)
    self.assertEqual((result['frames'], result['score']), (0, (1, 0)))

  def test_existing_checkpoint_survives_failed_atomic_publication(self):
    player = self.player(save_path=self.save)
    player.start()
    player.step()
    saved = player.save()
    before = Path(self.save).read_bytes()
    player.step()
    with mock.patch('gfootball.frame_sync.save_store.os.replace', side_effect=OSError('replace failed')):
      with self.assertRaises(OSError):
        player.save()
    self.assertEqual(Path(self.save).read_bytes(), before)
    self.assertEqual(decode_checkpoint(read_checkpoint(self.save))[2], saved['digest'])
    self.assertNotEqual(saved['digest'], player.stats()['last']['digest'])
    self.assertTrue(player.stats()['running'])

  def test_corrupt_checkpoint_does_not_construct_engines(self):
    Path(self.save).write_bytes(b'not a save\n')
    player = self.player(resume_path=self.save)
    with self.assertRaises((SaveFormatError, ValueError)):
      player.start()
    self.assertEqual(self.engines, [])
    self.assertTrue(player.stats()['closed'])

  def test_invalid_snapshot_bounds_and_encoding_rejected(self):
    engine = self.factory(ServerSettings())
    try:
      original = capture(ServerSettings(), engine)
    finally:
      engine.close()
    for field, value in [('size', MAX_SNAPSHOT + 1), ('size', True), ('chunks', ['!' * 12]),
                         ('sha256', '0' * 64), ('chunks', []), ('digest', 'x' * 64)]:
      data = copy.deepcopy(original)
      data[field] = value
      with self.assertRaises(SaveFormatError):
        decode_checkpoint(data)

  def test_replica_factory_failure_closes_authority(self):
    calls = []
    def factory(settings):
      calls.append(1)
      if len(calls) == 2:
        raise RuntimeError('replica factory failed')
      return self.factory(settings)
    player = self.player(engine_factory=factory)
    with self.assertRaisesRegex(RuntimeError, 'replica factory failed'):
      player.start()
    self.assertTrue(player.stats()['closed'])

  def test_replica_restore_failure_closes_both_engines(self):
    def factory(settings):
      engine = self.factory(settings)
      engine.fail_restore = len(self.engines) == 2
      return engine
    player = self.player(engine_factory=factory)
    with self.assertRaisesRegex(RuntimeError, 'restore failure'):
      player.start()

  def test_replica_step_failure_aborts_recording_preserves_previous_file(self):
    Path(self.replay).write_bytes(b'previous artifact')
    player = self.player(record_path=self.replay)
    player.start()
    player.replica.fail_step = True
    with self.assertRaisesRegex(RuntimeError, 'step failure'):
      player.step()
    self.assertEqual(Path(self.replay).read_bytes(), b'previous artifact')
    self.assertTrue(player.stats()['closed'])

  def test_recording_capacity_failure_never_publishes_partial_success(self):
    Path(self.replay).write_bytes(b'previous artifact')
    player = self.player(record_path=self.replay, replay_limits=ReplayLimits(frames=1))
    player.start()
    player.step()
    with self.assertRaises(ReplayCapacityError):
      player.step()
    self.assertEqual(Path(self.replay).read_bytes(), b'previous artifact')
    self.assertTrue(player.stats()['closed'])

  def test_export_failure_still_closes_all_owners(self):
    Path(self.replay).write_bytes(b'previous artifact')
    player = self.player(record_path=self.replay)
    player.start()
    player.step()
    with mock.patch('gfootball.replay_io.os.replace', side_effect=OSError('export failed')):
      with self.assertRaises(OSError):
        player.stop()
    self.assertTrue(player.stats()['closed'])
    self.assertEqual(Path(self.replay).read_bytes(), b'previous artifact')

  def test_callback_failure_closes_match_and_aborts_export(self):
    def fail(_):
      raise RuntimeError('callback failed')
    player = self.player(record_path=self.replay, on_frame=fail)
    player.start()
    with self.assertRaisesRegex(RuntimeError, 'callback failed'):
      player.step()
    self.assertFalse(Path(self.replay).exists())

  def test_foreign_thread_cannot_step_or_save_engine(self):
    player = self.player()
    player.start()
    errors = []
    def foreign():
      for operation in (player.step, player.save, player.stop):
        try:
          operation()
        except RuntimeError:
          errors.append(1)
    thread = threading.Thread(target=foreign)
    thread.start()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [1, 1, 1])
    self.assertEqual(player.replica.frames, 0)

  def test_invalid_input_cannot_step_authority(self):
    player = self.player()
    player.start()
    for value in (wire.SlotInput(float('nan'), 0, 0), wire.SlotInput(0, 0, -1),
                   wire.SlotInput(0, 0, True), wire.SlotInput(2, 0, 0)):
      with self.assertRaises(ReplayFormatError):
        player.step(value)
    self.assertEqual(player.server.get_frame_id(), 0)
    self.assertEqual(player.replica.frames, 0)

  def test_integrity_valid_replay_with_wrong_positions_is_rejected(self):
    player = self.player(record_path=self.replay)
    player.start()
    player.run(2, realtime=False)
    old = Replay.load(self.replay)
    replay = Replay(**old.metadata())
    for index, frame in enumerate(old.frames):
      replay.add_frame(ReplayFrame(frame.frame_id, (99, 0, 0) if index == 0 else frame.ball_pos,
                                    dict(frame.player_positions), dict(frame.inputs)))
    for event in old.events:
      replay.add_event(event)
    replay.seal().save(self.replay)
    with self.assertRaisesRegex(ReplayFormatError, 'positions diverged'):
      playback(self.replay, engine_factory=self.factory)

  def test_corrupt_replay_is_rejected_before_engine_factory(self):
    Path(self.replay).write_bytes(b'broken\n')
    with self.assertRaises(ReplayFormatError):
      playback(self.replay, engine_factory=self.factory)
    self.assertEqual(self.engines, [])

  def test_fresh_process_checkpoint_read_needs_no_native_module(self):
    player = self.player(save_path=self.save)
    player.start()
    player.run(2, realtime=False)
    source = ('import sys,json; from gfootball.frame_sync.match_archive import read_checkpoint; '
              'v=read_checkpoint(sys.argv[1]); '
              'assert "gfootball_engine" not in sys.modules; '
              'print(json.dumps({"size":v["size"],"digest":v["digest"]}))')
    result = subprocess.run([sys.executable, '-c', source, self.save], capture_output=True, text=True, timeout=10)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(json.loads(result.stdout)['digest'], player.stats()['last']['digest'])

  def test_menu_local_continue_and_replay_use_actual_runtime_and_files(self):
    from gfootball.frame_sync import main_menu
    import gfootball.frame_sync.local_play as facade
    import gfootball.frame_sync.match_archive as archive
    preferences = mock.patch('gfootball.frame_sync.menu_options.DEFAULT_SETTINGS_PATH', self.root / 'preferences.save')
    preferences.start()
    self.addCleanup(preferences.stop)
    def make(*args, **kwargs):
      kwargs['engine_factory'] = self.factory
      player = LocalPlayer(*args, **kwargs)
      self.players.append(player)
      return player
    with mock.patch.object(facade, 'LocalPlayer', make), contextlib.redirect_stdout(io.StringIO()):
      with mock.patch('builtins.input', side_effect=['', '', '', '', self.replay, self.save, '2']):
        main_menu.menu_local_play()
      with mock.patch('builtins.input', side_effect=[self.save, '', '1']):
        main_menu.menu_resume_match()
    with mock.patch.object(archive, 'native_engine', self.factory), contextlib.redirect_stdout(io.StringIO()):
      with mock.patch('builtins.input', return_value=self.replay):
        main_menu.menu_replay_match()
    self.assertEqual(struct.unpack_from('<I', decode_checkpoint(read_checkpoint(self.save))[1])[0], 3)

  def test_playback_callback_failure_closes_its_engine(self):
    player = self.player(record_path=self.replay)
    player.start()
    player.run(2, realtime=False)
    def fail(frame, env):
      raise RuntimeError('playback callback failed')
    with self.assertRaisesRegex(RuntimeError, 'playback callback failed'):
      playback(self.replay, engine_factory=self.factory, on_frame=fail)

  def test_reentrant_step_is_rejected_and_context_preserves_original_error(self):
    player = self.player(record_path=self.replay)
    def callback(_):
      player.step()
    player._on_frame = callback
    with self.assertRaisesRegex(RuntimeError, 'reentrant local frame'):
      with player:
        player.step()
    self.assertTrue(player.stats()['closed'])
    self.assertFalse(Path(self.replay).exists())

  def test_finished_recorder_can_be_closed_twice_and_releases_manager_budget(self):
    engine = self.factory(ServerSettings())
    recorder = None
    try:
      recorder = MatchRecorder(ServerSettings(), engine)
      replay = recorder.finish(engine)
      self.assertTrue(replay.is_sealed)
      recorder.close()
      recorder.close()
      self.assertEqual(recorder.manager.get_storage_info()['retained_bytes'], 0)
    finally:
      if recorder is not None:
        recorder.close()
      engine.close()


if __name__ == '__main__':
  unittest.main()
