# 2026-09-09: deterministic reconciliation oracle plus real TCP integration.
# The small engine below is an independent state machine, NOT native GameEnv.
import asyncio
import collections
import random
import struct
import sys
import threading
import time
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client import ClientLogicLoop, FrameSyncClient
from gfootball.frame_sync.client_async import FrameSyncClientAsync
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.client_logic import LogicLimits
from gfootball.frame_sync.test_tcp_client_budget import Peer, exact, hello, ready, until, async_until


def inputs(left=0.25, right=-0.5):
  return [wire.SlotInput(left, 0.125, 4), wire.SlotInput(right, -0.125, 8)]


def packed(values):
  return b''.join(wire.pack_slot_input(value) for value in values)


class Engine:
  def __init__(self):
    self.frame = 0
    self.value = 7
    self.saves = 0
    self.restores = 0
    self.steps = []
    self.padding = 0
    self.grow_after_correction = False
    self.fail_save_after_correction = False
    self.fail_step = False
    self.fail_digest = False
    self.digest_padding = 0

  def get_state(self, _):
    self.saves += 1
    if self.fail_save_after_correction and self.restores:
      raise RuntimeError('save failed')
    padding = 1024 if self.grow_after_correction and self.restores else self.padding
    return struct.pack('<QQ', self.frame, self.value) + b'\x00' * padding

  def set_state(self, state):
    self.restores += 1
    self.frame, self.value = struct.unpack_from('<QQ', state)

  def step_with_input(self, data):
    self.steps.append(data)
    self.value = ((self.value * 33) ^ wire.compute_state_hash(data)) & 0xffffffffffffffff
    self.frame += 1
    if self.fail_step:
      raise RuntimeError('step failed after mutation')

  def get_state_digest(self):
    if self.fail_digest:
      raise RuntimeError('digest failed')
    return struct.pack('<QQ', self.frame, self.value) + b'\x00' * self.digest_padding


class Client:
  def __init__(self):
    self.auth = collections.deque()
    self.hashes = collections.deque()
    self.sent = []
    self.closed = False
    self.failure_reason = None
    self.rtt = 0

  def send_frame_entries(self, frame, entries):
    self.sent.append((frame, tuple(entries)))
    return True

  def tick_disconnect_detection(self):
    return None

  def pop_authoritative_frame(self):
    return self.auth.popleft() if self.auth else None

  def has_authoritative_frame(self):
    return bool(self.auth)

  def pop_state_hash(self):
    return self.hashes.popleft() if self.hashes else None

  def is_disconnected(self):
    return self.closed

  def get_avg_rtt_ms(self):
    return self.rtt

  def close(self):
    self.closed = True
    self.failure_reason = self.failure_reason or 'closed'


