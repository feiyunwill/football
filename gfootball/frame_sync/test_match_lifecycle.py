"""Independent terminal-state oracle, rollback and actual socket/file integration."""
from pathlib import Path
import hashlib
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_logic import ClientLogicLoop
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import engine_digest, playback, read_checkpoint
from gfootball.frame_sync.match_lifecycle import MatchLifecycleEngine, match_finished, MAX_SNAPSHOT, _HEADER
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.test_client_logic_budget import Client
from gfootball.frame_sync.test_match_archive import MatchOracle
from gfootball.engine_pool import EnginePool, EngineKey
from gfootball.owned_engine import create_owned_engine


class TerminalOracle(MatchOracle):
  """Explicit finite state reducer. No native module substitution or imports."""
  def __init__(self, settings, duration=5, score=False, out=False, possession=False):
    super().__init__(settings)
    self.config = SimpleNamespace(game_duration=duration, end_episode_on_score=score,
        end_episode_on_out_of_play=out, end_episode_on_possession_change=possession)
    self.state = self.step = self.mode = self.owner_team = self.goals = 0
    self.finishes = self.after_end = 0
    self.identity['backend'] = 'test.TerminalOracle.v1'
    self.identity['implementation'] = hashlib.sha256(repr(vars(self.config)).encode()).hexdigest()

  def step_with_input(self, data):
    if self.state:
      self.after_end += 1
      raise RuntimeError('Oracle already finished')
    super().step_with_input(data)
    buttons = wire.unpack_slot_input(data)[0].buttons
    self.step += 0 if buttons & 16 else 1
    self.goals += bool(buttons & 1)
    if buttons & 2:
      self.mode = 1
    if buttons & 64:
      self.mode = 0
    if buttons & 4:
      self.owner_team = 1
    if buttons & 8:
      self.owner_team = -1
    if buttons & 32:
      self.owner_team = 0
    if buttons & 128:
      self.state = 1

  def finish(self):
    self.check()
    self.finishes += 1
    self.state = 1

  def get_info(self):
    info = super().get_info()
    info.left_goals = self.goals
    info.step, info.game_mode, info.ball_owned_team = self.step, self.mode, self.owner_team
    return info

  def get_state(self, unused=''):
    self.check()
    return struct.pack('<II6i', self.frames, self.digest, self.step, self.mode,
                       self.owner_team, self.goals, 0, self.state) + bytes(self.padding)

  def set_state(self, data):
    self.check()
    self.restores += 1
    if self.fail_restore:
      raise RuntimeError('Injected restore failure')
    self.frames, self.digest, self.step, self.mode, self.owner_team, self.goals, _, self.state = struct.unpack_from('<II6i', data)
    self.padding = len(data) - 32


def packed(buttons=0, slots=1):
  return wire.pack_slot_input(wire.SlotInput(0, 0, buttons)) + wire.pack_slot_input(wire.default_slot_input()) * (slots - 1)


