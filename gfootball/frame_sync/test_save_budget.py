"""Bounded save ownership, actual files and actual process failure tests."""
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import weakref

from gfootball.frame_sync.save_system import (
    GameProgress, SaveManager, SaveSlot, SaveType, SaveLimits, SaveDiskLimits,
    SaveCapacityError, SaveFormatError, SaveConflictError,
)
from gfootball.frame_sync import save_store
from gfootball.recording_directory import CONTROL_NAME, _lock_descriptors

ROOT = Path(__file__).resolve().parents[2]


class SaveBudgetTest(unittest.TestCase):
  def manager(self, **options):
    manager = SaveManager(**options)
    self.addCleanup(manager.close)
    return manager

  def test_all_public_slot_views_are_immutable_independent_snapshots(self):
    manager = self.manager()
    created = manager.create_slot('career', 'Career')
    value = {'team': {'players': [1, 2]}}
    manager.save('career', value)
    value['team']['players'].append(3)
    self.assertEqual(created.data, {})
    for slot in (manager.get_slot('career'), manager.list_slots()[0]):
      with self.assertRaises(AttributeError):
        slot.name = 'Modified'
      with self.assertRaises(AttributeError):
        slot.data = {}
      with self.assertRaises(AttributeError):
        slot.__dict__
      slot.data['team']['players'].clear()
      slot.to_dict()['name'] = 'Different'
    loaded = manager.load('career')
    loaded['team']['players'].clear()
    self.assertEqual(manager.load('career'), {'team': {'players': [1, 2]}})
    self.assertEqual(manager.get_slot('career').name, 'Career')

  def test_payload_limit_preserves_old_data_name_and_time(self):
    manager = self.manager(limits=SaveLimits(slot_bytes=128))
    manager.create_slot('s', 'Old')
    manager.save('s', {'ok': True})
    before = manager.export_slot('s')
    with self.assertRaises(SaveCapacityError):
      manager.save('s', {'large': 'x' * 128}, name='New')
    self.assertEqual(manager.export_slot('s'), before)

  def test_total_retained_capacity_is_atomic_and_deletion_refunds(self):
    charge = SaveSlot('a', 'A', SaveType.CUSTOM)._bytes
    manager = self.manager(limits=SaveLimits(slot_bytes=512, total_bytes=charge * 2 + 128, slots=3))
    manager.create_slot('a', 'A')
    manager.create_slot('b', 'B')
    with self.assertRaises(SaveCapacityError):
      manager.save('a', {'value': 'x' * 200})
    self.assertEqual(manager.load('a'), {})
    manager.delete_slot('b')
    self.assertTrue(manager.save('a', {'value': 'x' * 200}))
    usage = manager.get_storage_usage()
    self.assertGreater(usage['retained_bytes'], usage['total_bytes'])
    self.assertLessEqual(usage['retained_bytes'], usage['retained_bytes_max'])

  def test_slot_count_and_duplicate_never_overwrite(self):
    manager = self.manager(limits=SaveLimits(slots=1))
    first = manager.create_slot('s', 'First')
    with self.assertRaises(ValueError):
      manager.create_slot('s', 'Second')
    with self.assertRaises(SaveCapacityError):
      manager.create_slot('other', 'Other')
    self.assertIs(manager.get_slot('s'), first)
    self.assertIsNone(manager.import_slot(json.dumps(dict(slot_id='other', name='Other', save_type='custom'))))

  def test_invalid_plain_data_never_runs_custom_conversion(self):
    class Dangerous:
      def __deepcopy__(self, memo):
        raise AssertionError('Caller code ran')
      def __str__(self):
        raise AssertionError('Caller conversion ran')
    class CustomDict(dict):
      def items(self):
        raise AssertionError('Custom mapping ran')
    manager = self.manager()
    manager.create_slot('s', 'Save')
    for data in (None, [], {'x': Dangerous()}, CustomDict(x=1), {1: 'not a string'},
                 {'x': float('nan')}, {'x': float('inf')}, {'x': 2**63}, {'x': '\ud800'}):
      with self.subTest(kind=type(data).__name__), self.assertRaises(SaveFormatError):
        manager.save('s', data)
    self.assertEqual(manager.load('s'), {})

  def test_graph_cycle_depth_nodes_and_container_limits(self):
    manager = self.manager(limits=SaveLimits(nodes=64, depth=4, container_items=16))
    manager.create_slot('s', 'Save')
    cycle = {}; cycle['self'] = cycle
    deep = {'x': {'x': {'x': {'x': {'x': 1}}}}}
    broad = {'x': [list(range(16)) for _ in range(8)]}
    for data in (cycle, deep, broad, {'x': list(range(17))}):
      with self.assertRaises(SaveFormatError):
        manager.save('s', data)
    self.assertEqual(manager.load('s'), {})

  def test_unicode_limits_and_canonical_size(self):
    manager = self.manager(limits=SaveLimits(slot_bytes=512, string_bytes=256))
    manager.create_slot('存档', '职业生涯', SaveType.PROGRESS)
    data = {'名称': '球队', 'items': (1, 2), 'boolean': True, 'empty': None}
    manager.save('存档', data)
    self.assertEqual(manager.load('存档')['items'], [1, 2])
    expected = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    self.assertEqual(manager.get_slot('存档').size_bytes, len(expected))
    with self.assertRaises(SaveCapacityError):
      manager.save('存档', {'x': '球' * 86})

  def test_import_rejects_duplicate_keys_version_nonfinite_and_bad_metadata(self):
    manager = self.manager()
    manager.create_slot('s', 'Save')
    before = manager.export_slot('s')
    base = dict(slot_id='s', name='Other', save_type='custom', data={'money': 999})
    invalid = ['[]', '{', '{"slot_id":"s","slot_id":"x"}',
               json.dumps(dict(base, data=None)), json.dumps(dict(base, created_at=None)),
               json.dumps(dict(base, updated_at=-1)), json.dumps(dict(base, name=5)),
               json.dumps(dict(base, size_bytes=[])), json.dumps(dict(base, extra=True)),
               json.dumps(dict(base, format='football.save_slot', version=2)),
               json.dumps(dict(base, data={'x': float('nan')})),
               json.dumps(dict(base, data={'x': 2**63}))]
    for raw in invalid:
      self.assertIsNone(manager.import_slot(raw), raw)
      self.assertEqual(manager.export_slot('s'), before)

  def test_legacy_import_recomputes_size_and_new_format_roundtrips(self):
    manager = self.manager()
    old = dict(slot_id='s', name='Legacy', save_type='settings', data={'nested': [1, 2]},
               size_bytes=999999, created_at=100, updated_at=101)
    slot = manager.import_slot(json.dumps(old))
    self.assertEqual(slot.size_bytes, len(b'{"nested":[1,2]}'))
    other = self.manager()
    self.assertEqual(other.import_slot(manager.export_slot('s')).data, old['data'])
    self.assertEqual(other.get_slot('s').created_at, 100)

  def test_oversized_and_deep_import_reject_before_json_decoder(self):
    manager = self.manager(limits=SaveLimits(slot_bytes=128, depth=4))
    with mock.patch('gfootball.frame_sync.save_data.json.loads', side_effect=AssertionError('Decoder ran')):
      self.assertIsNone(manager.import_slot(' ' * 3000))
      self.assertIsNone(manager.import_slot('[' * 1000 + ']' * 1000))

  def test_many_overwrites_release_obsolete_slot_objects(self):
    manager = self.manager()
    manager.create_slot('s', 'Save')
    references = []
    for frame in range(1000):
      manager.save('s', {'frame': frame, 'values': [1, 2, 3]})
      references.append(weakref.ref(manager.get_slot('s')))
    self.assertTrue(all(reference() is None for reference in references[:-1]))
    self.assertEqual(manager.get_storage_usage()['slots_used'], 1)
    manager.close()
    gc.collect()
    self.assertIsNone(references[-1]())

  def test_maximum_default_payload_and_one_record_overflow(self):
    manager = self.manager()
    manager.create_slot('s', 'Large')
    value = 'x' * 65536
    self.assertTrue(manager.save('s', {'records': [value] * 15}))
    before = manager.get_slot('s')
    self.assertGreater(before.size_bytes, 900000)
    with self.assertRaises(SaveCapacityError):
      manager.save('s', {'records': [value] * 16})
    self.assertIs(manager.get_slot('s'), before)

  def test_process_and_closed_owner_guards(self):
    manager = self.manager()
    pid = os.getpid()
    with mock.patch('gfootball.frame_sync.save_runtime.os.getpid', return_value=pid + 1):
      for method in (manager.close, manager.reload, manager.list_slots):
        with self.assertRaisesRegex(RuntimeError, 'fork'):
          method()
    manager.close()
    manager.close()
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      manager.create_slot('s', 'Save')

  def test_concurrent_slot_admission_keeps_exact_capacity(self):
    manager = self.manager()
    barrier = threading.Barrier(17)
    accepted, rejected, errors = [], [], []
    def run(index):
      try:
        barrier.wait(3)
        manager.create_slot(str(index), 'Save')
        accepted.append(index)
      except SaveCapacityError:
        rejected.append(index)
      except BaseException as error:
        errors.append(error)
    threads = [threading.Thread(target=run, args=(i,), name='football-save-admission-test', daemon=False)
               for i in range(16)]
    for thread in threads:
      thread.start()
    barrier.wait(3)
    for thread in threads:
      thread.join(3)
      self.assertFalse(thread.is_alive())
    self.assertFalse(errors)
    self.assertEqual((len(accepted), len(rejected), len(manager.list_slots())), (10, 6, 10))