class LogicBudgetTest(unittest.TestCase):
  def make(self, callback=None, **options):
    self.client, self.engine = Client(), Engine()
    self.samples = []
    def sample():
      self.samples.append(len(self.samples))
      return [(0, wire.SlotInput(0.1 * (1 + len(self.samples) % 5), 0.25, 2))]
    # 2026-09-09: unit cases control retry time; real TCP retry below uses the
    # actual monotonic clock and the current-frame-only server policy.
    # self.loop = ClientLogicLoop(self.client, self.engine, 2, callback or sample, **options)
    options.setdefault('clock', lambda: 0.0)
    self.loop = ClientLogicLoop(self.client, self.engine, 2, callback or sample, **options)
    return self.loop

  def assert_failed(self, reason):
    self.assertEqual(self.loop.failure_reason, reason)
    self.assertTrue(self.client.closed)
    self.assertTrue(self.loop.is_waiting_for_authority())
    stats = self.loop.stats()
    self.assertEqual(stats['history_frames'], 0)
    self.assertEqual(stats['history_bytes'], 0)
    self.assertEqual(stats['sampled_input_frames'], 0)
    counts = self.engine.saves, len(self.engine.steps), self.engine.restores
    for _ in range(20):
      self.loop.run_one_tick()
    self.assertEqual(counts, (self.engine.saves, len(self.engine.steps), self.engine.restores))

  def test_configuration_rejects_unbounded_and_invalid_values(self):
    for key, value in [('prediction_frames', 9), ('prediction_frames', True), ('snapshot_bytes', 2**30),
                       ('history_bytes', 0), ('hash_frames', 1025), ('catchup_frames', 33),
                       # 2026-09-09: include invalid retry configuration.
                       # ('digest_bytes', 63), ('hashes_per_tick', 0)]:
                       ('digest_bytes', 63), ('hashes_per_tick', 0), ('input_retry_seconds', float('nan')),
                       ('input_retry_seconds', 0), ('input_retry_seconds', True)]:
      with self.subTest(key=key), self.assertRaises(ValueError):
        LogicLimits(**{key: value})
    for slots in (0, 23, True, 1.5):
      with self.assertRaises(ValueError):
        ClientLogicLoop(Client(), Engine(), slots, lambda: [])
    for rate in (0, float('nan'), float('inf'), True, 241):
      with self.assertRaises(ValueError):
        self.make(rate_hz=rate)

  def test_prediction_exact_cap_no_snapshots_or_duplicate_sends_while_stalled(self):
    loop = self.make()
    for _ in range(3):
      loop.run_one_tick()
    self.assertEqual(loop.get_current_frame_id(), 3)
    self.assertEqual(loop.get_last_confirmed_frame_id(), -1)
    self.assertTrue(loop.is_waiting_for_authority())
    self.assertEqual(self.engine.saves, 3)
    for _ in range(1000):
      loop.run_one_tick()
    self.assertEqual(self.engine.saves, 3)
    self.assertEqual(len(self.engine.steps), 3)
    self.assertEqual([fid for fid, _ in self.client.sent], [0, 1, 2, 3])
    self.assertEqual(len(self.samples), 4)
    retained = sum(sys.getsizeof(record.before) + sys.getsizeof(record.inputs)
                   for record in loop._history.values())
    self.assertEqual(loop.stats()['history_bytes'], retained)

  def test_adaptive_cap_is_used_in_execution_including_zero(self):
    for rtt, expected in ((0, 3), (50, 3), (51, 2), (100, 2), (101, 1)):
      loop = self.make()
      self.client.rtt = rtt
      for _ in range(10):
        loop.run_one_tick()
      self.assertEqual(loop.get_current_frame_id(), expected)
    loop = self.make(limits=LogicLimits(prediction_frames=0))
    for _ in range(10):
      loop.run_one_tick()
    self.assertEqual(self.engine.saves, 0)
    self.assertEqual(self.engine.steps, [])
    self.assertEqual(len(self.client.sent), 1)

  def test_retries_are_rate_limited_identical_and_target_oldest_unconfirmed_input(self):
    now = [0.0]
    loop = self.make(clock=lambda: now[0])
    for _ in range(3):
      loop.run_one_tick()
    first = self.client.sent[0]
    for _ in range(1000):
      loop.run_one_tick()
    self.assertEqual(len(self.client.sent), 4)
    now[0] = 0.1
    loop.run_one_tick()
    self.assertEqual(self.client.sent[-1], first)
    self.assertEqual(loop.stats()['input_retries'], 1)
    for _ in range(1000):
      loop.run_one_tick()
    self.assertEqual(loop.stats()['input_retries'], 1)
    values = [wire.default_slot_input()] * 2
    values[0] = first[1][0][1]
    self.client.auth.append((0, values))
    now[0] = 0.2
    self.client.rtt = 101
    loop.run_one_tick()
    self.assertEqual(self.client.sent[-1], self.client.sent[1])
    self.assertEqual(self.client.sent[-1][0], 1)
    self.assertEqual(loop.stats()['input_retries'], 2)
    self.assertEqual(len(self.samples), 4)
    self.assertNotIn(0, loop._input_sent_at)

  def test_every_affected_prediction_replayed_against_independent_oracle(self):
    loop = self.make()
    for _ in range(3):
      loop.run_one_tick()
    future = [loop._history[fid].inputs for fid in (1, 2)]
    expected = Engine()
    authority = inputs(-0.75, 0.875)
    expected.step_with_input(packed(authority))
    hash0 = wire.compute_state_hash(expected.get_state_digest())
    for frame in future:
      expected.step_with_input(frame)
    self.client.auth.append((0, authority))
    self.client.hashes.append((0, hash0))
    self.client.rtt = 101  # prevent a new prediction while reviewing correction
    loop.run_one_tick()
    self.assertEqual((self.engine.frame, self.engine.value), (expected.frame, expected.value))
    self.assertEqual(loop.get_last_confirmed_frame_id(), 0)
    self.assertEqual(loop.get_current_frame_id(), 3)
    self.assertEqual(loop.get_rollback_count(), 1)
    self.assertEqual(loop.stats()['verified_hashes'], 1)
    self.assertEqual(len(self.samples), 4)  # one waiting frame was sent
    self.assertEqual([fid for fid, _ in self.client.sent], [0, 1, 2, 3])

  def test_correct_predictions_confirm_without_restepping_and_float32_matches_wire(self):
    loop = self.make(callback=lambda: [(0, wire.SlotInput(0.1, 0.2, 3))])
    for _ in range(3):
      loop.run_one_tick()
    sent = self.client.sent[0][1][0][1]
    self.assertNotEqual(sent.dir_x, 0.1)
    for frame, record in loop._history.items():
      values = [wire.unpack_slot_input(record.inputs, i * 10)[0] for i in range(2)]
      self.client.auth.append((frame, values))
      self.client.hashes.append((frame, record.digest))
    # Empty callback suppresses future prediction after the three confirmations.
    loop._controlled_slots_callback = lambda: []
    loop.run_one_tick()
    self.assertEqual(len(self.engine.steps), 3)
    self.assertEqual(self.engine.restores, 0)
    self.assertEqual(loop.stats()['history_bytes'], 0)
    self.assertEqual(loop.stats()['verified_hashes'], 3)
    self.assertEqual(loop.get_last_confirmed_frame_id(), 2)

  def test_old_authority_is_never_silently_marked_confirmed_without_correction(self):
    loop = self.make()
    for _ in range(3):
      loop.run_one_tick()
    before = self.engine.value
    self.client.auth.append((0, inputs(-1, 1)))
    loop.run_one_tick()
    self.assertNotEqual(self.engine.value, before)
    self.assertEqual(loop.get_rollback_count(), 1)
    self.assertEqual(self.engine.restores, 1)

  def test_growth_during_correction_recovers_authority_and_reuses_sent_input(self):
    loop = self.make(limits=LogicLimits(snapshot_bytes=128, history_bytes=512))
    for _ in range(3):
      loop.run_one_tick()
    old_input1 = self.client.sent[1]
    expected = Engine()
    auth0 = inputs(-1, 1)
    expected.step_with_input(packed(auth0))
    self.engine.grow_after_correction = True
    self.client.auth.append((0, auth0))
    loop.run_one_tick()
    self.assertEqual((self.engine.frame, self.engine.value), (expected.frame, expected.value))
    self.assertEqual(loop.get_current_frame_id(), 1)
    self.assertEqual(loop.get_last_confirmed_frame_id(), 0)
    self.assertTrue(loop.stats()['prediction_limited'])
    self.assertEqual(loop.stats()['history_bytes'], 0)
    for _ in range(20):
      loop.run_one_tick()
    self.assertEqual(len(self.client.sent), 3)
    self.assertEqual(self.client.sent[1], old_input1)
    self.assertEqual(len(self.samples), 3)
    self.engine.grow_after_correction = False
    auth1 = inputs(0.3, -0.25)
    expected.step_with_input(packed(auth1))
    self.client.auth.append((1, auth1))
    loop.run_one_tick()
    self.assertEqual(len(self.samples), 3)
    self.assertEqual(loop.get_current_frame_id(), 3)
    self.assertEqual(loop.get_last_confirmed_frame_id(), 1)
    future = [wire.default_slot_input()] * 2
    future[:] = auth1
    future[0] = self.client.sent[2][1][0][1]
    expected.step_with_input(packed(future))
    self.assertEqual(self.engine.value, expected.value)

  def test_snapshot_and_total_history_limits_stop_prediction_but_not_authority(self):
    for limits, padding, predictions in ((LogicLimits(snapshot_bytes=64), 20, 0),
                                         (LogicLimits(history_bytes=150), 0, 1)):
      loop = self.make(limits=limits)
      self.engine.padding = padding
      for _ in range(20):
        loop.run_one_tick()
      self.assertEqual(loop.get_current_frame_id(), predictions)
      self.assertTrue(loop.stats()['prediction_limited'])
      self.assertEqual(self.engine.saves, predictions + 1)
      self.client.auth.append((0, inputs()))
      loop.run_one_tick()
      self.assertEqual(loop.get_last_confirmed_frame_id(), 0)
      self.assertFalse(self.client.closed)
      self.assertLessEqual(loop.stats()['history_bytes'], limits.history_bytes)

  def test_save_failure_during_correction_recovers_then_stops(self):
    loop = self.make()
    for _ in range(3):
      loop.run_one_tick()
    auth0 = inputs(-1, 1)
    expected = Engine()
    expected.step_with_input(packed(auth0))
    self.engine.fail_save_after_correction = True
    self.client.auth.append((0, auth0))
    with self.assertRaisesRegex(RuntimeError, 'save failed'):
      loop.run_one_tick()
    self.assertEqual((self.engine.frame, self.engine.value), (expected.frame, expected.value))
    self.assert_failed('logic_error')

  def test_prediction_step_or_digest_failure_restores_before_state(self):
    for name in ('fail_step', 'fail_digest'):
      loop = self.make()
      setattr(self.engine, name, True)
      with self.assertRaises(RuntimeError):
        loop.run_one_tick()
      self.assertEqual((self.engine.frame, self.engine.value), (0, 7))
      self.assert_failed('logic_error')

  def test_failed_correction_root_restores_before_state_and_stops(self):
    for name in ('fail_step', 'fail_digest'):
      loop = self.make()
      for _ in range(3):
        loop.run_one_tick()
      setattr(self.engine, name, True)
      self.client.auth.append((0, inputs(-1, 1)))
      with self.assertRaises(RuntimeError):
        loop.run_one_tick()
      self.assertEqual((self.engine.frame, self.engine.value), (0, 7))
      self.assert_failed('logic_error')

  def test_hash_arrives_before_authority_and_late_hash_uses_confirmed_state(self):
    loop = self.make(limits=LogicLimits(prediction_frames=0))
    expected = Engine()
    hashes = []
    for frame in range(3):
      expected.step_with_input(packed(inputs()))
      hashes.append(wire.compute_state_hash(expected.get_state_digest()))
    self.client.hashes.append((2, hashes[2]))
    loop.run_one_tick()
    self.assertEqual(loop.stats()['pending_hashes'], 1)
    for frame in range(3):
      self.client.auth.append((frame, inputs()))
    loop.run_one_tick()
    self.client.hashes.append((0, hashes[0]))
    loop.run_one_tick()
    self.assertEqual(loop.stats()['verified_hashes'], 2)
    self.assertEqual(loop.stats()['pending_hashes'], 0)
    self.assertFalse(self.client.closed)

  def test_confirmed_hash_mismatch_is_terminal_before_any_new_prediction(self):
    loop = self.make()
    self.client.auth.append((0, inputs()))
    self.client.hashes.append((0, 0))
    with self.assertRaisesRegex(ClientFailure, 'hash_mismatch'):
      loop.run_one_tick()
    self.assertEqual(len(self.engine.steps), 1)
    self.assertEqual(self.samples, [])
    self.assert_failed('hash_mismatch')

  def test_hash_window_bounded_and_evicted_hash_rejected(self):
    loop = self.make(limits=LogicLimits(prediction_frames=0, hash_frames=4))
    for frame in range(1000):
      self.client.auth.append((frame, inputs()))
      loop.run_one_tick()
      self.assertLessEqual(loop.stats()['confirmed_hashes'], 4)
      self.assertLessEqual(loop.stats()['sampled_input_frames'], 1)
    self.client.hashes.append((0, 1))
    with self.assertRaisesRegex(ClientFailure, 'hash_outside_window'):
      loop.run_one_tick()
    self.assert_failed('hash_outside_window')

  def test_conflicting_or_distant_future_hashes_fail_closed(self):
    for hashes, reason in (([(0, 1), (0, 2)], 'invalid_hash'),
                            ([(1024, 1)], 'hash_outside_window'),
                            ([(True, 1)], 'invalid_hash')):
      loop = self.make()
      self.client.hashes.extend(hashes)
      with self.assertRaises(ClientFailure):
        loop.run_one_tick()
      self.assert_failed(reason)
      self.assertEqual(self.engine.steps, [])

  def test_authority_validation_happens_before_engine_step(self):
    for message, reason in (((1, inputs()), 'authority_out_of_order'),
                             ((0, [wire.default_slot_input()]), 'invalid_authority'),
                             ((0, inputs(float('nan'), 0)), 'invalid_authority')):
      loop = self.make()
      self.client.auth.append(message)
      with self.assertRaises(ClientFailure):
        loop.run_one_tick()
      self.assertEqual(self.engine.steps, [])
      self.assert_failed(reason)

  def test_catchup_is_bounded_and_suppresses_prediction_while_backlogged(self):
    loop = self.make(limits=LogicLimits(catchup_frames=3))
    self.client.auth.extend((frame, inputs()) for frame in range(10))
    loop.run_one_tick()
    self.assertEqual(loop.get_last_confirmed_frame_id(), 2)
    self.assertEqual(self.engine.saves, 0)
    self.assertEqual(len(self.engine.steps), 3)
    self.assertEqual(self.samples, [])
    loop.run_one_tick()
    self.assertEqual(loop.get_last_confirmed_frame_id(), 5)
    loop.run_one_tick()
    loop.run_one_tick()
    self.assertEqual(loop.get_last_confirmed_frame_id(), 9)
    self.assertEqual(loop.get_current_frame_id(), 11)

  def test_infinite_callback_is_bounded_and_duplicate_slots_rejected(self):
    consumed = []
    def sample():
      while True:
        consumed.append(1)
        yield (0, wire.default_slot_input())
    loop = self.make(callback=sample)
    with self.assertRaisesRegex(ClientFailure, 'invalid_input'):
      loop.run_one_tick()
    self.assertEqual(len(consumed), 23)
    self.assertEqual(self.client.sent, [])
    self.assert_failed('invalid_input')

  def test_callback_stop_close_and_reentrancy_never_start_a_prediction(self):
    # 2026-09-09: run_loop from a manual tick must also reject reentry before
    # its final cleanup tries to acquire the already held tick lock.
    # for operation in ('stop', 'close', 'reenter'):
    for operation in ('stop', 'close', 'reenter', 'reenter_loop'):
      def sample():
        if operation == 'stop':
          self.loop.stop()
        elif operation == 'close':
          self.client.close()
        elif operation == 'reenter_loop':
          self.loop.run_loop()
        else:
          self.loop.run_one_tick()
        return [(0, wire.default_slot_input())]
      loop = self.make(callback=sample)
      # if operation == 'reenter':
      #   with self.assertRaisesRegex(RuntimeError, 'reentrant'):
      if operation.startswith('reenter'):
        with self.assertRaisesRegex(RuntimeError, 'reentrant|active tick'):
          loop.run_one_tick()
      else:
        loop.run_one_tick()
      self.assertEqual(self.engine.saves, 0)
      self.assertEqual(self.engine.steps, [])
      self.assertTrue(self.client.closed)

  def test_oversized_digest_and_published_state_are_terminal(self):
    loop = self.make(limits=LogicLimits(digest_bytes=64))
    self.engine.digest_padding = 100
    with self.assertRaisesRegex(ClientFailure, 'digest_capacity'):
      loop.run_one_tick()
    self.assertEqual(self.engine.frame, 0)
    self.assert_failed('digest_capacity')
    class Holder:
      def write(self, *_args, **_kwargs):
        raise AssertionError('must reject before publishing')
    loop = self.make(state_holder=Holder(), limits=LogicLimits(prediction_frames=0, snapshot_bytes=64))
    self.engine.padding = 100
    self.client.auth.append((0, inputs()))
    with self.assertRaisesRegex(ClientFailure, 'presentation_state_capacity'):
      loop.run_one_tick()
    self.assert_failed('presentation_state_capacity')

  def test_presentation_only_publishes_changed_bounded_state(self):
    writes = []
    class Holder:
      def write(self, *args, **kwargs):
        writes.append((args, kwargs))
    loop = self.make(state_holder=Holder())
    for _ in range(20):
      loop.run_one_tick()
    self.assertEqual(len(writes), 3)
    self.assertEqual(writes[-1][0][1:3], (2, -1))
    self.assertTrue(writes[-1][1]['waiting_for_authority'])
    self.assertEqual(self.engine.saves, 6)  # 3 rollback saves + 3 bounded publications

  def test_stop_interrupts_low_rate_loop_without_waiting_a_full_period(self):
    loop = self.make(rate_hz=1, limits=LogicLimits(prediction_frames=0))
    thread = threading.Thread(target=loop.run_loop, name='tcp-budget-logic-loop')
    thread.start()
    try:
      until(lambda: bool(self.client.sent))
      started = time.monotonic()
      loop.stop()
      thread.join(0.5)
      self.assertFalse(thread.is_alive())
      self.assertLess(time.monotonic() - started, 0.5)
    finally:
      loop.stop()
      thread.join(2)

  def test_hash_work_budget_is_shared_by_both_drains(self):
    loop = self.make(limits=LogicLimits(prediction_frames=0, hashes_per_tick=3))
    expected = Engine()
    expected.step_with_input(packed(inputs()))
    digest = wire.compute_state_hash(expected.get_state_digest())
    self.client.auth.append((0, inputs()))
    loop.run_one_tick()
    self.client.hashes.extend((0, digest) for _ in range(10))
    loop.run_one_tick()
    self.assertEqual(loop.stats()['verified_hashes'], 3)
    self.assertEqual(len(self.client.hashes), 7)

  def test_second_run_loop_cannot_clear_a_tick_stopped_inside_its_callback(self):
    entered, release = threading.Event(), threading.Event()
    errors = []
    def sample():
      entered.set()
      if not release.wait(2):
        raise AssertionError('callback release timed out')
      return [(0, wire.default_slot_input())]
    loop = self.make(callback=sample)
    def run():
      try:
        loop.run_loop()
      except BaseException as error:
        errors.append(error)
    thread = threading.Thread(target=run, name='tcp-budget-logic-owner')
    thread.start()
    try:
      self.assertTrue(entered.wait(2))
      loop.stop()
      with self.assertRaisesRegex(RuntimeError, 'already running'):
        loop.run_loop()
    finally:
      release.set()
      loop.stop()
      thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(errors, [])
    self.assertEqual(self.engine.saves, 0)
    self.assertEqual(self.engine.steps, [])

  def test_random_delays_and_corrections_match_1000_authoritative_frames_at_2_and_22_slots(self):
    for slots, seed in ((2, 42), (22, 43)):
      with self.subTest(slots=slots):
        rng = random.Random(seed)
        client, engine, reference = Client(), Engine(), Engine()
        def sample():
          return [(slot, wire.SlotInput(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.randrange(4096)))
                  for slot in range(slots)]
        loop = ClientLogicLoop(client, engine, slots, sample,
                               limits=LogicLimits(prediction_frames=8, hash_frames=32, catchup_frames=4))
        deferred = []
        hashes = []
        delivered = 0
        saw_rollback = False
        for tick in range(2000):
          for _ in range(min(rng.randrange(5), 1000 - delivered)):
            values = [wire.SlotInput(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.randrange(4096))
                      for _ in range(slots)]
            reference.step_with_input(packed(values))
            digest = wire.compute_state_hash(reference.get_state_digest())
            hashes.append(digest)
            client.auth.append((delivered, values))
            deferred.append((tick + rng.randrange(4), delivered, digest))
            delivered += 1
          due = [entry for entry in deferred if entry[0] <= tick]
          deferred = [entry for entry in deferred if entry[0] > tick]
          rng.shuffle(due)  # Hash arrival order need not match authority order.
          client.hashes.extend((frame, digest) for _, frame, digest in due)
          client.rtt = rng.choice((0, 25, 75, 150))
          loop.run_one_tick()
          confirmed = loop.get_last_confirmed_frame_id()
          for frame, digest in loop._confirmed_hashes.items():
            self.assertEqual(digest, hashes[frame])
          stats = loop.stats()
          self.assertLessEqual(stats['history_frames'], 8)
          self.assertLessEqual(stats['history_bytes'], loop.limits.history_bytes)
          self.assertLessEqual(stats['confirmed_hashes'], 32)
          self.assertLessEqual(stats['pending_hashes'], 32)
          self.assertLessEqual(stats['sampled_input_frames'], 9)
          self.assertLessEqual(loop.get_current_frame_id() - confirmed - 1, 8)
          saw_rollback = saw_rollback or stats['rollbacks'] > 0
          if confirmed == 999 and not deferred:
            break
        self.assertEqual(loop.get_last_confirmed_frame_id(), 999)
        self.assertEqual(loop.stats()['verified_hashes'], 1000)
        self.assertTrue(saw_rollback)
        self.assertFalse(client.closed)