class MatchLifecycleTest(unittest.TestCase):
  def make(self, **rules):
    raw = TerminalOracle(ServerSettings(), **rules)
    env = MatchLifecycleEngine(raw, normal_mode=0, done_state=1)
    self.addCleanup(env.close)
    return env, raw

  def test_duration_uses_engine_play_clock_and_stops_before_an_extra_step(self):
    env, raw = self.make(duration=2)
    for _ in range(4):
      env.step_with_input(packed(16))
    self.assertFalse(match_finished(env))
    env.step_with_input(packed())
    env.step_with_input(packed())
    self.assertEqual(env.get_match_end_reason(), 'duration')
    with self.assertRaisesRegex(RuntimeError, 'ended'):
      env.step_with_input(packed())
    self.assertEqual((raw.frames, raw.step, raw.finishes, raw.after_end), (6, 2, 1, 0))

  def test_score_rule_finishes_the_scoring_frame(self):
    env, raw = self.make(score=True)
    env.step_with_input(packed(1))
    self.assertEqual(env.get_match_end_reason(), 'score')
    self.assertEqual((raw.frames, raw.goals, raw.finishes), (1, 1, 1))

  def test_out_of_play_requires_a_transition_from_normal(self):
    env, raw = self.make(out=True)
    raw.mode = env._previous_mode = 1
    env.step_with_input(packed(2))
    self.assertFalse(match_finished(env))
    env.step_with_input(packed(64))
    env.step_with_input(packed(2))
    self.assertEqual(env.get_match_end_reason(), 'out_of_play')

  def test_loose_ball_retains_previous_possession_across_snapshot(self):
    env, raw = self.make(possession=True)
    env.step_with_input(packed())  # Establish possession from the first frame.
    env.step_with_input(packed(8))
    snapshot, digest = env.get_state(''), env.get_state_digest()
    env.step_with_input(packed(4))
    self.assertEqual(env.get_match_end_reason(), 'possession_change')
    expected = env.get_state_digest()
    env.set_state(snapshot)
    self.assertEqual(env.get_state_digest(), digest)
    self.assertEqual(raw.owner_team, -1)
    env.step_with_input(packed(4))
    self.assertEqual(env.get_state_digest(), expected)

  def test_disabled_rules_do_not_finish_on_score_mode_or_possession(self):
    env, _ = self.make()
    env.step_with_input(packed(1 | 2 | 4))
    self.assertFalse(match_finished(env))

  def test_native_prematch_clock_and_first_set_piece_are_valid_origins(self):
    raw = TerminalOracle(ServerSettings(), duration=5, out=True, possession=True)
    raw.step, raw.mode, raw.owner_team = -1, 1, -1
    env = MatchLifecycleEngine(raw, normal_mode=0, done_state=1)
    self.addCleanup(env.close)
    origin = env.get_state('')
    env.set_state(origin)
    env.step_with_input(packed(4))
    self.assertFalse(match_finished(env))
    self.assertEqual(raw.step, 0)

  def test_native_terminal_signal_is_preserved_without_double_finish(self):
    env, raw = self.make()
    env.step_with_input(packed(128))
    self.assertEqual(env.get_match_end_reason(), 'engine')
    self.assertEqual(raw.finishes, 0)

  def test_explicit_finish_and_supported_match_step_contract(self):
    env, raw = self.make()
    before = env.get_state('')
    env.finish()
    env.finish()
    self.assertEqual(env.get_match_end_reason(), 'engine')
    self.assertEqual(raw.finishes, 1)
    ended = env.get_state('')
    env.set_state(before)
    env.set_state(ended)
    self.assertTrue(match_finished(env))
    with self.assertRaisesRegex(RuntimeError, 'step_with_input'):
      env.step()
    with self.assertRaisesRegex(RuntimeError, 'new match engine'):
      env.reset(None, False)

  def test_terminal_snapshot_restores_terminal_and_running_states(self):
    env, _ = self.make(duration=1)
    start = env.get_state('')
    env.step_with_input(packed())
    end, digest = env.get_state(''), env.get_state_digest()
    env.set_state(start)
    self.assertFalse(match_finished(env))
    env.set_state(end)
    self.assertTrue(match_finished(env))
    self.assertEqual(env.get_state_digest(), digest)

  def test_header_and_body_corruption_rejected_before_engine_restore(self):
    env, raw = self.make()
    snapshot = env.get_state('')
    for offset in (0, 8, _HEADER.size - 1, _HEADER.size, len(snapshot) - 1):
      damaged = bytearray(snapshot)
      damaged[offset] ^= 1
      with self.assertRaises(ValueError):
        env.set_state(bytes(damaged))
    self.assertEqual(raw.restores, 0)
    self.assertEqual(env.get_state(''), snapshot)

  def test_different_rules_cannot_restore_even_a_valid_snapshot(self):
    env, _ = self.make(duration=2)
    other, raw = self.make(duration=3)
    with self.assertRaisesRegex(ValueError, 'Incompatible'):
      other.set_state(env.get_state(''))
    self.assertEqual(raw.restores, 0)

  def test_rechecksummed_native_terminal_mismatch_rolls_back_atomically(self):
    env, raw = self.make()
    before = env.get_state('')
    values = list(_HEADER.unpack_from(before))
    values[-2] = 1
    header, body = _HEADER.pack(*values), before[_HEADER.size + 32:]
    damaged = header + hashlib.sha256(header + body).digest() + body
    with self.assertRaisesRegex(ValueError, 'disagree'):
      env.set_state(damaged)
    self.assertEqual(raw.restores, 2)
    self.assertEqual(env.get_state(''), before)

  def test_failed_restore_and_failed_recovery_close_resource(self):
    env, raw = self.make()
    before = env.get_state('')
    raw.fail_restore = True
    with self.assertRaisesRegex(RuntimeError, 'Injected restore'):
      env.set_state(before)
    self.assertEqual(raw.closed, 1)
    with self.assertRaisesRegex(RuntimeError, 'closed'):
      env.get_state('')

  def test_snapshot_limit_includes_lifecycle_header(self):
    env, raw = self.make()
    raw.padding = MAX_SNAPSHOT - _HEADER.size - 32 - 32
    snapshot = env.get_state('')
    self.assertEqual(len(snapshot), MAX_SNAPSHOT)
    env.set_state(snapshot)
    raw.padding += 1
    with self.assertRaisesRegex(ValueError, 'capacity'):
      env.get_state('')
    with self.assertRaises(ValueError):
      env.set_state(snapshot + b'0')

  def test_configuration_changes_and_foreign_thread_fail_explicitly(self):
    env, raw = self.make()
    failures = []
    def foreign():
      try:
        env.get_state('')
      except RuntimeError as error:
        failures.append(str(error))
    thread = threading.Thread(target=foreign, name='football-terminal-owner')
    thread.start()
    thread.join(2)
    self.assertFalse(thread.is_alive())
    self.assertEqual(len(failures), 1)
    raw.config.game_duration = 100
    with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
      match_finished(env)

  def test_completion_capability_is_explicit_and_validated(self):
    self.assertFalse(match_finished(object()))
    for value in (1, lambda: 1, lambda: None):
      with self.assertRaises(ValueError):
        match_finished(SimpleNamespace(is_match_finished=value))

  def test_prediction_of_false_terminal_can_be_corrected_and_continue(self):
    env, raw = self.make(score=True)
    client = Client()
    buttons, samples = [1], []
    def sample():
      samples.append(len(samples))
      return [(0, wire.SlotInput(0, 0, buttons[0]))]
    logic = ClientLogicLoop(client, env, 1, sample, clock=lambda: 0)
    logic.run_one_tick()
    self.assertTrue(match_finished(env))
    for _ in range(3):
      logic.run_one_tick()
    self.assertEqual(len(samples), 1)
    buttons[0] = 0
    client.auth.append((0, [wire.default_slot_input()]))
    logic.run_one_tick()
    self.assertFalse(match_finished(env))
    self.assertEqual(logic.get_last_confirmed_frame_id(), 0)
    self.assertEqual(logic.get_current_frame_id(), 2)
    self.assertEqual(raw.after_end, 0)

  def test_corrected_earlier_terminal_discards_later_predictions(self):
    env, raw = self.make(duration=50, score=True)
    client = Client()
    logic = ClientLogicLoop(client, env, 1, lambda: [(0, wire.default_slot_input())], clock=lambda: 0)
    # 2026-09-10: the existing no-authority budget caps this run at three frames.
    # for _ in range(5):
    for _ in range(3):
      logic.run_one_tick()
    # self.assertEqual(logic.get_current_frame_id(), 5)
    self.assertEqual(logic.get_current_frame_id(), 3)
    client.auth.append((0, [wire.SlotInput(0, 0, 1)]))
    logic.run_one_tick()
    self.assertEqual((logic.get_current_frame_id(), raw.frames), (1, 1))
    self.assertTrue(match_finished(env))
    self.assertEqual(logic.stats()['history_bytes'], 0)
    self.assertEqual(logic.stats()['sampled_input_frames'], 0)
    self.assertIsNone(logic.failure_reason)
    logic.finish_at(1, wire.compute_state_hash(env.get_state_digest()))
    self.assertEqual(raw.after_end, 0)


