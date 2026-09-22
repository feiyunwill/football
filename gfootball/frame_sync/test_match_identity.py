"""Compatibility boundaries with actual files and explicit non-native engines."""
import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from gfootball.frame_sync import match_identity as identity
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import (
    MatchRecorder, SAVE_LIMITS, capture, decode_checkpoint, playback, read_checkpoint, write_checkpoint,
)
from gfootball.frame_sync.replay_data import ReplayEvent
from gfootball.frame_sync.replay_store import Replay
from gfootball.frame_sync.save_data import SaveFormatError, SaveSlot, SaveType
from gfootball.frame_sync.save_runtime import SaveManager
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.test_match_archive import MatchOracle


class MatchIdentityTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.save = str(self.root / 'match.save')
    self.replay = str(self.root / 'match.jsonl')
    self.engines = []

  def engine(self, settings=None):
    engine = MatchOracle(settings or ServerSettings())
    self.engines.append(engine)
    return engine

  def tearDown(self):
    self.assertTrue(all(engine.closed == 1 for engine in self.engines), [engine.closed for engine in self.engines])

  def checkpoint(self):
    engine = self.engine()
    try:
      return capture(ServerSettings(), engine)
    finally:
      engine.close()

  def test_each_identity_component_rejects_before_restoring_saved_engine(self):
    checkpoint = self.checkpoint()
    write_checkpoint(self.save, checkpoint)
    original = Path(self.save).read_bytes()
    for component in sorted(identity.IDENTITY_FIELDS):
      def factory(settings):
        engine = self.engine(settings)
        engine.identity[component] = 'c' * 64
        return engine
      player = LocalPlayer(resume_path=self.save, engine_factory=factory)
      with self.assertRaisesRegex(SaveFormatError, component):
        player.start()
      self.assertEqual(self.engines[-1].restores, 0)
      self.assertTrue(player.stats()['closed'])
      self.assertEqual(Path(self.save).read_bytes(), original)

  def test_replica_identity_mismatch_does_not_restore_or_leak_authority(self):
    def factory(settings):
      engine = self.engine(settings)
      if len(self.engines) == 2:
        engine.identity['implementation'] = 'c' * 64
      return engine
    player = LocalPlayer(engine_factory=factory)
    with self.assertRaisesRegex(SaveFormatError, 'implementation'):
      player.start()
    self.assertEqual([engine.restores for engine in self.engines], [0, 0])
    self.assertTrue(player.stats()['closed'])

  def test_missing_identity_provider_is_rejected_before_snapshot_capture(self):
    class Unsupported:
      def get_state(self, unused):
        raise AssertionError('Unknown backend must not be read')
    with self.assertRaisesRegex(SaveFormatError, 'explicitly provide'):
      capture(ServerSettings(), Unsupported())

  def test_legacy_save_never_constructs_engine_and_is_preserved(self):
    checkpoint = self.checkpoint()
    checkpoint['version'] = 1
    del checkpoint['identity']
    slot = SaveSlot('match', 'Legacy match', SaveType.CUSTOM, checkpoint, limits=SAVE_LIMITS)
    with SaveManager(path=self.save, limits=SAVE_LIMITS) as manager:
      manager.import_slot(slot.export_bytes().decode('utf-8'))
    before, count = Path(self.save).read_bytes(), len(self.engines)
    player = LocalPlayer(resume_path=self.save, engine_factory=self.engine)
    with self.assertRaisesRegex(SaveFormatError, 'version 1'):
      player.start()
    self.assertEqual(len(self.engines), count)
    self.assertEqual(Path(self.save).read_bytes(), before)
    with self.assertRaisesRegex(SaveFormatError, 'version 1'):
      write_checkpoint(self.save, self.checkpoint())
    self.assertEqual(Path(self.save).read_bytes(), before)

  def test_malformed_metadata_rejected_before_base64_allocation(self):
    valid = self.checkpoint()
    malformed = [None, {}, dict(valid['identity'], extra=0), dict(valid['identity'], abi=True),
                 dict(valid['identity'], backend='x' * 129), dict(valid['identity'], abi='line\nbreak'),
                 dict(valid['identity'], resources='G' * 64), dict(valid['identity'], implementation=['a'])]
    for value in malformed:
      checkpoint = copy.deepcopy(valid)
      checkpoint['identity'] = value
      with mock.patch('gfootball.frame_sync.match_archive.base64.b64decode', side_effect=AssertionError('allocation boundary')):
        with self.assertRaises(SaveFormatError):
          decode_checkpoint(checkpoint)

  def test_valid_replay_with_incompatible_origin_rejects_before_set_state(self):
    with LocalPlayer(record_path=self.replay, engine_factory=self.engine) as player:
      player.step()
    source = Replay.load(self.replay)
    altered = Replay(**source.metadata())
    for frame in source.frames:
      altered.add_frame(frame)
    for index, event in enumerate(source.events):
      row = event.to_dict()
      if index == 0:
        row['details']['identity']['resources'] = 'c' * 64
      altered.add_event(ReplayEvent.from_dict(row))
    altered.seal().save(self.replay)
    with self.assertRaisesRegex(SaveFormatError, 'resources'):
      playback(self.replay, engine_factory=self.engine)
    self.assertEqual(self.engines[-1].restores, 0)

  def test_legacy_replay_rejected_before_factory(self):
    with LocalPlayer(record_path=self.replay, engine_factory=self.engine):
      pass
    source = Replay.load(self.replay)
    altered = Replay(**source.metadata())
    for event in source.events:
      row = event.to_dict()
      if row['event_type'] == source.events[0].to_dict()['event_type']:
        row['details']['version'] = 1
        del row['details']['identity']
      altered.add_event(ReplayEvent.from_dict(row))
    altered.seal().save(self.replay)
    count = len(self.engines)
    with self.assertRaisesRegex(SaveFormatError, 'version 1'):
      playback(self.replay, engine_factory=self.engine)
    self.assertEqual(len(self.engines), count)

  def test_recorder_identity_drift_aborts_publication_and_closes_owners(self):
    Path(self.replay).write_bytes(b'previous replay')
    player = LocalPlayer(record_path=self.replay, engine_factory=self.engine)
    player.start()
    player.step()
    player.server._call(lambda: player.server._runtime.env.identity.update(resources='c' * 64))
    with self.assertRaisesRegex(SaveFormatError, 'resources'):
      player.stop()
    self.assertTrue(player.stats()['closed'])
    self.assertEqual(Path(self.replay).read_bytes(), b'previous replay')

  def test_identity_copy_cannot_relabel_an_existing_checkpoint(self):
    engine = self.engine()
    try:
      checkpoint = capture(ServerSettings(), engine)
      engine.identity['resources'] = 'c' * 64
      self.assertEqual(checkpoint['identity']['resources'], 'b' * 64)
      decoded = decode_checkpoint(checkpoint)
      decoded[3]['resources'] = 'd' * 64
      self.assertEqual(checkpoint['identity']['resources'], 'b' * 64)
    finally:
      engine.close()


class FingerprintFilesTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.data = self.root / 'assets'
    self.data.mkdir()
    self.ball = self.data / 'ball.bin'
    self.ball.write_bytes(bytes(range(256)) * 600)

  def capture(self, root=None):
    return identity.fingerprint(trees=[('assets', root or self.data, False)])

  def test_content_path_and_add_remove_changes_are_detected(self):
    original = self.capture()
    data = self.ball.read_bytes()
    self.ball.write_bytes(b'changed' + data[7:])
    self.assertNotEqual(self.capture(), original)
    self.ball.write_bytes(data)
    self.assertEqual(self.capture(), original)
    extra = self.data / 'extra'
    extra.write_bytes(b'')
    self.assertNotEqual(self.capture(), original)
    extra.unlink()
    self.assertEqual(self.capture(), original)
    self.ball.rename(self.data / 'renamed.bin')
    self.assertNotEqual(self.capture(), original)

  def test_relocated_identical_tree_has_same_digest(self):
    other = self.root / 'moved'
    other.mkdir()
    (other / 'ball.bin').write_bytes(self.ball.read_bytes())
    self.assertEqual(self.capture(other), self.capture())

  def test_large_file_uses_bounded_stream_reads(self):
    sizes, original = [], identity.os.read
    def read(descriptor, count):
      sizes.append(count)
      return original(descriptor, count)
    with mock.patch.object(identity.os, 'read', read):
      self.capture()
    self.assertGreater(len(sizes), 3)
    self.assertLessEqual(max(sizes), 65536)

  def test_file_entry_and_total_limits_prevent_hash_reads(self):
    for constant, maximum in [('MAX_FILE_BYTES', 10), ('MAX_TOTAL_BYTES', 10), ('MAX_ENTRIES', 0), ('MAX_DIRECTORIES', 0)]:
      with mock.patch.object(identity, constant, maximum), mock.patch.object(identity.os, 'read', side_effect=AssertionError('unadmitted read')):
        with self.assertRaises(SaveFormatError):
          self.capture()

  def test_nested_symlink_cannot_escape_resource_tree(self):
    # Windows symlink creation may require privilege; a real junction is also
    # a reparse point. This test observes the portable scandir symlink contract
    # with an explicit entry seam, never a replacement native engine module.
    class Entry:
      name = 'outside'
      def is_symlink(self):
        return True
    class Scan:
      def __enter__(self):
        return iter([Entry()])
      def __exit__(self, *_):
        pass
    with mock.patch.object(identity.os, 'scandir', return_value=Scan()):
      with self.assertRaisesRegex(SaveFormatError, 'symbolic link'):
        self.capture()

  def test_file_changed_during_read_is_rejected_and_descriptor_closed(self):
    original, descriptors = identity.os.read, []
    def read(descriptor, count):
      value = original(descriptor, count)
      if not descriptors:
        descriptors.append(descriptor)
        with self.ball.open('ab') as stream:
          stream.write(b'extra')
      return value
    with mock.patch.object(identity.os, 'read', read):
      with self.assertRaisesRegex(SaveFormatError, 'changed'):
        self.capture()
    with self.assertRaises(OSError):
      identity.os.fstat(descriptors[0])

  def test_new_file_during_capture_is_rejected(self):
    original, changed = identity.os.read, []
    def read(descriptor, count):
      value = original(descriptor, count)
      if not changed:
        changed.append(True)
        (self.data / 'new-file').write_bytes(b'new')
      return value
    with mock.patch.object(identity.os, 'read', read):
      with self.assertRaisesRegex(SaveFormatError, 'directory changed'):
        self.capture()

  def test_python_tree_ignores_bytecode_and_hashes_source(self):
    source = self.data / 'scenario.py'
    source.write_bytes(b'x = 1\n')
    def capture():
      return identity.fingerprint(trees=[('python', self.data, True)])
    before = capture()
    (self.data / '__pycache__').mkdir()
    (self.data / '__pycache__' / 'scenario.pyc').write_bytes(b'cache')
    self.assertEqual(capture(), before)
    source.write_bytes(b'x = 2\n')
    self.assertNotEqual(capture(), before)

  def test_adapter_checks_initial_files_config_and_owner(self):
    # 2026-09-13: adapter fixture represents negotiated v7 physics.
    # engine = SimpleNamespace(game_config=SimpleNamespace(render=False, physics_steps_per_frame=10,
    engine = SimpleNamespace(game_config=SimpleNamespace(render=False, physics_steps_per_frame=2,
                                                        render_resolution_x=1280, render_resolution_y=720))
    def provider():
      return dict(backend='explicit-file-fixture', abi='fixture', implementation='a' * 64, resources=self.capture())
    initial = provider()
    adapter = identity.NativeMatchEngine(engine, provider, initial)
    self.assertEqual(adapter.get_snapshot_identity(), initial)
    errors = []
    def foreign():
      try:
        adapter.get_snapshot_identity()
      except RuntimeError:
        errors.append(True)
    thread = threading.Thread(target=foreign)
    thread.start()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [True])
    engine.game_config.physics_steps_per_frame = 1
    with self.assertRaisesRegex(SaveFormatError, 'configuration changed'):
      adapter.get_snapshot_identity()
    # 2026-09-13: restore v7 configuration before independently testing changed resources.
    # engine.game_config.physics_steps_per_frame = 10
    engine.game_config.physics_steps_per_frame = 2
    self.ball.write_bytes(b'replaced content')
    with self.assertRaisesRegex(SaveFormatError, 'after engine creation'):
      adapter.get_snapshot_identity()

  def test_explicit_font_is_hashed_while_only_its_unused_fallback_is_excluded(self):
    fallback = self.data / 'media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf'
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b'unused')
    font = self.root / 'configured.ttf'
    font.write_bytes(b'actual font')
    def capture():
      return identity.fingerprint([('font', font)], [('data', self.data, False)],
                                  excluded=(identity.UNUSED_FONT_FALLBACK,))
    before = capture()
    fallback.write_bytes(b'different unused fallback')
    self.assertEqual(capture(), before)
    font.write_bytes(b'changed actual font')
    self.assertNotEqual(capture(), before)
    with self.assertRaises(SaveFormatError):
      identity.fingerprint(excluded=['path'] * 9)