class SocketScenario:
  def __init__(self):
    self.received = []
    self.release = threading.Event()
    self.done = threading.Event()
    self.reference = Engine()

  def script(self, peer, stop):
    hello(peer)
    ready(peer)
    for frame in range(3):
      header = exact(peer, 7)
      count = struct.unpack_from('<H', header, 5)[0]
      message = header + exact(peer, count * 12)
      fid, entries = wire.unpack_client_frame_input(message)
      if fid != frame:
        raise AssertionError('input frame did not advance exactly once')
      self.received.append((fid, entries, message))
    if not self.release.wait(3):
      raise AssertionError('authority release timed out')
    output = b''
    for frame in range(3):
      authoritative = inputs(-0.75 + frame / 8, 0.5)
      self.reference.step_with_input(packed(authoritative))
      output += wire.pack_authoritative_frame(frame, authoritative)
      output += wire.pack_state_hash(frame, wire.compute_state_hash(self.reference.get_state_digest()))
    # Fragment inside the first authority and hash, not only at packet boundaries.
    peer.sendall(output[:12])
    peer.sendall(output[12:31])
    peer.sendall(output[31:])
    header = exact(peer, 7)
    count = struct.unpack_from('<H', header, 5)[0]
    fid, entries = wire.unpack_client_frame_input(header + exact(peer, count * 12))
    if fid != 3:
      raise AssertionError('expected one input for frame 3')
    self.received.append((fid, entries, None))
    self.done.set()
    while not stop.is_set():
      data = peer.recv(256)
      if not data:
        return
      raise AssertionError('unexpected duplicate input while stalled')

  def build_loop(self, client):
    self.engine = Engine()
    self.samples = 0
    def sample():
      self.samples += 1
      return [(0, wire.SlotInput(0.1 * self.samples, 0.2, self.samples))]
    # 2026-09-09: this peer buffers future inputs; isolate reconciliation from
    # legacy input retries, which have their own actual-time TCP fixture below.
    # self.loop = ClientLogicLoop(client, self.engine, 2, sample)
    self.loop = ClientLogicLoop(client, self.engine, 2, sample, clock=lambda: 0.0)

  def verify(self, test):
    test.assertEqual(self.loop.get_last_confirmed_frame_id(), 2)
    test.assertEqual(self.loop.stats()['verified_hashes'], 3)
    test.assertEqual(self.loop.get_rollback_count(), 3)
    test.assertEqual(self.samples, 4)
    predicted3 = inputs(-0.5, 0.5)
    predicted3[0] = self.received[3][1][0][1]
    self.reference.step_with_input(packed(predicted3))
    test.assertEqual((self.engine.frame, self.engine.value), (self.reference.frame, self.reference.value))
    # This checks packet bytes against the exact input used in the first local prediction.
    test.assertEqual(self.engine.steps[0][:10], self.received[0][2][9:19])


