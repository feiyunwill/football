# 2026-09-10: actual match-v6 socket coverage now lives in its dedicated suite.
# The production match transports still negotiate v5. These checks exercise the
# new codec, actual prediction loop and actual input buffer, without claiming a
# TCP/UDP pause handshake or a native/device acceptance run.
"""v6 execution primitives with an explicit independent engine, not GameEnv.

These checks exercise the codec, actual prediction loop and actual input buffer.
Actual v6 socket pause handshakes are in test_match_pause_network; neither suite
claims a native/device acceptance run.
"""
from dataclasses import FrozenInstanceError
import struct
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.client_logic import ClientLogicLoop, LogicLimits
from gfootball.frame_sync.graphical_input import InputBuffer
from gfootball.frame_sync.presentation_state import LogicStateHolder
from gfootball.frame_sync.match_control import (
    MatchControl, RUNNING, PAUSED, RESUMING, MAX_EPOCH, MAX_FRAME,
    pack_control, unpack_control, pack_control_ack, unpack_control_ack,
    pack_epoch_input, unpack_epoch_input, parse_control_metadata)
from gfootball.frame_sync.server_state import FrameInputWindow, ServerLimits, ServerFailure
from gfootball.frame_sync.test_client_logic_budget import Client, Engine, packed


class MatchControlCodecTest(unittest.TestCase):
  def test_control_has_independent_little_endian_golden(self):
    control = MatchControl(0x12345678, PAUSED, 0x10203040, 0x0102030405060708)
    golden = bytes.fromhex('13 78563412 01 40302010 0807060504030201')
    self.assertEqual(pack_control(control), golden)
    self.assertEqual(unpack_control(golden), control)
    with self.assertRaises(FrozenInstanceError):
      control.phase = RUNNING

  def test_ack_has_independent_golden_and_cannot_ack_running(self):
    control = MatchControl(0x12345678, RESUMING, 9, 0x0102030405060708)
    golden = bytes.fromhex('14 78563412 09000000 0807060504030201')
    self.assertEqual(pack_control_ack(control), golden)
    self.assertEqual(unpack_control_ack(golden), (0x12345678, 9, 0x0102030405060708))
    with self.assertRaises(ValueError):
      pack_control_ack(MatchControl(2, RUNNING, 9, 1))

  def test_epoch_input_preserves_wire_slot_float32_and_buttons(self):
    value = wire.SlotInput(.5, -1., 4)
    golden = bytes.fromhex('15 02000000 09000000 0100 0100 0000003f 000080bf 0400')
    self.assertEqual(pack_epoch_input(2, 9, [(1, value)]), golden)
    epoch, ordinary = unpack_epoch_input(golden, 2)
    self.assertEqual(epoch, 2)
    self.assertEqual(ordinary, bytes.fromhex('02 09000000 0100 0100 0000003f 000080bf 0400'))
    self.assertEqual(wire.unpack_client_frame_input(ordinary), (9, [(1, value)]))

  def test_metadata_and_integer_fields_are_strict_and_bounded(self):
    valid = dict(epoch=0, phase=RUNNING, next_frame=0, state_hash=0)
    for field, values in {'epoch': (True, -1, MAX_EPOCH + 1), 'phase': (False, -1, 3),
                          'next_frame': (1., -1, MAX_FRAME + 1),
                          'state_hash': (True, -1, 1 << 64)}.items():
      for value in values:
        with self.subTest(field=field, value=value), self.assertRaises(ValueError):
          MatchControl(**dict(valid, **{field: value}))
    for metadata in ({}, {'epoch': 1, 'phase': 1, 'extra': 3}, {'epoch': True, 'phase': 1}, []):
      with self.assertRaises(ValueError):
        parse_control_metadata(metadata, 0, 0)
    control = MatchControl(1, PAUSED, 7, 11)
    metadata = control.metadata()
    self.assertEqual(parse_control_metadata(metadata, 7, 11), control)
    metadata['epoch'] = 77
    self.assertEqual(control.epoch, 1)

  def test_only_pause_prepare_and_commit_form_valid_transitions(self):
    states = [MatchControl(0, RUNNING, 0, 7), MatchControl(1, PAUSED, 9, 11),
              MatchControl(2, RESUMING, 9, 11), MatchControl(2, RUNNING, 9, 11),
              MatchControl(3, PAUSED, 12, 15)]
    for index, previous in enumerate(states):
      self.assertFalse(previous.validate_after(previous))
      if index + 1 < len(states):
        self.assertTrue(states[index + 1].validate_after(previous))
    invalid = [MatchControl(2, RUNNING, 9, 11), MatchControl(3, RESUMING, 9, 11),
               MatchControl(2, RESUMING, 10, 11), MatchControl(2, RESUMING, 9, 12),
               MatchControl(1, RUNNING, 9, 11), MatchControl(0, RUNNING, 0, 7)]
    for state in invalid:
      with self.assertRaises(ValueError):
        state.validate_after(states[1])
    with self.assertRaises(ValueError):
      MatchControl(2, RUNNING, 9, 12).validate_after(states[2])

  def test_fixed_packets_reject_truncation_suffix_type_and_invalid_phase(self):
    for pack, unpack in ((pack_control, unpack_control), (pack_control_ack, unpack_control_ack)):
      packet = pack(MatchControl(1, PAUSED, 0, 1))
      for bad in [packet[:n] for n in range(len(packet))] + [packet + b'\0', b'\0' + packet[1:], bytearray(packet)]:
        with self.assertRaises(ValueError):
          unpack(bad)
    for packet in (bytes.fromhex('13 00000000 01 00000000 0000000000000000'),
                   bytes.fromhex('13 01000000 03 00000000 0000000000000000')):
      with self.assertRaises(ValueError):
        unpack_control(packet)
    with self.assertRaises(ValueError):
      unpack_control_ack(bytes.fromhex('14 00000000 00000000 0000000000000000'))

  def test_input_shape_and_sender_values_reject_without_masking(self):
    valid = [(0, wire.default_slot_input())]
    packet = pack_epoch_input(0, 0, valid)
    for bad in [packet[:n] for n in range(len(packet))] + [packet + b'\0', b'\2' + packet[1:], bytearray(packet)]:
      with self.assertRaises(ValueError):
        unpack_epoch_input(bad)
    for entries in ([], valid * 23, valid * 2, [(65536, valid[0][1])], [(True, valid[0][1])],
                    [(0, wire.SlotInput(float('nan'), 0, 0))], [(0, wire.SlotInput(0, 0, 4096))],
                    [(0, wire.SlotInput(False, 0, 0))], iter(valid)):
      with self.assertRaises(ValueError):
        pack_epoch_input(0, 0, entries)
    for slots in (0, 23, True):
      with self.assertRaises(ValueError):
        unpack_epoch_input(packet, slots)

  def test_converted_input_still_uses_real_window_validation_and_budget(self):
    window = FrameInputWindow(ServerLimits(), 2)
    epoch, ordinary = unpack_epoch_input(pack_epoch_input(2, 0, [(1, wire.SlotInput(.5, 0, 4))]), 2)
    self.assertEqual(epoch, 2)
    self.assertEqual(window.accept(ordinary, (1,)), 'accepted')
    self.assertEqual(window.accept(ordinary, (1,)), 'duplicate')
    baseline = window.stats()
    bad_packets = [ordinary[:7] + b'\x02\x00' + ordinary[9:],
                   ordinary[:9] + struct.pack('<f', float('nan')) + ordinary[13:],
                   ordinary[:-2] + b'\x00\x10']
    for bad in bad_packets:
      with self.assertRaises(ServerFailure):
        window.accept(bad, (1,))
      self.assertEqual(window.stats(), baseline)
    window.clear()
    self.assertEqual(window.stats()['payload_bytes'], 0)

  def test_epoch_exhaustion_cannot_wrap_or_skip_resume_preparation(self):
    previous = MatchControl(MAX_EPOCH, PAUSED, 12, 9)
    with self.assertRaises(ValueError):
      MatchControl(0, RUNNING, 12, 9).validate_after(previous)
    with self.assertRaises(ValueError):
      MatchControl(MAX_EPOCH, RUNNING, 12, 9).validate_after(previous)
    for epoch in (True, -1, MAX_EPOCH + 1):
      with self.assertRaises(ValueError):
        pack_epoch_input(epoch, 0, [(0, wire.default_slot_input())])