class NativeMappingParserTest(unittest.TestCase):
  """Proc-maps byte fixtures; these do not execute the Linux loader or GameEnv."""
  def line(self, filename, device=b'08:13', inode=b'123456'):
    return b'7f00-7f10 r-xp 0000 ' + device + b' ' + inode + b' ' + filename + b'\n'

  def test_binding_core_and_optional_shared_libraries_with_space_in_path(self):
    for name in (b'_gameplayfootball.so', b'_gameplayfootball.cpython-314-x86_64-linux-gnu.so',
                 b'libfootball_engine.so', b'libfootball_engine.so.2', b'libblunted2.so', b'libgamelib.so'):
      path = b'/opt/football release/' + name
      self.assertEqual(identity.parse_native_mapping(self.line(path)),
                       (name.decode(), path.decode(), 8, 19, 123456))

  def test_unrelated_mappings_do_not_change_engine_identity(self):
    for path in (b'[heap]', b'/usr/lib/libc.so.6', b'/usr/lib/libfootball_engine.software',
                 b'/opt/libfootball_engine-copy.so', b'/opt/gameplayfootball.txt'):
      self.assertIsNone(identity.parse_native_mapping(self.line(path)))

  def test_deleted_or_escaped_paths_are_rejected(self):
    for path in (b'/opt/libfootball_engine.so (deleted)', b'/opt/_gameplayfootball.so (deleted)',
                 b'/opt/escaped\\012path/libfootball_engine.so'):
      with self.assertRaisesRegex(SaveFormatError, 'removed|unsupported'):
        identity.parse_native_mapping(self.line(path))

  def test_malformed_device_inode_and_oversized_records_are_rejected(self):
    for device, inode in [(b'xx:yy', b'1'), (b'01:02:03', b'1'), (b'01:02', b'-1'),
                          (b'01:02', b'0'), (b'01:02', b'18446744073709551616')]:
      with self.assertRaises(SaveFormatError):
        identity.parse_native_mapping(self.line(b'/opt/libfootball_engine.so', device, inode))
    for line in (b'x' * 8193, b'\0', 'not bytes'):
      with self.assertRaises(SaveFormatError):
        identity.parse_native_mapping(line)


if __name__ == '__main__':
  unittest.main()
