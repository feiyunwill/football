# 2026-09-09: real files/pickle/OpenCV plus targeted I/O failure injection.
import gc
import os
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest import mock
import weakref

import cv2
import numpy as np

from gfootball.recording_buffers import ObservationState, RecordingCapacityError
from gfootball.recording_output import (
    OutputBudget, OutputLimits, RecordingOutput, VideoSettings, _BoundedFile,
)


class RecordingOutputTest(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory(prefix='football-recording-test-')
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)

  def payloads(self):
    from gfootball.recording_directory import CONTROL_NAME, METADATA_BYTES, SLOTS
    directory = self.directory
    control = directory / CONTROL_NAME
    if control.exists():
      self.assertTrue(control.is_dir())
      self.assertFalse(control.is_symlink())
      metadata = list(control.iterdir())
      self.assertLessEqual(len(metadata), 2 * SLOTS + 1)
      self.assertTrue(all(path.is_file() and path.stat().st_size <= METADATA_BYTES for path in metadata))
    return sorted(path for path in directory.iterdir() if path.name != CONTROL_NAME)

  def budget(self, **options):
    return OutputBudget(self.directory, OutputLimits(**options))

  def test_limits_and_video_settings_validate_before_file_creation(self):
    for options in ({'dump_bytes': True}, {'active_dumps': 0}, {'steps': 100001},
                    {'scan_entries': 16385}, {'video_frames': 0}, {'total_bytes': 2**40}):
      with self.assertRaises(ValueError):
        OutputLimits(**options)
    for options in (dict(width=0, height=100, fps=10), dict(width=10, height=10, fps=float('nan')),
                    dict(width=10, height=10, fps=True), dict(width=10, height=10, fps=10, quality=True),
                    dict(width=10, height=10, fps=10, format='../avi')):
      with self.assertRaises(ValueError):
        VideoSettings(**options)
    for stem in ('../escape', 'NUL', 'x/other', 'x:', 'x.', 'x' * 129):
      with self.assertRaises(ValueError):
        RecordingOutput(stem, self.budget())
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_low_quality_scales_both_dimensions_and_preserves_aspect_ratio(self):
    self.assertEqual(VideoSettings(1280, 720, 10).dimensions, (800, 450))
    self.assertEqual(VideoSettings(400, 1000, 10).dimensions, (180, 450))
    self.assertEqual(VideoSettings(2000, 300, 10).dimensions, (800, 120))
    self.assertEqual(VideoSettings(401, 301, 10, quality=1).dimensions, (400, 300))

  def test_actual_pickle_stream_commit_is_repeatable_and_record_is_unchanged(self):
    budget = self.budget()
    image = np.zeros((8, 8, 3), np.uint8)
    state = ObservationState(dict(observation={'frame': image, 'ball': np.zeros(3)}, debug={}))
    output = RecordingOutput('进球_20260909-123456000000', budget)
    for frame in range(4):
      record = state.to_record(include_frame=False, first_config={'seed': 42} if frame == 0 else None)
      record['frame'] = frame
      output.write_step(record)
    self.assertFalse(Path(output.name + '.dump').exists())
    result = output.finalize()
    self.assertEqual(output.finalize(), result)
    with open(result['dump'], 'rb') as stream:
      records = [pickle.load(stream) for _ in range(4)]
      with self.assertRaises(EOFError):
        pickle.load(stream)
    self.assertEqual([item['frame'] for item in records], list(range(4)))
    self.assertEqual(records[0]['debug']['config'], {'seed': 42})
    self.assertNotIn('config', records[1]['debug'])
    self.assertIn('frame', state['observation'])
    self.assertNotIn('config', state['debug'])
    output.abort()  # Explicit/GC cleanup must preserve committed user files.
    del output
    gc.collect()
    self.assertTrue(Path(result['dump']).exists())
    self.assertEqual(budget.stats()['active_dumps'], 0)
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(len(list(self.directory.iterdir())), 1)
    self.assertEqual(len(self.payloads()), 1)

  def test_dump_limit_checked_before_write_and_failed_output_never_publishes(self):
    budget = self.budget(dump_bytes=128)
    output = RecordingOutput('large', budget)
    output.write_step({'first': True})
    with self.assertRaises(RecordingCapacityError):
      output.write_step({'too_large': b'x' * 512})
    self.assertEqual(output.finalize(), {})
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])
    self.assertEqual(budget.stats()['reserved_bytes'], 0)
    with self.assertRaises(RuntimeError):
      output.write_step({})

  def test_step_limit_and_exception_context_abort_only_owned_files(self):
    existing = self.directory / 'user.dump'
    existing.write_bytes(b'user data')
    output = RecordingOutput('limited', self.budget(steps=1))
    output.write_step({})
    with self.assertRaises(RecordingCapacityError):
      output.write_step({})
    with self.assertRaisesRegex(RuntimeError, 'caller failure'):
      with RecordingOutput('context', self.budget()) as output:
        output.write_step({})
        raise RuntimeError('caller failure')
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [existing])
    self.assertEqual(self.payloads(), [existing])
    self.assertEqual(existing.read_bytes(), b'user data')

  def test_no_files_mode_has_no_directory_side_effect_or_encoder(self):
    missing = self.directory / 'not-created'
    budget = OutputBudget(missing)
    with mock.patch('gfootball.recording_output.cv2.VideoWriter', side_effect=AssertionError('unexpected codec')):
      with RecordingOutput('disabled', budget, VideoSettings(32, 32, 10), enabled=False) as output:
        output.write_step({})
        output.write_frame(None)
      self.assertEqual(output.finalize(), {})
    self.assertFalse(missing.exists())
    self.assertEqual(budget.stats()['active_dumps'], 0)

  def test_empty_and_abandoned_outputs_are_removed_without_implicit_commit(self):
    budget = self.budget()
    empty = RecordingOutput('empty', budget)
    self.assertEqual(empty.finalize(), {})
    abandoned = RecordingOutput('abandoned', budget)
    abandoned.write_step({'partial_episode': True})
    reference = weakref.ref(abandoned)
    del abandoned
    gc.collect()
    self.assertIsNone(reference())
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])
    self.assertEqual(budget.stats()['active_dumps'], 0)

  def test_directory_reservation_accounts_existing_bytes_and_previous_sessions(self):
    budget = self.budget(dump_bytes=128, total_bytes=256)
    first = RecordingOutput('first', budget)
    second = RecordingOutput('second', budget)
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('third', budget)
    self.assertEqual(budget.stats(), dict(active_dumps=2, reserved_bytes=256, reserved_files=2))
    first.abort()
    second.abort()
    (self.directory / 'previous.dump').write_bytes(b'x' * 129)
    fresh_session = self.budget(dump_bytes=128, total_bytes=256)
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('next', fresh_session)
    self.assertEqual((self.directory / 'previous.dump').stat().st_size, 129)
    self.assertEqual(fresh_session.stats()['active_dumps'], 0)

  def test_active_file_and_scan_count_limits_release_after_abort(self):
    budget = self.budget(active_dumps=1)
    first = RecordingOutput('first', budget)
    with self.assertRaises(RecordingCapacityError):
      RecordingOutput('second', budget)
    first.abort()
    with RecordingOutput('second', budget) as second:
      second.write_step({})
    for limits in (dict(total_files=1), dict(scan_entries=1)):
      (self.directory / 'external.txt').write_bytes(b'preserve')
      with self.assertRaises(RecordingCapacityError):
        RecordingOutput('third', self.budget(**limits))
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(len(list(self.directory.iterdir())), 2)
    self.assertEqual(len(self.payloads()), 2)

  def test_destination_collision_preserves_existing_file_and_cleans_partial(self):
    final = self.directory / 'collision.dump'
    final.write_bytes(b'original')
    output = RecordingOutput('collision', self.budget())
    output.write_step({'new': True})
    with self.assertRaises(FileExistsError):
      output.finalize()
    self.assertEqual(final.read_bytes(), b'original')
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [final])
    self.assertEqual(self.payloads(), [final])

  def test_publication_failure_aborts_without_reporting_a_successful_dump(self):
    output = RecordingOutput('publish', self.budget())
    output.write_step({})
    with mock.patch('gfootball.recording_output.os.link', side_effect=OSError('link unavailable')):
      with self.assertRaisesRegex(OSError, 'link unavailable'):
        output.finalize()
    self.assertEqual(output.finalize(), {})
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_short_writes_and_no_progress_are_handled_without_exceeding_budget(self):
    class ShortWriter:
      def __init__(self):
        self.value = bytearray()

      def write(self, data):
        self.value.extend(data[:3])
        return min(3, len(data))

    stream = ShortWriter()
    bounded = _BoundedFile(stream, 8)
    self.assertEqual(bounded.write(b'12345678'), 8)
    with self.assertRaises(RecordingCapacityError):
      bounded.write(b'9')
    self.assertEqual(stream.value, b'12345678')
    stream.write = lambda data: 0
    with self.assertRaises(OSError):
      _BoundedFile(stream, 8).write(b'1')

  def test_encoder_open_failure_closes_files_and_refunds_reservation(self):
    budget = self.budget()
    writer = mock.Mock()
    writer.isOpened.return_value = False
    with mock.patch('gfootball.recording_output.cv2.VideoWriter', return_value=writer):
      with self.assertRaisesRegex(OSError, 'could not open'):
        RecordingOutput('failed', budget, VideoSettings(32, 32, 10, quality=1))
    writer.release.assert_called_once()
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])
    self.assertEqual(budget.stats()['reserved_files'], 0)

  def test_real_mjpg_encoder_decodes_every_frame_and_keeps_input_unchanged(self):
    budget = self.budget()
    output = RecordingOutput('video', budget, VideoSettings(64, 48, 10, quality=1))
    for index in range(12):
      frame = np.full((48, 64, 3), index * 16, np.uint8)
      output.write_frame(frame)
      output.write_step({'index': index})
      self.assertTrue(np.all(frame == index * 16))
    self.assertEqual(output.stats()['video_frames'], 12)
    result = output.finalize()
    self.assertEqual(set(result), {'dump', 'video'})
    capture = cv2.VideoCapture(result['video'])
    self.assertTrue(capture.isOpened())
    values = []
    try:
      while True:
        valid, frame = capture.read()
        if not valid:
          break
        self.assertEqual(frame.shape, (48, 64, 3))
        values.append(float(frame.mean()))
    finally:
      capture.release()
    self.assertEqual(len(values), 12)
    np.testing.assert_allclose(values, np.arange(12) * 16, atol=3)
    self.assertEqual(budget.stats()['active_dumps'], 0)
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(len(list(self.directory.iterdir())), 2)
    self.assertEqual(len(self.payloads()), 2)

  def test_video_frame_count_overflow_aborts_all_outputs(self):
    output = RecordingOutput('frames', self.budget(video_frames=1), VideoSettings(64, 48, 10, quality=1))
    frame = np.zeros((48, 64, 3), np.uint8)
    output.write_frame(frame)
    with self.assertRaises(RecordingCapacityError):
      output.write_frame(frame)
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_real_encoder_size_checked_after_release_and_oversize_is_not_published(self):
    # 2026-09-09: either eager header output or delayed flush must reject; the
    # check is backend-independent instead of assuming construction stays small.
    # output = RecordingOutput('bytes', self.budget(video_bytes=128), VideoSettings(64, 48, 10, quality=1))
    output = None
    # Some encoders write a header eagerly, others buffer it until release.
    with self.assertRaises(RecordingCapacityError):
      output = RecordingOutput('bytes', self.budget(video_bytes=128), VideoSettings(64, 48, 10, quality=1))
      output.write_frame(np.zeros((48, 64, 3), np.uint8))
      output.finalize()
    # 2026-09-09: a constructor rejection has no returned output owner.
    # self.assertEqual(output.finalize(), {})
    if output is not None:
      self.assertEqual(output.finalize(), {})
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_second_destination_collision_rolls_back_first_link_only(self):
    existing = self.directory / 'pair.avi'
    existing.write_bytes(b'user video')
    output = RecordingOutput('pair', self.budget(), VideoSettings(64, 48, 10, quality=1))
    output.write_step({})
    output.write_frame(np.zeros((48, 64, 3), np.uint8))
    with self.assertRaises(FileExistsError):
      output.finalize()
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [existing])
    self.assertEqual(self.payloads(), [existing])
    self.assertEqual(existing.read_bytes(), b'user video')

  def test_pickle_and_disk_failures_close_stream_without_changing_observation(self):
    class CannotSerialize:
      def __reduce__(self):
        raise ValueError('serialization failure')

    state = ObservationState(dict(observation={'frame': np.zeros((8, 8, 3), np.uint8)}, debug={}))
    for disk_error in (False, True):
      budget = self.budget()
      output = RecordingOutput('failure', budget)
      stream = output._dump.stream
      record = state.to_record(include_frame=False)
      if disk_error:
        with mock.patch.object(output._dump, 'write', side_effect=OSError('disk full')):
          with self.assertRaisesRegex(OSError, 'disk full'):
            output.write_step(record)
      else:
        record['bad'] = CannotSerialize()
        with self.assertRaisesRegex(ValueError, 'serialization failure'):
          output.write_step(record)
      self.assertTrue(stream.closed)
      self.assertIn('frame', state['observation'])
      # 2026-09-09: persistent bounded lock metadata is not a payload file.
      # self.assertEqual(list(self.directory.iterdir()), [])
      self.assertEqual(self.payloads(), [])
      self.assertEqual(budget.stats()['active_dumps'], 0)

  def test_encoder_write_and_release_failures_close_real_encoder_and_dump(self):
    original = cv2.VideoWriter
    for fail_release in (False, True):
      native = []

      def factory(*args):
        writer = original(*args)
        native.append(writer)
        wrapped = mock.Mock(wraps=writer)
        if fail_release:
          def release():
            writer.release()
            raise OSError('release failed')
          wrapped.release.side_effect = release
        else:
          wrapped.write.side_effect = OSError('write failed')
        return wrapped

      budget = self.budget()
      with mock.patch('gfootball.recording_output.cv2.VideoWriter', side_effect=factory):
        output = RecordingOutput('codec_error', budget, VideoSettings(64, 48, 10, quality=1))
      stream = output._dump.stream
      with self.assertRaisesRegex(OSError, 'release failed' if fail_release else 'write failed'):
        output.write_frame(np.zeros((48, 64, 3), np.uint8))
        output.finalize()
      self.assertFalse(native[0].isOpened())
      self.assertTrue(stream.closed)
      # 2026-09-09: persistent bounded lock metadata is not a payload file.
      # self.assertEqual(list(self.directory.iterdir()), [])
      self.assertEqual(self.payloads(), [])
      self.assertEqual(budget.stats()['active_dumps'], 0)

  def test_abort_failure_does_not_hide_original_error_and_later_cleanup_can_retry(self):
    output = RecordingOutput('cleanup_error', self.budget(dump_bytes=128))
    with mock.patch('gfootball.recording_output._unlink_owned', side_effect=OSError('permission denied')):
      with self.assertRaisesRegex(RecordingCapacityError, 'Dump file byte budget'):
        output.write_step({'large': b'x' * 512})
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertTrue(list(self.directory.iterdir()))
    self.assertTrue(self.payloads())
    output.abort()
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(self.directory.iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_repeated_real_file_and_encoder_abort_refunds_all_reservations(self):
    budget = self.budget()
    for iteration in range(200):
      video = VideoSettings(64, 48, 10, quality=1) if iteration % 20 == 0 else None
      output = RecordingOutput('cycle', budget, video)
      output.write_step({'iteration': iteration})
      if video is not None:
        output.write_frame(np.zeros((48, 64, 3), np.uint8))
      output.abort()
      self.assertEqual(budget.stats(), dict(active_dumps=0, reserved_bytes=0, reserved_files=0))
      # 2026-09-09: persistent bounded lock metadata is not a payload file.
      # self.assertEqual(list(self.directory.iterdir()), [])
      self.assertEqual(self.payloads(), [])


if __name__ == '__main__':
  unittest.main()
