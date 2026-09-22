# 2026-09-10: record ownership and validation against independently inspected data.
from dataclasses import FrozenInstanceError, replace
import json
import math
import unittest

from gfootball.frame_sync.replay import (
    ReplayCapacityError, ReplayEvent, ReplayEventType, ReplayFormatError, ReplayFrame, ReplayLimits,
)


class ReplayRecordTest(unittest.TestCase):
  def test_frame_owns_nested_inputs_and_serializes_every_field(self):
    positions = {'left-1': [1, 2, 3]}
    actions = {'left-1': {'direction': [1, 0], 'buttons': {'kick': True}}}
    frame = ReplayFrame(12, [4, 5, 6], positions, actions)
    positions['left-1'][0] = 100
    actions['left-1']['direction'][0] = -1
    self.assertEqual(frame.player_positions['left-1'], (1, 2, 3))
    self.assertEqual(frame.inputs['left-1']['direction'], (1, 0))
    with self.assertRaises(FrozenInstanceError): frame.frame_id = 13
    with self.assertRaises(TypeError): frame.inputs['left-1']['buttons']['kick'] = False
    output = frame.to_dict()
    self.assertEqual(set(output), {'frame_id', 'ball_pos', 'player_positions', 'inputs'})
    output['inputs']['left-1']['direction'][0] = 5
    self.assertEqual(frame.inputs['left-1']['direction'], (1, 0))
    self.assertEqual(ReplayFrame.from_dict(json.loads(json.dumps(frame.to_dict()))), frame)

  def test_event_owns_details_and_preserves_round_trip(self):
    details = {'assist': {'player': 'p2', 'path': [3, 4]}, 'reason': '精彩进球'}
    event = ReplayEvent(ReplayEventType.GOAL, 45000, 450, 'p1', 'home', details)
    details['assist']['path'].append(99)
    self.assertEqual(event.details['assist']['path'], (3, 4))
    with self.assertRaises(FrozenInstanceError): event.timestamp_ms = 0
    exported = event.to_dict()
    exported['details']['assist']['path'].append(11)
    self.assertEqual(event.details['assist']['path'], (3, 4))
    self.assertEqual(ReplayEvent.from_dict(json.loads(json.dumps(event.to_dict()))), event)

  def test_limits_reject_invalid_types_and_inconsistent_aggregate(self):
    for value in (False, -1, 0, 1.5, math.inf, 1000001):
      with self.subTest(value=value), self.assertRaises(ValueError): ReplayLimits(frames=value)
    with self.assertRaises(ValueError): ReplayLimits(replay_bytes=8192, total_bytes=4096)
    with self.assertRaises(ValueError): ReplayLimits(frame_bytes=65537)
    self.assertEqual(replace(ReplayLimits(), frames=1).frames, 1)

  def test_invalid_positions_and_player_map_reject_before_record_admission(self):
    for value in ([1, 2], [1, 2, 3, 4], [True, 0, 0], [math.inf, 0, 0], [math.nan, 0, 0], [1e30, 0, 0]):
      with self.subTest(value=value), self.assertRaises(ReplayFormatError): ReplayFrame(0, value)
    with self.assertRaises(ReplayFormatError): ReplayFrame(0, player_positions={str(i): (0, 0, 0) for i in range(23)})
    with self.assertRaises(ReplayFormatError): ReplayFrame(0, inputs={'p': [1, 2]})
    frame = ReplayFrame(0, player_positions={str(i): (0, 0, 0) for i in range(22)})
    self.assertEqual(len(frame.player_positions), 22)

  def test_cycles_depth_and_node_growth_are_bounded(self):
    cycle = {}; cycle['self'] = cycle
    with self.assertRaises(ReplayFormatError): ReplayEvent(ReplayEventType.GOAL, 0, 0, details=cycle)
    nested = 0
    for _ in range(10): nested = [nested]
    with self.assertRaises(ReplayCapacityError): ReplayEvent(ReplayEventType.GOAL, 0, 0, details={'value': nested})
    with self.assertRaises(ReplayCapacityError):
      ReplayEvent(ReplayEventType.GOAL, 0, 0, details={str(i): list(range(100)) for i in range(30)})

  def test_record_byte_capacity_does_not_depend_only_on_node_count(self):
    with self.assertRaises(ReplayCapacityError):
      ReplayEvent(ReplayEventType.GOAL, 0, 0, details={str(i): 'x' * 4096 for i in range(18)})
    event = ReplayEvent(ReplayEventType.GOAL, 0, 0, details={'text': 'x' * 4096})
    self.assertGreater(event.retained_bytes, 4096)
    self.assertLess(event.retained_bytes, 65536)

  def test_non_json_values_and_non_finite_numbers_are_rejected(self):
    for value in (b'bytes', object(), complex(1, 2), math.inf, math.nan, 2**63, -(2**63) - 1):
      with self.subTest(value=type(value)), self.assertRaises(ReplayFormatError):
        ReplayEvent(ReplayEventType.GOAL, 0, 0, details={'value': value})
    event = ReplayEvent(ReplayEventType.GOAL, 0, 0, details={'min': -(2**63), 'max': 2**63 - 1})
    self.assertEqual(event.to_dict()['details']['max'], 2**63 - 1)

  def test_ids_timestamps_and_unicode_are_strict(self):
    for value in (True, -1, 2**32, 1.0):
      with self.subTest(value=value), self.assertRaises(ReplayFormatError): ReplayFrame(value)
    for value in ('', '\0', '\ud800', '汉' * 50):
      with self.subTest(value=repr(value)), self.assertRaises(ReplayFormatError):
        ReplayEvent(ReplayEventType.GOAL, 0, 0, player_id=value)
    with self.assertRaises(ReplayFormatError): ReplayEvent('goal', 0, 0)
    with self.assertRaises(ReplayFormatError): ReplayEvent(ReplayEventType.GOAL, True, 0)

  def test_serialized_schema_rejects_missing_and_unknown_fields(self):
    frame = ReplayFrame(0).to_dict()
    with self.assertRaises(ReplayFormatError): ReplayFrame.from_dict({'frame_id': 0, 'ball_pos': [0, 0, 0]})
    with self.assertRaises(ReplayFormatError): ReplayFrame.from_dict(dict(frame, unexpected=1))
    event = ReplayEvent(ReplayEventType.GOAL, 0, 0).to_dict()
    with self.assertRaises(ReplayFormatError): ReplayEvent.from_dict(dict(event, event_type='unknown'))
    del event['details']
    with self.assertRaises(ReplayFormatError): ReplayEvent.from_dict(event)

  def test_record_instance_dictionary_cannot_bypass_frozen_fields(self):
    for value in (ReplayFrame(0), ReplayEvent(ReplayEventType.GOAL, 0, 0)):
      with self.assertRaises(AttributeError): getattr(value, '__dict__')
      with self.assertRaises(FrozenInstanceError): value._bytes = 0


if __name__ == '__main__': unittest.main()