class ControlTransport(Client):
  """Controlled single-owner delivery fixture; intentionally has no sockets."""
  def __init__(self):
    super().__init__()
    self.control = None
    self.acks = []
    self.polls = 0
    self.accept_ack = True
    self.on_ack = lambda control: None
    self.commits = []

  def get_match_control(self):
    return self.control

  def acknowledge_control(self, control):
    self.on_ack(control)
    if not self.accept_ack:
      return False
    self.acks.append(control)
    return True

  def tick_disconnect_detection(self):
    self.polls += 1

  def commit_control(self, control):
    self.commits.append(control)
    return True


class MatchControlLogicTest(unittest.TestCase):
  def make(self, **options):
    self.client, self.env, self.authority, self.inputs = ControlTransport(), Engine(), Engine(), InputBuffer()
    self.samples, self.notifications = [], []
    self.now = 0.
    def sample():
      value = self.inputs.sample()
      self.samples.append((self.logic.control_state.epoch, self.logic.get_current_frame_id(), value))
      return [(0, value)]
    def control(state):
      self.notifications.append(state)
      self.inputs.set_suspended(state.phase != RUNNING)
    self.logic = ClientLogicLoop(self.client, self.env, 2, sample, on_control=control,
                                clock=lambda: self.now, **options)
    self.addCleanup(self.logic.stop)
    self.addCleanup(self.inputs.close)
    self.client.control = MatchControl(0, RUNNING, 0, wire.compute_state_hash(self.env.get_state_digest()))
    self.logic.initialize_control(self.client.control)
    return self.logic

  def deliver_authority(self, count, values=None, hashes=False):
    values = values or [wire.default_slot_input()] * 2
    for _ in range(count):
      frame = self.authority.frame
      self.authority.step_with_input(packed(values))
      self.client.auth.append((frame, values))
      if hashes:
        self.client.hashes.append((frame, wire.compute_state_hash(self.authority.get_state_digest())))

  def pause(self):
    self.client.control = MatchControl(self.client.control.epoch + 1, PAUSED, self.authority.frame,
                                       wire.compute_state_hash(self.authority.get_state_digest()))

  def prepare(self):
    previous = self.client.control
    self.client.control = MatchControl(previous.epoch + 1, RESUMING, previous.next_frame, previous.state_hash)

  def commit(self):
    previous = self.client.control
    self.client.control = MatchControl(previous.epoch, RUNNING, previous.next_frame, previous.state_hash)

  def assert_released(self):
    for key in ('history_frames', 'history_bytes', 'sampled_input_frames', 'input_timestamps'):
      self.assertEqual(self.logic.stats()[key], 0, key)

  def test_prediction_rewinds_and_old_epoch_shot_cannot_reappear_after_resume(self):
    logic = self.make()
    self.inputs.feed(keys=('z', 'w'))
    for _ in range(4):
      logic.run_one_tick()
    old_samples = tuple(self.samples)
    self.deliver_authority(2, [wire.default_slot_input(), wire.SlotInput(1, 0, 8)])
    self.pause()
    observed = []
    self.client.on_ack = lambda control: observed.append((self.env.get_state_digest(), self.inputs.sample(), logic.stats()))
    logic.run_one_tick()
    self.assertEqual(self.env.get_state_digest(), self.authority.get_state_digest())
    self.assertEqual(logic.get_current_frame_id(), 2)
    self.assertGreater(logic.get_rollback_count(), 0)
    self.assertEqual(tuple(self.samples), old_samples)
    self.assert_released()
    self.assertEqual(observed[0][0], self.authority.get_state_digest())
    self.assertEqual(observed[0][1], wire.default_slot_input())
    self.assertEqual(observed[0][2]['sampled_input_frames'], 0)
    self.prepare()
    logic.run_one_tick()
    self.inputs.feed(pressed_keys=('v',), keys=('z', 'w'))
    self.commit()
    logic.run_one_tick()
    self.assertEqual(self.samples[-1], (2, 2, wire.default_slot_input()))
    # Remote held input is neutral too, until the next authority supplies it.
    self.assertEqual(self.env.steps[-1], b'\0' * 20)
    self.inputs.feed()
    self.inputs.feed(pressed_keys=('z',))
    logic.run_one_tick()
    self.assertEqual(self.samples[-1][2].buttons, 4)
    self.assertEqual(self.client.acks, self.notifications[1:3])

  def test_pause_freezes_sampling_immediately_but_catchup_remains_bounded(self):
    logic = self.make(limits=LogicLimits(catchup_frames=1))
    self.deliver_authority(4)
    self.pause()
    self.inputs.feed(pressed_keys=('z',))
    for frame in range(4):
      logic.run_one_tick()
      self.assertEqual(logic.get_last_confirmed_frame_id(), frame)
      self.assertEqual(self.samples, [])
      self.assertEqual(self.inputs.sample(), wire.default_slot_input())
      self.assertEqual(len(self.client.acks), int(frame == 3))
    self.assertEqual(self.env.frame, 4)
    self.assertEqual(len(self.notifications), 2)

  def test_pause_publishes_authoritative_rewind_and_does_not_repeat_snapshot_work(self):
    holder = LogicStateHolder(clock=lambda: 1.)
    self.addCleanup(holder.close)
    logic = self.make(state_holder=holder)
    self.inputs.feed(keys=('z',))
    for _ in range(4):
      logic.run_one_tick()
    # 2026-09-10: the fourth unanswered tick samples but enters authority-only
    # mode. Three predictions already exceed the two-frame pause boundary.
    # self.assertEqual(holder.read_sample().frame_id, 3)
    self.assertEqual(holder.read_sample().frame_id, 2)
    self.assertEqual(logic.get_current_frame_id(), 3)
    self.deliver_authority(2)
    self.pause()
    logic.run_one_tick()
    sample = holder.read_sample()
    self.assertEqual((sample.frame_id, sample.confirmed_frame_id), (1, 1))
    self.assertEqual(sample.state, self.authority.get_state(''))
    self.assertTrue(sample.waiting_for_authority)
    self.assertTrue(sample.discontinuity)
    self.assertEqual(holder.buffer_depth, 1)
    baseline = self.env.saves
    for _ in range(100):
      logic.run_one_tick()
    self.assertEqual(self.env.saves, baseline)
    self.assertIs(holder.read_sample(), sample)

  def test_long_pause_keeps_connection_checks_and_hash_drains_without_retry_or_step(self):
    logic = self.make(limits=LogicLimits(hashes_per_tick=1))
    self.deliver_authority(4, hashes=True)
    self.pause()
    logic.run_one_tick()
    self.assertEqual(logic.stats()['verified_hashes'], 1)
    baseline = self.env.get_state_digest(), len(self.env.steps), len(self.client.sent)
    for _ in range(1000):
      self.now += 10.
      logic.run_one_tick()
    self.assertEqual((self.env.get_state_digest(), len(self.env.steps), len(self.client.sent)), baseline)
    self.assertEqual(logic.stats()['verified_hashes'], 4)
    self.assertEqual(self.client.polls, 1001)
    self.assertEqual(len(self.client.acks), 1)
    self.assert_released()
    self.prepare()
    logic.run_one_tick()
    self.commit()
    logic.run_one_tick()
    self.assertEqual(logic.get_current_frame_id(), 5)
    self.assertEqual(len(self.env.steps), 5)

  def test_hash_failure_closes_before_ack_and_releases_abandoned_inputs(self):
    logic = self.make()
    logic.run_one_tick()
    self.pause()
    self.client.control = MatchControl(1, PAUSED, 0, self.client.control.state_hash ^ 1)
    with self.assertRaisesRegex(ClientFailure, 'control_hash_mismatch'):
      logic.run_one_tick()
    self.assertTrue(self.client.closed)
    self.assertEqual(self.client.acks, [])
    self.assert_released()

  def test_missing_boundary_snapshot_fails_closed_without_ack(self):
    logic = self.make()
    logic.run_one_tick()
    # Corrupt only the fixture's retained record to exercise fail-closed lookup.
    logic._clear_history()
    self.pause()
    with self.assertRaisesRegex(ClientFailure, 'missing_control_snapshot'):
      logic.run_one_tick()
    self.assertTrue(self.client.closed)
    self.assertFalse(self.client.acks)

  def test_invalid_transition_and_second_unacked_control_are_rejected(self):
    for second in (MatchControl(2, RUNNING, 0, 0), MatchControl(3, PAUSED, 0, 0), None):
      logic = self.make()
      self.client.control = second
      with self.assertRaises(ClientFailure):
        logic.run_one_tick()
      self.assertFalse(self.client.acks)
    logic = self.make(limits=LogicLimits(catchup_frames=1))
    self.deliver_authority(3)
    self.pause()
    logic.run_one_tick()
    self.prepare()
    with self.assertRaisesRegex(ClientFailure, 'control_before_ack'):
      logic.run_one_tick()

  def test_authority_past_pause_is_rejected_before_stepping(self):
    logic = self.make()
    self.pause()
    self.deliver_authority(1)
    with self.assertRaisesRegex(ClientFailure, 'authority_past_control'):
      logic.run_one_tick()
    self.assertEqual(self.env.frame, 0)

  def test_commit_and_first_authority_in_same_batch_apply_in_order(self):
    logic = self.make()
    self.pause()
    logic.run_one_tick()
    self.prepare()
    logic.run_one_tick()
    self.commit()
    self.deliver_authority(1)
    logic.run_one_tick()
    self.assertEqual(logic.get_last_confirmed_frame_id(), 0)
    self.assertEqual(logic.get_current_frame_id(), 2)
    self.assertFalse(self.client.closed)

  def test_commit_followed_by_pause_is_consumed_in_order_without_new_prediction(self):
    logic = self.make()
    self.pause()
    logic.run_one_tick()
    self.prepare()
    logic.run_one_tick()
    prepared = self.client.control
    self.commit()
    committed = self.client.control
    self.pause()
    paused = self.client.control
    pending = [committed, paused]
    self.client.get_match_control = lambda: pending[0] if pending else self.client.control
    # initialize_control intentionally retains the negotiated reader method.
    logic._control_reader = self.client.get_match_control
    def commit(state):
      self.assertEqual(pending.pop(0), state)
      self.assertEqual(state, committed)
      return True
    self.client.commit_control = commit
    self.client.on_ack = lambda state: self.assertEqual(pending.pop(0), state)
    logic.run_one_tick()
    self.assertEqual(pending, [])
    self.assertEqual(logic.control_state, paused)
    self.assertEqual(self.env.frame, 0)
    self.assertEqual(self.samples, [])
    self.assertEqual(self.notifications[-3:], [prepared, committed, paused])

  def test_commit_consumption_failure_cannot_resume_prediction(self):
    logic = self.make()
    self.pause()
    logic.run_one_tick()
    self.prepare()
    logic.run_one_tick()
    self.commit()
    self.client.commit_control = lambda control: False
    with self.assertRaisesRegex(ClientFailure, 'control_commit_rejected'):
      logic.run_one_tick()
    self.assertEqual(self.env.frame, 0)
    self.assertEqual(self.samples, [])
    self.assertTrue(self.client.closed)

  def test_notification_failure_or_stop_prevents_ack(self):
    for stop in (False, True):
      logic = self.make()
      def callback(control):
        if stop:
          logic.stop()
        else:
          raise RuntimeError('input owner failed')
      logic._on_control = callback
      self.pause()
      with self.assertRaises(RuntimeError):
        logic.run_one_tick()
      self.assertEqual(self.client.acks, [])
      self.assertTrue(self.client.closed)
      self.assert_released()

  def test_ack_admission_failure_closes_and_duplicate_does_not_repeat_notification(self):
    logic = self.make()
    self.pause()
    logic.run_one_tick()
    baseline = tuple(self.notifications), tuple(self.client.acks)
    for _ in range(5):
      logic.run_one_tick()
    self.assertEqual((tuple(self.notifications), tuple(self.client.acks)), baseline)
    self.prepare()
    self.client.accept_ack = False
    with self.assertRaisesRegex(ClientFailure, 'control_ack_rejected'):
      logic.run_one_tick()
    self.assertTrue(self.client.closed)
    self.assert_released()

  def test_pause_during_sample_discards_unsent_input(self):
    logic = self.make()
    def sample():
      self.pause()
      return [(0, wire.SlotInput(1, 0, 4))]
    logic._controlled_slots_callback = sample
    logic.run_one_tick()
    self.assertEqual(self.env.frame, 0)
    self.assertEqual(self.client.sent, [])
    self.assertEqual(len(self.client.acks), 1)
    self.assert_released()

  def test_pause_closing_admission_during_send_is_not_a_disconnect(self):
    for retry in (False, True):
      logic = self.make()
      if retry:
        logic.run_one_tick()
        self.now = .2
      def send(frame, entries):
        self.pause()
        return False
      self.client.send_frame_entries = send
      logic.run_one_tick()
      self.assertEqual(self.env.frame, 0)
      self.assertFalse(self.client.closed)
      self.assertEqual(len(self.client.acks), 1)
      self.assert_released()

  def test_terminal_boundary_and_stop_remain_available_while_paused(self):
    logic = self.make()
    self.deliver_authority(2)
    self.pause()
    logic.run_one_tick()
    state = self.env.get_state_digest()
    logic.finish_at(2, self.client.control.state_hash)
    logic.run_one_tick()
    self.assertEqual(self.env.get_state_digest(), state)
    self.assertEqual(len(self.client.acks), 1)
    self.assert_released()

  def test_origin_requires_exact_frame_hash_and_unsampled_session(self):
    for invalid in ('hash', 'frame', 'sampled', 'duplicate'):
      logic = self.make()
      if invalid != 'duplicate':
        # A separate pristine owner represents a new attachment attempt.
        logic.stop()
        logic = ClientLogicLoop(self.client, self.env, 2, lambda: [(0, wire.default_slot_input())])
        self.addCleanup(logic.stop)
      state = self.client.control
      if invalid == 'hash':
        state = MatchControl(0, RUNNING, 0, state.state_hash ^ 1)
      elif invalid == 'frame':
        state = MatchControl(0, RUNNING, 1, state.state_hash)
      elif invalid == 'sampled':
        logic.run_one_tick()
      with self.assertRaises(ClientFailure):
        logic.initialize_control(state)
      self.assertTrue(self.client.closed)
      self.assertFalse(self.client.acks)

  def test_paused_origin_stays_quiescent_without_extra_barrier_ack(self):
    client, env = ControlTransport(), Engine()
    client.control = MatchControl(7, PAUSED, 0, wire.compute_state_hash(env.get_state_digest()))
    logic = ClientLogicLoop(client, env, 1, lambda: self.fail('sampled a paused origin'))
    self.addCleanup(logic.stop)
    logic.initialize_control(client.control)
    for _ in range(4):
      logic.run_one_tick()
    self.assertEqual(env.frame, 0)
    self.assertEqual(client.acks, [])  # MatchReady will confirm the origin epoch.

  def test_reentrant_control_initialization_cannot_replace_active_tick(self):
    logic = self.make()
    def sample():
      with self.assertRaisesRegex(RuntimeError, 'reentrant'):
        logic.initialize_control(self.client.control)
      return [(0, wire.default_slot_input())]
    logic._controlled_slots_callback = sample
    logic.run_one_tick()
    self.assertEqual(self.env.frame, 1)
    self.assertFalse(self.client.closed)


