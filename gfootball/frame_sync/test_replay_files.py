# 2026-09-10: real file round-trips, corruption, quotas, publication and streaming.
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import weakref

from gfootball.frame_sync.replay import (
    Replay, ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFileReader,
    ReplayFormatError, ReplayFrame, ReplayLimits, ReplayManager,
)


class ReplayFileTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-frame-replay-')
    self.root = Path(self.temporary.name).resolve()
    self.parent = Path(tempfile.gettempdir()).resolve()
    self.assertEqual(self.root.parent, self.parent)
    self.assertTrue(self.root.name.startswith('football-frame-replay-'))
    self.identity = self.root.stat().st_dev, self.root.stat().st_ino
    self.addCleanup(self.cleanup)
    self.path = self.root / 'match.jsonl'

  def cleanup(self):
    current = Path(self.temporary.name).resolve()
    if (current != self.root or current.parent != self.parent
        or not current.name.startswith('football-frame-replay-')
        or (current.stat().st_dev, current.stat().st_ino) != self.identity):
      raise RuntimeError('Temporary replay directory identity changed; refusing recursive cleanup')
    self.temporary.cleanup()

  def sample(self, **changes):
    limits = replace(ReplayLimits(frames=1000, events=8, replay_bytes=16 * 1024**2,
                                 total_bytes=32 * 1024**2), **changes)
    replay = Replay('r0', 'm0', '主队', 'Away', 2, 1, created_at=123.25, tick_hz=20, limits=limits)
    for frame in range(10, 16):
      positions = {'p%d' % i: (i + frame / 100, -i, .25) for i in range(22)}
      inputs = {'p%d' % i: {'direction': [1, 0], 'buttons': i, 'enabled': True} for i in range(22)}
      replay.add_frame(ReplayFrame(frame, (1, 2, 3), positions, inputs))
    replay.add_event(ReplayEvent(ReplayEventType.GOAL, 500, 12, 'p2', 'home', {'assist': ['p1'], 'x': 3.5}))
    replay.add_event(ReplayEvent(ReplayEventType.SAVE, 700, 15, 'p20', 'away', {'note': '精彩扑救'}))
    return replay.seal()

  def payload_files(self):
    return sorted(item.name for item in self.root.iterdir() if item.name != '.football-recording-v1')

  def test_complete_round_trip_preserves_positions_inputs_details_and_metadata(self):
    source = self.sample()
    source.save(self.path)
    loaded = Replay.load(self.path, limits=source.limits)
    self.assertTrue(loaded.is_sealed)
    self.assertEqual(loaded.metadata(), source.metadata())
    self.assertEqual(list(loaded.frames), list(source.frames))
    self.assertEqual(list(loaded.events), list(source.events))
    self.assertEqual([event.player_id for event in loaded.get_highlights()], ['p2', 'p20'])
    loaded.cursor().seek(13)
    lines = self.path.read_bytes().splitlines(keepends=True)
    footer = json.loads(lines[-1])
    self.assertEqual(footer['sha256'], hashlib.sha256(b''.join(lines[:-1])).hexdigest())
    self.assertEqual((footer['frames'], footer['events']), (6, 2))

  def test_reader_stays_dependency_free_in_an_actual_fresh_interpreter(self):
    self.sample().save(self.path)
    script = '''import sys
from gfootball.frame_sync.replay import ReplayFileReader
with ReplayFileReader(sys.argv[1]) as reader:
    assert sum(1 for _ in reader) == 8
    assert reader.stats()['verified']
assert 'numpy' not in sys.modules and 'cv2' not in sys.modules
assert 'gfootball_engine' not in sys.modules
print('stdlib replay reader verified')
'''
    result = subprocess.run([sys.executable, '-c', script, str(self.path)], capture_output=True,
                            text=True, encoding='utf-8', timeout=15)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('stdlib replay reader verified', result.stdout)

  def test_streaming_releases_every_previous_record_and_only_verifies_complete_file(self):
    replay = Replay('r0', 'm0', 'Home', 'Away', limits=ReplayLimits(frames=1000))
    for frame in range(1000): replay.add_frame(ReplayFrame(frame, inputs={'p': {'axis': [1, 0]}}))
    replay.seal().save(self.path)
    references = []
    with ReplayFileReader(self.path) as reader:
      for index, record in enumerate(reader):
        self.assertFalse(reader.stats()['verified'])
        self.assertEqual(record.frame_id, index)
        references.append(weakref.ref(record))
        del record
      self.assertTrue(reader.stats()['verified'])
      self.assertEqual(reader.stats()['frames'], 1000)
      self.assertLess(reader.stats()['peak_record_bytes'], 4096)
      with self.assertRaises(StopIteration): next(reader)
    gc.collect()
    self.assertTrue(all(reference() is None for reference in references))

  def test_early_close_releases_descriptor_without_claiming_footer_verification(self):
    self.sample().save(self.path)
    reader = ReplayFileReader(self.path)
    with self.assertRaises(AttributeError): reader.limits = ReplayLimits(file_bytes=1024**3)
    self.assertEqual(next(reader).frame_id, 10)
    reader.close(); reader.close()
    self.assertTrue(reader.stats()['closed'])
    self.assertFalse(reader.stats()['verified'])
    with self.assertRaises(RuntimeError): next(reader)
    self.path.unlink()
    self.assertFalse(self.path.exists())

  def test_tampered_payload_fails_independent_footer_digest(self):
    self.sample().save(self.path)
    data = self.path.read_bytes()
    self.assertIn(b'"ball_pos":[1.0,2.0,3.0]', data)
    self.path.write_bytes(data.replace(b'"ball_pos":[1.0,2.0,3.0]', b'"ball_pos":[9.0,2.0,3.0]', 1))
    with self.assertRaisesRegex(ReplayFormatError, 'integrity'): Replay.load(self.path)

  def test_truncated_files_and_trailing_data_never_load_as_complete_replays(self):
    self.sample().save(self.path)
    valid = self.path.read_bytes()
    for cut in (0, 1, valid.index(b'\n'), len(valid) - 1, len(valid) - 90):
      with self.subTest(cut=cut):
        self.path.write_bytes(valid[:cut])
        with self.assertRaises(ReplayFormatError): Replay.load(self.path)
    self.path.write_bytes(valid + b'\n')
    with self.assertRaisesRegex(ReplayFormatError, 'trailing'): Replay.load(self.path)

  def test_line_and_file_limits_reject_before_full_loading(self):
    self.sample().save(self.path)
    with self.assertRaises(ReplayCapacityError): Replay.load(self.path, limits=ReplayLimits(file_bytes=128))
    with self.assertRaises(ReplayCapacityError): Replay.load(self.path, limits=ReplayLimits(line_bytes=128))
    with self.assertRaises(ReplayFormatError): Replay.load(self.path, limits=ReplayLimits(frames=5))

  def test_duplicate_json_keys_non_finite_and_long_integer_headers_are_rejected(self):
    self.sample().save(self.path)
    valid = self.path.read_bytes()
    cases = [valid.replace(b'"version":1', b'"version":1,"version":1', 1),
             valid.replace(b'"created_at":123.25', b'"created_at":NaN', 1),
             valid.replace(b'"frames":6', b'"frames":' + b'9' * 10000, 1),
             valid.replace(b'"version":1', b'"version":true', 1),
             # 2026-09-10: v2 is the supported native-origin extension; v3 is unknown.
             # valid.replace(b'"version":1', b'"version":2', 1)]
             valid.replace(b'"version":1', b'"version":3', 1)]
    for data in cases:
      self.path.write_bytes(data)
      with self.assertRaises(ReplayFormatError): Replay.load(self.path)

  def test_actual_file_change_during_streaming_closes_reader(self):
    self.sample().save(self.path)
    reader = ReplayFileReader(self.path)
    self.addCleanup(reader.close)
    next(reader)
    with self.path.open('ab') as stream: stream.write(b'foreign append')
    with self.assertRaisesRegex(ReplayFormatError, 'changed'): next(reader)
    self.assertTrue(reader.stats()['closed'])
    self.assertFalse(reader.stats()['verified'])

  def test_output_capacity_and_serialization_failure_preserve_old_target(self):
    self.path.write_bytes(b'previous complete replay')
    small = self.sample(file_bytes=1024)
    with self.assertRaises(ReplayCapacityError): small.save(self.path)
    self.assertEqual(self.path.read_bytes(), b'previous complete replay')
    source = self.sample()
    from gfootball.frame_sync import replay_file
    original = replay_file._encoded
    def encode(value, maximum):
      if value.get('kind') == 'event': raise ValueError('injected serialization failure')
      return original(value, maximum)
    with mock.patch.object(replay_file, '_encoded', encode):
      with self.assertRaisesRegex(ValueError, 'injected'): source.save(self.path)
    self.assertEqual(self.path.read_bytes(), b'previous complete replay')
    self.assertEqual(self.payload_files(), ['match.jsonl'])

  def test_actual_publication_failure_cleans_own_temporary_and_preserves_sibling(self):
    self.path.write_bytes(b'old target')
    sibling = self.root / 'keep.txt'; sibling.write_bytes(b'other data')
    original = os.replace
    def publication(source, target):
      if Path(target) == self.path: raise OSError('injected publication failure')
      return original(source, target)
    with mock.patch('gfootball.replay_io.os.replace', publication):
      with self.assertRaisesRegex(OSError, 'publication'): self.sample().save(self.path)
    self.assertEqual(self.path.read_bytes(), b'old target')
    self.assertEqual(sibling.read_bytes(), b'other data')
    self.assertEqual(self.payload_files(), ['keep.txt', 'match.jsonl'])

  def test_manager_load_is_atomic_on_corruption_duplicate_and_capacity(self):
    source = self.sample(); source.save(self.path)
    manager = ReplayManager(limits=source.limits)
    self.addCleanup(manager.close)
    loaded = manager.load_replay(self.path)
    self.assertEqual(loaded.metadata(), source.metadata())
    before = manager.get_storage_info()
    with self.assertRaises(ReplayFormatError): manager.load_replay(self.path)
    self.assertEqual(manager.get_storage_info(), before)
    self.path.write_bytes(b'corrupt')
    with self.assertRaises(ReplayFormatError): manager.load_replay(self.path)
    self.assertEqual(manager.get_storage_info(), before)
    manager.close()
    with self.assertRaises(RuntimeError): manager.load_replay(self.path)

  def test_empty_round_trip_and_explicit_seal_requirement(self):
    empty = Replay('r0', 'm0', 'Home', 'Away')
    with self.assertRaises(ReplayFormatError): empty.save(self.path)
    self.assertFalse(self.path.exists())
    empty.seal().save(self.path)
    loaded = Replay.load(self.path)
    self.assertEqual((len(loaded.frames), len(loaded.events)), (0, 0))
    with self.assertRaises(ValueError): loaded.save(self.path, directory_limits=False)

  def test_declared_duration_and_record_order_require_more_than_a_valid_digest(self):
    self.sample().save(self.path)
    rows = [json.loads(line) for line in self.path.read_bytes().splitlines()]
    def store(records):
      data = b''.join((json.dumps(item, separators=(',', ':')) + '\n').encode() for item in records[:-1])
      footer = dict(records[-1], sha256=hashlib.sha256(data).hexdigest())
      self.path.write_bytes(data + (json.dumps(footer) + '\n').encode())
    rows[0]['metadata']['duration_ms'] = 0
    store(rows)
    with self.assertRaisesRegex(ReplayFormatError, 'duration'): Replay.load(self.path)
    rows[0]['metadata']['duration_ms'] = 700
    rows[1], rows[2] = rows[2], rows[1]
    store(rows)
    with self.assertRaisesRegex(ReplayFormatError, 'consecutive'): Replay.load(self.path)

  def test_maximum_default_frame_count_persists_and_streams_completely(self):
    replay = Replay('r0', 'm0', 'Home', 'Away')
    for frame in range(100000): replay.add_frame(ReplayFrame(frame))
    replay.seal().save(self.path)
    count, total = 0, 0
    with ReplayFileReader(self.path) as reader:
      for frame in reader:
        count += 1
        total += frame.frame_id
      self.assertTrue(reader.stats()['verified'])
      self.assertLess(reader.stats()['peak_record_bytes'], 1024)
    self.assertEqual((count, total), (100000, 100000 * 99999 // 2))
    self.assertLessEqual(self.path.stat().st_size, replay.limits.file_bytes)

  def test_only_one_staged_import_is_admitted_and_close_cancels_real_open_reader(self):
    self.sample().save(self.path)
    manager = ReplayManager()
    self.addCleanup(manager.close)
    opened, release = threading.Event(), threading.Event()
    original = ReplayFileReader._read
    errors, readers = [], []
    def paused_read(reader):
      if not opened.is_set():
        readers.append(reader)
        opened.set()
        if not release.wait(3): raise AssertionError('Reader release deadline expired')
      return original(reader)
    def load():
      try: manager.load_replay(self.path)
      except BaseException as error: errors.append(error)
    with mock.patch.object(ReplayFileReader, '_read', paused_read):
      worker = threading.Thread(target=load, name='frame-replay-import')
      worker.start()
      try:
        self.assertTrue(opened.wait(3))
        self.assertTrue(manager.get_storage_info()['loading'])
        self.assertEqual(manager.get_storage_info()['staging_limit_bytes'], ReplayLimits().replay_bytes)
        with self.assertRaisesRegex(ReplayCapacityError, 'already in progress'): manager.load_replay(self.path)
        manager.close()
      finally:
        release.set()
        worker.join(5)
      self.assertFalse(worker.is_alive())
    self.assertEqual(len(errors), 1)
    self.assertIsInstance(errors[0], RuntimeError)
    self.assertIn('cancelled', str(errors[0]))
    self.assertTrue(readers[0].stats()['closed'])
    self.assertFalse(manager.get_storage_info()['loading'])
    self.assertEqual(manager.get_storage_info()['retained_bytes'], 0)


if __name__ == '__main__': unittest.main()