class LogicTCPTest(unittest.TestCase):
  def test_current_frame_only_server_receives_exact_cached_future_inputs_on_retry(self):
    received = []
    confirmed_inputs = []
    def read_input(peer):
      header = exact(peer, 7)
      count = struct.unpack_from('<H', header, 5)[0]
      return wire.unpack_client_frame_input(header + exact(peer, count * 12))
    def script(peer, stop):
      hello(peer)
      ready(peer)
      reference = Engine()
      for expected in range(3):
        frame, entries = read_input(peer)
        self.assertEqual(frame, expected)
        received.append(entries)
      # This is the existing server policy: frame 1/2 were received while
      # collecting frame 0 and discarded. Only an identical retry can apply them.
      for frame in range(3):
        if frame:
          while True:
            fid, entries = read_input(peer)
            if fid == frame:
              self.assertEqual(entries, received[frame])
              break
        values = [wire.default_slot_input()] * 2
        values[0] = received[frame][0][1]
        confirmed_inputs.append(values[0])
        reference.step_with_input(packed(values))
        peer.sendall(wire.pack_authoritative_frame(frame, values) + wire.pack_state_hash(
            frame, wire.compute_state_hash(reference.get_state_digest())))
      while not stop.is_set():
        if not peer.recv(4096):
          return
    with Peer(script) as peer:
      client = FrameSyncClient('127.0.0.1', peer.port)
      samples = []
      def sample():
        samples.append(1)
        return [(0, wire.SlotInput(0.1 * (len(samples) % 5 + 1), 0.2, len(samples)))]
      try:
        client.connect()
        loop = ClientLogicLoop(client, Engine(), 2, sample)
        client.send_ready()
        for _ in range(3):
          loop.run_one_tick()
        deadline = time.monotonic() + 1.5
        while loop.get_last_confirmed_frame_id() < 2 and time.monotonic() < deadline:
          loop.run_one_tick()
          time.sleep(0.005)
        self.assertEqual(loop.get_last_confirmed_frame_id(), 2)
        self.assertEqual(loop.stats()['verified_hashes'], 3)
        self.assertEqual(confirmed_inputs, [entries[0][1] for entries in received])
        self.assertTrue(all(value.buttons for value in confirmed_inputs))
      finally:
        client.close()

  def test_actual_sync_transport_reconciliation_and_three_confirmed_hashes(self):
    case = SocketScenario()
    def forbidden():
      raise AssertionError('transport must not resample logic input')
    with Peer(case.script) as peer:
      client = FrameSyncClient('127.0.0.1', peer.port, forbidden)
      try:
        client.connect()
        case.build_loop(client)
        client.send_ready()
        for _ in range(3):
          case.loop.run_one_tick()
        until(lambda: len(case.received) == 3)
        case.release.set()
        until(lambda: client.stats()['authority_frames'] == 3 and client.stats()['hashes'] == 3)
        case.loop.run_one_tick()
        self.assertTrue(case.done.wait(2))
        case.verify(self)
      finally:
        client.close()


class LogicAsyncTCPTest(unittest.IsolatedAsyncioTestCase):
  async def test_actual_async_transport_runs_the_same_logic_and_exact_input_contract(self):
    case = SocketScenario()
    def forbidden():
      raise AssertionError('transport must not resample logic input')
    with Peer(case.script) as peer:
      client = FrameSyncClientAsync('127.0.0.1', peer.port, forbidden, handshake='versioned')
      try:
        await client.connect_async()
        case.build_loop(client)
        client.send_ready()
        for _ in range(3):
          case.loop.run_one_tick()
        await async_until(lambda: len(case.received) == 3)
        case.release.set()
        await async_until(lambda: client.stats()['authority_frames'] == 3 and client.stats()['hashes'] == 3)
        case.loop.run_one_tick()
        await async_until(case.done.is_set)
        case.verify(self)
      finally:
        await client.close_async()


if __name__ == '__main__':
  unittest.main()