class MatchCompletionIntegrationTest(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.engines = []
    self.pool = EnginePool(max_live=3, idle_headless=0, idle_rendering=0)
    self.key = EngineKey.current(1280, 720)

  def factory(self, settings):
    # 2026-09-10: exercise lifecycle under the same owner adapter as production.
    # raw = TerminalOracle(settings, duration=5)
    # self.engines.append(raw)
    # return MatchLifecycleEngine(raw, normal_mode=0, done_state=1)
    def initialize():
      raw = TerminalOracle(settings, duration=5)
      self.engines.append(raw)
      return MatchLifecycleEngine(raw, normal_mode=0, done_state=1)
    return create_owned_engine(self.key, initialize, pool=self.pool)

  def tearDown(self):
    self.pool.close()
    self.assertEqual(self.pool.stats()['live'], 0)
    self.assertTrue(all(env.closed == 1 and env.after_end == 0 for env in self.engines),
                    [(env.closed, env.after_end) for env in self.engines])

  def test_local_natural_end_record_checkpoint_and_completed_restore(self):
    record, save = str(self.root / 'match.replay'), str(self.root / 'match.save')
    with LocalPlayer(engine_factory=self.factory, record_path=record, save_path=save) as player:
      result = player.run(100, realtime=False)
    self.assertEqual(result['frames'], 5)
    self.assertTrue(result['ended'] and result['closed'])
    expected = read_checkpoint(save)['digest']
    self.assertEqual(playback(record, engine_factory=self.factory)['digest'], expected)
    with LocalPlayer(engine_factory=self.factory, resume_path=save) as resumed:
      self.assertTrue(resumed.stats()['ended'])
      with self.assertRaisesRegex(RuntimeError, 'ended'):
        resumed.step()
      self.assertEqual(resumed.run(100, realtime=False)['frames'], 0)

  def test_saved_running_match_preserves_remaining_duration(self):
    save, record = str(self.root / 'mid.save'), str(self.root / 'remaining.replay')
    with LocalPlayer(engine_factory=self.factory, save_path=save) as player:
      player.step()
      player.step()
      player.save()
    with LocalPlayer(engine_factory=self.factory, resume_path=save, record_path=record) as resumed:
      result = resumed.run(100, realtime=False)
    self.assertEqual(result['frames'], 3)
    self.assertTrue(result['ended'])
    self.assertEqual(playback(record, engine_factory=self.factory)['digest'], result['last']['digest'])

  def multiplayer(self, transport):
    record, save = str(self.root / 'multi.replay'), str(self.root / 'multi.save')
    host = HostedMatch(transport=transport, engine_factory=self.factory,
        record_path=record, save_path=save, input_provider=lambda _: wire.default_slot_input())
    results, errors = [], []
    try:
      host.start()
      def join():
        try:
          with NetworkPlayer('127.0.0.1', host.port, transport=transport, engine_factory=self.factory,
                             input_provider=lambda _: wire.default_slot_input()) as player:
            results.append(player.run(100, realtime=False))
        except BaseException as error:
          errors.append(repr(error))
      thread = threading.Thread(target=join, name='football-terminal-join')
      thread.start()
      try:
        result = host.run(100, realtime=False, lobby_timeout=3)
      finally:
        host.close(finalize=False)
        thread.join(6)
      self.assertFalse(thread.is_alive())
      self.assertEqual(errors, [])
      self.assertEqual(result['frame'], 5)
      self.assertTrue(result['end_acknowledged'])
      self.assertTrue(results[0]['ended'])
      self.assertEqual(results[0]['final_frame'], 5)
      self.assertEqual(playback(record, engine_factory=self.factory)['digest'], read_checkpoint(save)['digest'])
    finally:
      host.close(finalize=False)

  def test_tcp_natural_end_delivers_final_authority_ack_and_files(self):
    self.multiplayer('tcp')

  def test_udp_natural_end_delivers_final_authority_ack_and_files(self):
    self.multiplayer('udp')

  def test_natural_udp_end_survives_lost_end_ack_and_transport_receipt(self):
    from gfootball.frame_sync.test_multiplayer_udp import EndAckRelay
    with HostedMatch(transport='udp', engine_factory=self.factory,
                     input_provider=lambda _: wire.default_slot_input()) as host:
      relay = EndAckRelay(host.port)
      try:
        with NetworkPlayer('127.0.0.1', relay.port, transport='udp', engine_factory=self.factory,
                           input_provider=lambda _: wire.default_slot_input()) as player:
          deadline = time.monotonic() + 5
          while host.frame < 5:
            player.tick()
            host.advance()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.001)
          while not player.stats()['ended'] or not host.player.stats()['ended']:
            player.tick()
            host.player.tick()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.001)
          player.flush_end_ack()
          self.assertTrue(host.finish())
          self.assertEqual(relay.end_data_dropped, 1)
          self.assertEqual(relay.end_receipt_dropped, 1)
          self.assertEqual(player.stats()['final_frame'], 5)
      finally:
        relay.close()

  def test_terminal_callback_failure_keeps_previous_replay_and_closes_owners(self):
    path = self.root / 'previous.replay'
    path.write_bytes(b'previous complete replay')
    failure = ValueError('terminal callback failed')
    def on_frame(frame):
      if frame['ended']:
        raise failure
    player = LocalPlayer(engine_factory=self.factory, record_path=str(path), on_frame=on_frame)
    try:
      player.start()
      with self.assertRaises(ValueError) as caught:
        player.run(100, realtime=False)
      self.assertIs(caught.exception, failure)
      self.assertEqual(path.read_bytes(), b'previous complete replay')
      self.assertTrue(player.stats()['closed'])
    finally:
      player.stop(finalize=False)

  def test_input_failure_survives_secondary_local_cleanup_error(self):
    failure = ValueError('input callback failed before frame')
    def provider(_):
      raise failure
    player = LocalPlayer(engine_factory=self.factory, input_provider=provider)
    try:
      player.start()
      original = player.stop
      def cleanup(**options):
        original(**options)
        raise RuntimeError('secondary close failure')
      player.stop = cleanup
      with self.assertRaises(ValueError) as caught:
        player.run(100, realtime=False)
      self.assertIs(caught.exception, failure)
      self.assertTrue(player.stats()['closed'])
    finally:
      player.close(finalize=False)

  def public_loop(self, transport):
    from gfootball.frame_sync.multiplayer_transport import MatchServer
    from gfootball.frame_sync.multiplayer_udp import MatchUDPServer
    server_type = MatchServer if transport == 'tcp' else MatchUDPServer
    server = server_type(listen_host='127.0.0.1', listen_port=0, left_agents=1, right_agents=0,
                         engine_factory=self.factory, state_hash_interval=1)
    results, errors = [], []
    try:
      server.start()
      def join():
        try:
          with NetworkPlayer('127.0.0.1', server.listen_port, transport=transport,
                             engine_factory=self.factory, input_provider=lambda _: wire.default_slot_input()) as player:
            results.append(player.run(100, realtime=False))
        except BaseException as error:
          errors.append(repr(error))
      thread = threading.Thread(target=join, name='football-terminal-public-loop')
      thread.start()
      try:
        # 2026-09-10: exercise the real v5 negotiated cadence in public loops.
        # server.run_loop(rate_hz=100)
        # 2026-09-13: product completion test uses its negotiated v7 rate.
        # server.run_loop(rate_hz=10)
        server.run_loop(rate_hz=50)
      finally:
        server.stop()
        thread.join(5)
      self.assertFalse(thread.is_alive())
      self.assertEqual(errors, [])
      self.assertTrue(results[0]['ended'])
      self.assertEqual(results[0]['final_frame'], 5)
      self.assertTrue(server._runtime.closed)
    finally:
      server.stop()

  def test_public_tcp_server_loop_closes_after_natural_end(self):
    self.public_loop('tcp')

  def test_public_udp_server_loop_drains_and_closes_after_natural_end(self):
    self.public_loop('udp')


if __name__ == '__main__':
  unittest.main()