class MatchControlInputTest(unittest.TestCase):
  def test_pause_discards_pending_taps_and_resume_requires_fresh_press(self):
    inputs = InputBuffer()
    inputs.feed(pressed_keys=('z',))
    inputs.set_suspended(True)
    inputs.feed(pressed_keys=('v',))
    self.assertEqual(inputs.sample(), wire.default_slot_input())
    inputs.set_suspended(False)
    inputs.feed(pressed_keys=('x',))
    self.assertEqual(inputs.sample(), wire.default_slot_input())
    inputs.feed()
    inputs.feed(pressed_keys=('z',))
    self.assertEqual(inputs.sample().buttons, 4)
    self.assertEqual(inputs.sample().buttons, 0)

  def test_held_keyboard_and_opposites_do_not_count_as_neutral(self):
    for keys in (('w',), ('z',), ('w', 's', 'a', 'd'), ('tab', 'lshift')):
      inputs = InputBuffer()
      inputs.feed(keys=keys)
      inputs.set_suspended(True)
      inputs.set_suspended(False)
      for _ in range(5):
        inputs.feed(keys=keys)
        self.assertEqual(inputs.sample(), wire.default_slot_input())
      inputs.feed()
      inputs.feed(keys=('d', 'z'))
      self.assertEqual(inputs.sample(), wire.SlotInput(1, 0, 4))

  def test_controller_stick_actions_dpad_and_pressed_edges_require_release(self):
    for state in (dict(axes=(1, 0)), dict(buttons=1), dict(buttons=15 << 11),
                  dict(pressed_buttons=2), dict(axes=(.13, .13))):
      inputs = InputBuffer()
      inputs.set_suspended(True)
      inputs.set_suspended(False)
      inputs.feed(connected=True, **state)
      self.assertEqual(inputs.sample(), wire.default_slot_input())
      inputs.feed(connected=True, pressed_buttons=1)
      self.assertEqual(inputs.sample(), wire.default_slot_input())
      inputs.feed(connected=True)
      inputs.feed(connected=True, pressed_buttons=1)
      self.assertEqual(inputs.sample().buttons, 4)

  def test_focus_loss_does_not_release_gate_until_focused_neutral_observation(self):
    inputs = InputBuffer()
    inputs.set_suspended(True)
    inputs.set_suspended(False)
    inputs.feed(focused=False, keys=('z',))
    inputs.feed(keys=('z',))
    self.assertEqual(inputs.sample(), wire.default_slot_input())
    inputs.feed()
    inputs.feed(pressed_keys=('z',))
    self.assertEqual(inputs.sample().buttons, 4)

  def test_controller_disconnect_is_neutral_but_reconnect_cannot_replay_old_tap(self):
    inputs = InputBuffer()
    inputs.feed(connected=True, buttons=1)
    inputs.set_suspended(True)
    inputs.set_suspended(False)
    inputs.feed(connected=False, buttons=1, axes=(1, 0), pressed_buttons=1)
    self.assertEqual(inputs.sample(), wire.default_slot_input())
    inputs.feed(connected=True)
    self.assertEqual(inputs.sample(), wire.default_slot_input())
    inputs.feed(connected=True, pressed_buttons=1)
    self.assertEqual(inputs.sample().buttons, 4)

  def test_save_and_quit_remain_independent_and_do_not_prevent_neutral_release(self):
    for command in (dict(keys=('p', 'q')), dict(connected=True, buttons=(1 << 6) | (1 << 4))):
      inputs = InputBuffer()
      inputs.set_suspended(True)
      inputs.feed(**command)
      self.assertEqual(inputs.commands(), (True, True))
      self.assertTrue(inputs.wait_for_quit(0))
      self.assertEqual(inputs.sample(), wire.default_slot_input())
      inputs.set_suspended(False)
      inputs.feed(**command)
      self.assertEqual(inputs.commands(), (True, False))
      inputs.feed(pressed_keys=('z',))
      self.assertEqual(inputs.sample().buttons, 4)

  def test_suspension_is_strict_idempotent_and_closed_buffer_cannot_resume(self):
    inputs = InputBuffer()
    inputs.feed(pressed_keys=('z',))
    inputs.set_suspended(False)
    self.assertEqual(inputs.sample().buttons, 4)
    for value in (0, 1, None, 'pause'):
      with self.assertRaises(ValueError):
        inputs.set_suspended(value)
    inputs.set_suspended(True)
    inputs.set_suspended(True)
    inputs.set_suspended(False)
    inputs.feed()
    inputs.feed(pressed_keys=('z',))
    inputs.set_suspended(False)
    self.assertEqual(inputs.sample().buttons, 4)
    inputs.close()
    with self.assertRaises(RuntimeError):
      inputs.set_suspended(False)


if __name__ == '__main__':
  unittest.main()