class ProgressBudgetTest(unittest.TestCase):
  def test_get_set_and_from_dict_never_alias_live_progress(self):
    progress = GameProgress()
    teams = progress.get('unlocks.teams')
    teams.clear()
    self.assertTrue(progress.is_team_unlocked('real_madrid'))
    trophy = {'name': 'Cup', 'seasons': [1]}
    progress.set('career.trophies', [trophy])
    trophy['seasons'].append(2)
    self.assertEqual(progress.get('career.trophies'), [{'name': 'Cup', 'seasons': [1]}])
    loaded = progress.to_dict()
    progress.from_dict(loaded)
    loaded['career']['money'] = 99
    self.assertEqual(progress.get('career.money'), 0)

  def test_invalid_progress_schema_preserves_current_snapshot(self):
    progress = GameProgress()
    before = progress.to_dict()
    for data in ({}, {'career': []}, dict(before, stats={}), dict(before, unlocks={'teams': []})):
      with self.assertRaises(SaveFormatError):
        progress.from_dict(data)
      self.assertEqual(progress.to_dict(), before)
    with self.assertRaises(SaveFormatError):
      progress.set('career', 5)
    with self.assertRaises(SaveFormatError):
      progress.set('unlocks.teams', ['same', 'same'])

  def test_stats_overflow_negative_time_and_inconsistent_win_are_atomic(self):
    progress = GameProgress()
    before = progress.to_dict()
    for options in (dict(playtime_seconds=-1), dict(won=True), dict(match_played=1)):
      with self.assertRaises(SaveFormatError):
        progress.update_stats(**options)
      self.assertEqual(progress.to_dict(), before)
    progress.set('stats.total_matches', 2**63 - 1)
    before = progress.to_dict()
    with self.assertRaises(SaveFormatError):
      progress.update_stats(match_played=True, goal_scored=True)
    self.assertEqual(progress.to_dict(), before)

  def test_progress_paths_reject_empty_deep_and_scalar_traversal(self):
    progress = GameProgress()
    for path in ('', '.career', 'career..money', 'x.' * 9 + 'leaf', 'career.money.value'):
      with self.assertRaises(SaveFormatError):
        progress.set(path, 1)
    self.assertEqual(progress.get('career.money'), 0)
    self.assertEqual(progress.get('missing.value', 42), 42)

  def test_unlock_capacity_failure_preserves_valid_state(self):
    progress = GameProgress(limits=SaveLimits(container_items=16))
    for index in range(14):
      self.assertTrue(progress.unlock_team('team%d' % index))
    before = progress.to_dict()
    with self.assertRaises(SaveCapacityError):
      progress.unlock_team('one-too-many')
    self.assertEqual(progress.to_dict(), before)
    self.assertFalse(progress.unlock_team('team1'))

  def test_concurrent_stats_updates_do_not_lose_matches(self):
    progress = GameProgress()
    errors = []
    def run():
      try:
        for _ in range(100):
          progress.update_stats(match_played=True, goal_scored=True, won=True, playtime_seconds=1)
      except BaseException as error:
        errors.append(error)
    threads = [threading.Thread(target=run, name='football-save-stats-test', daemon=False) for _ in range(8)]
    for thread in threads:
      thread.start()
    for thread in threads:
      thread.join(5)
      self.assertFalse(thread.is_alive())
    self.assertFalse(errors)
    self.assertEqual(progress.get('stats'), dict(total_matches=800, total_goals=800,
                                               total_wins=800, playtime_seconds=800))


class SaveDiskTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-save-test-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.path = self.directory / 'career.saves'

  def manager(self, **options):
    manager = SaveManager(path=self.path, **options)
    self.addCleanup(manager.close)
    return manager

  def initialize(self, **options):
    manager = self.manager(**options)
    manager.create_slot('s', 'Career', SaveType.PROGRESS)
    manager.save('s', {'money': 10})
    return manager

  def payloads(self):
    self.assertFalse(_lock_descriptors)
    return sorted(path for path in self.directory.iterdir() if path.name != CONTROL_NAME)

  def child(self, code, *args):
    return subprocess.run([sys.executable, '-W', 'error::ResourceWarning', '-c', code, str(self.path), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=15,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

  def test_restart_roundtrip_progress_settings_and_deletion(self):
    manager = self.manager()
    progress = GameProgress()
    progress.unlock_team('bayern')
    progress.update_stats(match_played=True, won=True)
    manager.create_slot('career', 'Career', SaveType.PROGRESS)
    manager.save('career', progress.to_dict())
    manager.create_slot('settings', 'Settings', SaveType.SETTINGS)
    manager.save('settings', {'graphics': {'width': 1920}, 'sound': 0.5})
    manager.close()
    restored = self.manager()
    other = GameProgress()
    other.from_dict(restored.load('career'))
    self.assertEqual(other.to_dict(), progress.to_dict())
    self.assertEqual(restored.load('settings')['sound'], 0.5)
    restored.delete_slot('settings')
    self.assertIsNone(self.manager().load('settings'))
    self.assertEqual(self.payloads(), [self.path])

  def test_actual_fresh_process_load_needs_no_array_codec_or_engine_import(self):
    self.initialize()
    result = self.child('''import sys
from gfootball.frame_sync.save_system import SaveManager
m=SaveManager(path=sys.argv[1])
assert m.load('s') == {'money': 10}
assert not any(name in sys.modules for name in ('numpy','cv2','gfootball_engine','gym'))
m.close()
''')
    self.assertEqual(result.returncode, 0, result.stderr)

  def test_stale_writer_conflicts_and_reload_recovers(self):
    first = self.initialize()
    second = self.manager()
    first.save('s', {'money': 11})
    with self.assertRaises(SaveConflictError):
      second.save('s', {'money': 99})
    self.assertEqual(second.load('s'), {'money': 10})
    second.reload()
    second.save('s', {'money': 12})
    self.assertEqual(self.manager().load('s'), {'money': 12})

  def test_fsync_failure_preserves_old_file_memory_and_cleans_temp(self):
    manager = self.initialize()
    before = self.path.read_bytes()
    with mock.patch.object(save_store.os, 'fsync', side_effect=OSError('injected fsync failure')):
      with self.assertRaisesRegex(OSError, 'fsync'):
        manager.save('s', {'money': 99})
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(manager.load('s'), {'money': 10})
    self.assertEqual(self.payloads(), [self.path])
    self.assertTrue(manager.save('s', {'money': 12}))

  def test_replace_failure_preserves_old_file_and_new_slot_is_not_added(self):
    manager = self.initialize()
    before = self.path.read_bytes()
    with mock.patch.object(save_store.os, 'replace', side_effect=OSError('injected rename failure')):
      with self.assertRaises(OSError):
        manager.create_slot('new', 'New')
    self.assertEqual(self.path.read_bytes(), before)
    self.assertIsNone(manager.get_slot('new'))
    self.assertEqual(self.payloads(), [self.path])

  def test_quota_counts_existing_files_and_preserves_them(self):
    manager = self.initialize()
    foreign = self.directory / 'unrelated.bin'
    foreign.write_bytes(b'preserve')
    restricted = self.manager(disk_limits=SaveDiskLimits(total_files=2))
    with self.assertRaises(SaveCapacityError):
      restricted.save('s', {'money': 99})
    self.assertEqual(foreign.read_bytes(), b'preserve')
    self.assertEqual(manager.load('s'), {'money': 10})
    self.assertEqual(self.payloads(), [self.path, foreign])

  def test_truncation_checksum_and_trailing_data_never_replace_memory(self):
    manager = self.initialize()
    before = self.path.read_bytes()
    corruptions = (before[:-1], before.replace(b'"money":10', b'"money":99'), before + b'{}\n')
    for bad in corruptions:
      self.path.write_bytes(bad)
      with self.assertRaises(SaveFormatError):
        manager.reload()
      self.assertEqual(manager.load('s'), {'money': 10})
      with self.assertRaises(SaveFormatError):
        manager.save('s', {'money': 20})
      self.assertEqual(self.path.read_bytes(), bad)
      self.path.write_bytes(before)

  def test_oversized_file_rejects_before_open_or_parse(self):
    manager = self.initialize(limits=SaveLimits(slot_bytes=128, total_bytes=512, slots=1))
    with self.path.open('ab') as stream:
      stream.truncate(manager.limits.file_bytes + 1)
    with mock.patch.object(save_store.os, 'open', wraps=save_store.os.open) as opened:
      with self.assertRaises(SaveCapacityError):
        manager.reload()
    self.assertFalse(any(Path(call.args[0]) == self.path for call in opened.call_args_list))

  def test_crash_before_rename_keeps_old_save_and_reclaims_os_lease(self):
    manager = self.initialize()
    before = self.path.read_bytes()
    result = self.child('''import os,sys
from gfootball.frame_sync.save_system import SaveManager
from gfootball.frame_sync import save_store
m=SaveManager(path=sys.argv[1])
save_store.os.replace=lambda *args: os._exit(37)
m.save('s', {'money': 999})
''')
    self.assertEqual(result.returncode, 37, result.stderr)
    self.assertEqual(self.path.read_bytes(), before)
    orphans = [path for path in self.payloads() if path != self.path]
    self.assertEqual(len(orphans), 1)
    manager.save('s', {'money': 11})
    self.assertEqual(self.manager().load('s'), {'money': 11})
    self.assertTrue(orphans[0].exists(), 'Unknown interrupted output must be preserved and charged')

  def test_crash_after_rename_exposes_complete_new_collection(self):
    self.initialize()
    result = self.child('''import os,sys
from gfootball.frame_sync.save_system import SaveManager
from gfootball.frame_sync import save_store
m=SaveManager(path=sys.argv[1])
replace=save_store.os.replace
def commit_then_exit(*args):
  replace(*args)
  os._exit(38)
save_store.os.replace=commit_then_exit
m.save('s', {'money': 12})
''')
    self.assertEqual(result.returncode, 38, result.stderr)
    self.assertEqual(self.manager().load('s'), {'money': 12})
    self.assertEqual(self.payloads(), [self.path])

  def test_post_publication_release_error_keeps_memory_consistent(self):
    manager = self.initialize()
    release = manager._store.directory.release
    def fail_after_release(lease):
      release(lease)
      raise OSError('release reported a terminal error')
    with mock.patch.object(manager._store.directory, 'release', side_effect=fail_after_release):
      with self.assertRaises(OSError) as raised:
        manager.save('s', {'money': 13})
    self.assertTrue(raised.exception.save_committed)
    self.assertEqual(manager.load('s'), {'money': 13})
    self.assertEqual(self.manager().load('s'), {'money': 13})
    self.assertEqual(self.payloads(), [self.path])

  def test_partial_write_failure_releases_actual_stream_and_temp(self):
    manager = self.initialize()
    before = self.path.read_bytes()
    original = save_store.os.fdopen
    streams = []
    class FailingStream:
      def __init__(self, stream):
        self.stream = stream
      def write(self, data):
        self.stream.write(data[:10])
        raise OSError('injected partial write')
      def close(self):
        self.stream.close()
    def fdopen(fd, mode, **kwargs):
      stream = original(fd, mode, **kwargs)
      if mode == 'wb':
        streams.append(stream)
        return FailingStream(stream)
      return stream
    with mock.patch.object(save_store.os, 'fdopen', side_effect=fdopen):
      with self.assertRaisesRegex(OSError, 'partial write'):
        manager.save('s', {'money': 99})
    self.assertTrue(streams and all(stream.closed for stream in streams))
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(manager.load('s'), {'money': 10})
    self.assertEqual(self.payloads(), [self.path])

  def test_external_change_during_write_is_detected_before_publication(self):
    manager = self.initialize()
    with tempfile.TemporaryDirectory(prefix='football-save-external-test-') as folder:
      other_path = Path(folder) / 'other.saves'
      with SaveManager(path=other_path) as other:
        other.create_slot('s', 'Career', SaveType.PROGRESS)
        other.save('s', {'money': 33})
      externally_changed = other_path.read_bytes()
    fsync = save_store.os.fsync
    def external_write(fd):
      fsync(fd)
      self.path.write_bytes(externally_changed)
    with mock.patch.object(save_store.os, 'fsync', side_effect=external_write):
      with self.assertRaises(SaveConflictError):
        manager.save('s', {'money': 99})
    self.assertEqual(self.path.read_bytes(), externally_changed)
    self.assertEqual(manager.load('s'), {'money': 10})
    manager.reload()
    self.assertEqual(manager.load('s'), {'money': 33})
    self.assertEqual(self.payloads(), [self.path])

  def test_two_real_processes_one_revision_has_only_one_winner(self):
    self.initialize()
    code = '''import pathlib,sys,time
from gfootball.frame_sync.save_system import SaveManager,SaveConflictError
p=pathlib.Path(sys.argv[1]); value=int(sys.argv[2]); m=SaveManager(path=p)
(p.parent/('ready-'+str(value))).write_text('ready')
deadline=time.monotonic()+8
while not (p.parent/'go').exists():
  if time.monotonic()>deadline: raise TimeoutError('start signal')
  time.sleep(.005)
try:
  m.save('s', {'money':value})
  print('saved',flush=True)
except SaveConflictError:
  print('conflict',flush=True)
m.close()
'''
    processes = []
    try:
      for value in (21, 22):
        processes.append(subprocess.Popen([sys.executable, '-c', code, str(self.path), str(value)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
      deadline = time.monotonic() + 8
      while not all((self.directory / ('ready-' + str(value))).exists() for value in (21, 22)):
        self.assertLess(time.monotonic(), deadline)
        self.assertTrue(all(process.poll() is None for process in processes))
        time.sleep(.005)
      (self.directory / 'go').write_text('start')
      results = []
      for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        results.append(stdout.strip())
      self.assertEqual(sorted(results), ['conflict', 'saved'])
      self.assertIn(self.manager().load('s')['money'], (21, 22))
    finally:
      for process in processes:
        if process.poll() is None:
          process.kill()
        process.communicate(timeout=3)
    self.assertFalse(_lock_descriptors)

  def test_near_capacity_collection_roundtrips_in_actual_fresh_process(self):
    manager = self.manager()
    for index in range(10):
      manager.create_slot('s%d' % index, 'Save %d' % index)
    for index in range(8):
      manager.save('s%d' % index, {'records': [chr(65 + index) * 65536] * 15})
    before = hashlib.sha256(self.path.read_bytes()).hexdigest()
    with self.assertRaises(SaveCapacityError):
      manager.save('s8', {'records': ['Z' * 65536] * 15})
    self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
    self.assertGreater(self.path.stat().st_size, 7800000)
    self.assertLessEqual(self.path.stat().st_size, manager.limits.file_bytes)
    result = self.child('''import sys
from gfootball.frame_sync.save_system import SaveManager
with SaveManager(path=sys.argv[1]) as m:
  assert len(m.list_slots())==10
  for i in range(8):
    assert m.load('s%d'%i)=={'records':[chr(65+i)*65536]*15}
  assert m.load('s8')=={} and m.load('s9')=={}
  assert m.get_storage_usage()['total_bytes']>7800000
''')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.payloads(), [self.path])


if __name__ == '__main__':
  unittest.main()
