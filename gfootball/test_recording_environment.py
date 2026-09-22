# 2026-09-09: actual legacy entrypoint / native CoreAction integration.
# Requires the installed gfootball native engine, Gym, absl and six in WSL/Linux.
# This suite never installs replacement native modules or copies class bodies.
from pathlib import Path
import pickle
import tempfile
import unittest

import cv2
import numpy as np

from gfootball.env import config, football_action_set, observation_processor
from gfootball.recording_buffers import RecordingCapacityError


class RecordingEnvironmentTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory(prefix='football-recording-env-')
    self.addCleanup(self.directory.cleanup)

  def payloads(self):
    from gfootball.recording_directory import CONTROL_NAME, METADATA_BYTES, SLOTS
    directory = Path(self.directory.name)
    control = directory / CONTROL_NAME
    if control.exists():
      self.assertTrue(control.is_dir())
      self.assertFalse(control.is_symlink())
      metadata = list(control.iterdir())
      self.assertLessEqual(len(metadata), 2 * SLOTS + 1)
      self.assertTrue(all(path.is_file() and path.stat().st_size <= METADATA_BYTES for path in metadata))
    return sorted(path for path in directory.iterdir() if path.name != CONTROL_NAME)

  def processor(self, **options):
    values = dict(tracesdir=self.directory.name, write_video=False,
                  dump_full_episodes=True, display_game_stats=False,
                  render_resolution_x=64, render_resolution_y=48,
                  video_quality_level=1)
    values.update(options)
    result = observation_processor.ObservationProcessor(config.Config(values))
    self.addCleanup(result.close, finalize=False)
    return result

  def trace(self, frame=0):
    return dict(observation={'frame': np.full((48, 64, 3), frame, np.uint8),
                              'ball': np.zeros(3), 'score': [0, 0]},
                debug={'frame_cnt': frame, 'action': [football_action_set.action_left]},
                reward=0.0, cumulative_reward=0.0)

  def read(self, path):
    values = []
    with open(path, 'rb') as stream:
      while True:
        try:
          values.append(pickle.load(stream))
        except EOFError:
          return values

  def test_native_action_roundtrip_and_first_record_config_without_trace_mutation(self):
    processor = self.processor()
    processor.write_dump('episode_done')
    original = self.trace()
    processor.update(original)
    processor.update(self.trace(1))
    result = processor.close()
    self.assertEqual(len(result), 1)
    records = self.read(result[0]['dump'])
    self.assertEqual([value['debug']['frame_cnt'] for value in records], [0, 1])
    action = records[0]['debug']['action'][0]
    self.assertIs(type(action), football_action_set.CoreAction)
    self.assertEqual(int(action._backend_action), int(football_action_set.action_left._backend_action))
    self.assertEqual(action._name, 'left')
    self.assertIn('config', records[0]['debug'])
    self.assertNotIn('config', records[1]['debug'])
    self.assertNotIn('config', original['debug'])
    self.assertIn('frame', original['observation'])
    self.assertTrue(all('frame' not in value['observation'] for value in records))
    self.assertEqual(processor.recording_stats()['active_dumps'], 0)

  def test_zero_preceding_steps_excludes_existing_history(self):
    processor = self.processor()
    for frame in range(3):
      processor.update(self.trace(frame))
    processor.write_dump('episode_done')
    processor.update(self.trace(3))
    records = self.read(processor.close()[0]['dump'])
    self.assertEqual([value['debug']['frame_cnt'] for value in records], [3])

  def test_reset_finalizes_pending_files_and_allows_fresh_history(self):
    processor = self.processor()
    processor.write_dump('episode_done')
    processor.update(self.trace())
    processor.reset()
    paths = list(Path(self.directory.name).glob('*.dump'))
    self.assertEqual(len(paths), 1)
    self.assertEqual(len(self.read(paths[0])), 1)
    self.assertEqual(processor.len(), 0)
    self.assertEqual(processor.pending_dumps(), [])
    processor.update(self.trace(7))
    self.assertEqual(processor[-1]['frame_cnt'], 7)

  def test_start_failure_preserves_attempt_and_clears_active_reservation(self):
    processor = self.processor(recording_output_limits={'dump_bytes': 128})
    processor.update(self.trace())
    with self.assertRaises(RecordingCapacityError):
      processor.write_dump('manual')
    self.assertEqual(processor._dump_config['manual']._max_count, 1)
    self.assertIsNone(processor._dump_config['manual']._active_dump)
    self.assertEqual(processor.recording_stats()['active_dumps'], 0)
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(Path(self.directory.name).iterdir()), [])
    self.assertEqual(self.payloads(), [])

  def test_update_failure_aborts_all_active_writers_and_closes_recorder(self):
    processor = self.processor(recording_output_limits={'dump_bytes': 128})
    processor.write_dump('episode_done')
    with self.assertRaises(RecordingCapacityError):
      processor.update(self.trace())
    self.assertEqual(processor.pending_dumps(), [])
    self.assertEqual(processor.recording_stats()['active_dumps'], 0)
    # 2026-09-09: persistent bounded lock metadata is not a payload file.
    # self.assertEqual(list(Path(self.directory.name).iterdir()), [])
    self.assertEqual(self.payloads(), [])
    with self.assertRaises(RuntimeError):
      processor.update(self.trace())

  def test_public_name_budget_rejects_without_growing_config_table(self):
    processor = self.processor(recording_limits={'dump_names': 4})
    with self.assertRaises(RecordingCapacityError):
      processor.write_dump('extra')
    self.assertEqual(processor.recording_stats()['dump_names'], 4)

  def test_actual_entrypoint_video_includes_steps_and_additional_frames(self):
    processor = self.processor(write_video=True)
    processor.write_dump('episode_done')
    for frame in range(3):
      processor.update(self.trace(frame))
      processor.add_frame(np.full((48, 64, 3), frame + 1, np.uint8))
    result = processor.close()[0]
    self.assertEqual(len(self.read(result['dump'])), 3)
    reader = cv2.VideoCapture(result['video'])
    count = 0
    try:
      self.assertTrue(reader.isOpened())
      while reader.read()[0]:
        count += 1
    finally:
      reader.release()
    self.assertEqual(count, 6)
    self.assertEqual(processor.close(), [])


if __name__ == '__main__':
  unittest.main()
