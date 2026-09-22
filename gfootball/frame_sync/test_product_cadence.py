"""Version 7 time, archive, legacy-boundary and actual native cadence contracts."""
import copy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
from gfootball.frame_sync.graphical_input import InputBuffer
from gfootball.frame_sync.match_archive import (
    MatchRecorder, capture, decode_checkpoint, engine_digest, playback,
)
from gfootball.frame_sync.match_bootstrap import (
    MATCH_VERSION, pack_match_ready, unpack_match_ready, unpack_match_reconnect,
    pack_origin, unpack_origin,
)
from gfootball.frame_sync.match_cadence import MATCH_CADENCE
from gfootball.frame_sync.protocol import SlotInput, default_slot_input, pack_slot_input
from gfootball.frame_sync.replay import Replay
from gfootball.frame_sync.save_data import SaveFormatError
from gfootball.frame_sync.server import BotTakeoverManager
from gfootball.frame_sync.server_runtime import ServerRuntime, ServerSettings
from gfootball.frame_sync.test_frame_pacing import Clock
from gfootball.frame_sync.test_match_archive import MatchOracle


class ProductCadenceTest(unittest.TestCase):
  def test_scenario_time_and_signed_native_duration_boundary(self):
    self.assertEqual((MATCH_VERSION, MATCH_HZ, MATCH_CADENCE.frame_ms), (7, 50, 20))
    for legacy_frames in range(1, 40001):
      actual = MATCH_CADENCE.scenario_frames(legacy_frames)
      self.assertEqual(actual * 20, legacy_frames * 100)
    self.assertEqual(MATCH_CADENCE.scenario_frames(3000), 15000)
    self.assertEqual(MATCH_CADENCE.scenario_frames(400), 2000)
    maximum = 0x7fffffff // 5
    self.assertEqual(MATCH_CADENCE.scenario_frames(maximum), maximum * 5)
    for value in (False, True, 0, -1, 1.0, '1', None, maximum + 1, 0x7fffffff, 2**64):
      with self.subTest(value=value), self.assertRaises(ValueError):
        MATCH_CADENCE.scenario_frames(value)

  def test_generic_interfaces_keep_legacy_defaults(self):
    self.assertEqual(FramePacer().stats()['period_ns'], 100000000)
    self.assertEqual(inspect.signature(ServerRuntime.run_loop).parameters['rate_hz'].default, 10)
    from gfootball.frame_sync.multiplayer_transport import MatchServer, MatchServerRuntime
    self.assertEqual(inspect.signature(MatchServer.run_loop).parameters['rate_hz'].default, 50)
    self.assertEqual(inspect.signature(MatchServerRuntime.run_loop).parameters['rate_hz'].default, 50)

  def test_product_absolute_grid_and_stall_preserve_input_edges(self):
    clock, buffer = Clock(), InputBuffer()
    self.addCleanup(buffer.close)
    pacer = FramePacer(MATCH_HZ, clock_ns=clock)
    starts, samples = [], []
    for frame in range(2500):
      pacer.wait_next(clock.wait)
      starts.append(clock.ns)
      samples.append(buffer.sample(frame).buttons)
      clock.ns += 3000000
    self.assertEqual(starts, [n * 20000000 for n in range(2500)])
    self.assertEqual(samples, [0] * 2500)
    self.assertEqual(pacer.stats()['missed_deadlines'], 0)
    clock.ns = 55007000000
    buffer.feed(pressed_keys=('v',))
    buffer.feed()
    pacer.wait_next(clock.wait)
    self.assertEqual(buffer.sample(2500).buttons, 8)
    # 2026-09-13: the raw buffer does not implement the caller's publication history.
    # # Retry retains the already published frame, subsequent new frame is neutral.
    # self.assertEqual(buffer.sample(2500).buttons, 8)
    # Buffer consumes edges once; ClientLogicLoop owns immutable publication retries.
    self.assertEqual(buffer.sample(2500).buttons, 0)
    pacer.wait_next(clock.wait)
    self.assertEqual(clock.ns, 55020000000)
    self.assertEqual(buffer.sample(2501).buttons, 0)
    self.assertEqual(pacer.stats()['ticks'], 2502)
    self.assertEqual(pacer.stats()['missed_deadlines'], 250)

  def test_old_cadence_and_protocol_cannot_be_reinterpreted(self):
    self.assertEqual(pack_match_ready(), bytes.fromhex('12 0700 3200 3200 0200 10270000 00000000'))
    for packet in (
        bytes.fromhex('12 0600 0a00 0a00 0a00 10270000 00000000'),
        bytes.fromhex('12 0600 3200 3200 0200 10270000 00000000'),
        bytes.fromhex('12 0700 0a00 0a00 0a00 10270000 00000000'),
        bytes.fromhex('12 0700 3200 3200 0a00 10270000 00000000')):
      with self.assertRaises(ValueError):
        unpack_match_ready(packet)
    # MatchReconnectRequest=15; the C++ v2 family gives message 15 a different meaning.
    with self.assertRaises(ValueError):
      unpack_match_reconnect(bytes.fromhex('0f 0600 0100000000000000'))
    env = MatchOracle(ServerSettings())
    self.addCleanup(env.close)
    origin = pack_origin(ServerSettings(), env)
    self.assertEqual(origin[:8], b'FMATCH7\0')
    from gfootball.frame_sync.client_buffers import ClientFailure
    with self.assertRaises(ClientFailure):
      unpack_origin(b'FMATCH6\0' + origin[8:])

  def test_checkpoint_requires_cadence_before_snapshot_decode(self):
    env = MatchOracle(ServerSettings())
    self.addCleanup(env.close)
    checkpoint = capture(ServerSettings(), env)
    self.assertEqual(checkpoint['version'], 3)
    self.assertEqual(checkpoint['cadence'], dict(input_hz=50, network_hz=50, physics_steps=2, physics_step_us=10000))
    variants = []
    old = copy.deepcopy(checkpoint)
    old['version'] = 2
    del old['cadence']
    variants.append(old)
    for name, value in (('input_hz', 10), ('network_hz', 10), ('physics_steps', 10), ('physics_step_us', 2000)):
      bad = copy.deepcopy(checkpoint)
      bad['cadence'][name] = value
      variants.append(bad)
    for bad in variants:
      # Poison chunk decoding too: the cadence error must be first.
      bad['chunks'] = ['!']
      with self.assertRaisesRegex(SaveFormatError, 'cadence'):
        decode_checkpoint(bad)
    self.assertEqual(decode_checkpoint(checkpoint)[1], env.get_state(''))

  def test_replay_header_and_terminal_time_use_actual_frame_units(self):
    for count in (0, 1, 49, 50, 51):
      with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
        settings = ServerSettings()
        env = MatchOracle(settings)
        recorder = MatchRecorder(settings, env)
        try:
          for frame in range(count):
            value = SlotInput(.5, -.25, 8 if frame % 2 else 0)
            env.step_with_input(pack_slot_input(value))
            recorder.record(frame, [value], env)
          replay = recorder.finish(env)
          self.assertEqual(replay.tick_hz, 50)
          self.assertEqual(replay.events[-1].timestamp_ms, count * 20)
          path = Path(directory) / 'match.replay'
          replay.save(path)
          self.assertEqual(Replay.load(path).tick_hz, 50)
          self.assertEqual(playback(path, engine_factory=MatchOracle)['digest'], engine_digest(env))
        finally:
          recorder.close()
          env.close()

  def test_bot_cooldowns_preserve_simulated_seconds(self):
    for hz in (10, 50):
      for team, args, bit, seconds in (
          (0, (98., 0., 96., 0.), 1 << 3, 3),
          (0, (-99., 0., -98., 0.), 1 << 0, 4)):
        bots = BotTakeoverManager(rate_hz=hz)
        bots.takeover(0, team)
        events = [frame for frame in range(seconds * hz * 2 + 1)
                  if bots.generate_input(0, *args).buttons & bit]
        self.assertEqual(events, [0, seconds * hz, seconds * hz * 2])
    for value in (True, False, 0, 241, 50., None):
      with self.assertRaises(ValueError):
        BotTakeoverManager(rate_hz=value)

  def test_real_tcp_and_udp_v6_clients_cannot_acquire_v7_slots(self):
    from gfootball.frame_sync import protocol as wire
    from gfootball.frame_sync.client_buffers import ClientFailure
    from gfootball.frame_sync.multiplayer_transport import MatchServer, MatchTCPClient
    from gfootball.frame_sync.multiplayer_udp import MatchUDPServer, MatchUDPClient
    for server_type, client_type in ((MatchServer, MatchTCPClient), (MatchUDPServer, MatchUDPClient)):
      server = server_type(listen_host='127.0.0.1', listen_port=0, engine_factory=MatchOracle)
      client = None
      try:
        server.start()
        client = client_type('127.0.0.1', server.listen_port)
        client._hello_packet = lambda token: wire.pack_version_negotiate(6, 6)
        with self.assertRaises(ClientFailure):
          client.connect()
        self.assertEqual(server.get_session_tokens(), {})
        self.assertEqual(server._call(lambda: server._runtime.window.frame_id), 0)
        self.assertEqual(server._call(lambda: server._runtime.bots._rate_hz), 50)
      finally:
        if client is not None:
          client.close()
        server.close()


class ProductCadenceNativeTest(unittest.TestCase):
  def test_actual_native_product_and_legacy_factories_keep_distinct_time_units(self):
    from gfootball.frame_sync.match_identity import native_match_engine
    from gfootball.frame_sync.server_runtime import native_engine
    settings = ServerSettings(scenario_name='11_vs_11_easy_stochastic')
    with native_engine(settings) as legacy:
      self.assertEqual(legacy.game_config.physics_steps_per_frame, 10)
      self.assertEqual(legacy.config.game_duration, 3000)
    with native_match_engine(settings) as product:
      self.assertEqual(product.game_config.physics_steps_per_frame, 2)
      self.assertEqual(product.config.game_duration, 15000)
      self.assertEqual(product.get_snapshot_identity()['backend'], 'gfootball.GameEnv.FSTA2.match1.physics2.cadence50')
      # 2026-09-13: capture a running match after bounded kickoff, not an all-kickoff replay.
      # origin = product.get_state('')
      neutral = pack_slot_input(default_slot_input())
      for attempt in range(500):
        if product.get_info().step >= 0:
          break
        product.step_with_input(neutral)
      self.assertEqual(product.get_info().step, 0)
      origin = product.get_state('')
      samples = [pack_slot_input(SlotInput(1., 0., 512 if frame < 25 else 0)) for frame in range(50)]
      digests = []
      for value in samples:
        product.step_with_input(value)
        digests.append(engine_digest(product))
      product.set_state(origin)
      for value, expected in zip(samples, digests):
        product.step_with_input(value)
        self.assertEqual(engine_digest(product), expected)

  def test_actual_native_scaled_termination_and_midmatch_restore(self):
    from gfootball.frame_sync import server
    from gfootball.frame_sync.match_identity import native_match_engine
    original = server.get_scenario_config
    def short_scenario(*args):
      scenario = original(*args)
      scenario.game_duration = 3  # 300 ms at the legacy scenario definition.
      scenario.end_episode_on_score = False
      scenario.end_episode_on_out_of_play = False
      scenario.end_episode_on_possession_change = False
      return scenario
    with mock.patch.object(server, 'get_scenario_config', short_scenario):
      with native_match_engine(ServerSettings()) as env:
        self.assertEqual(env.config.game_duration, 15)
        neutral = pack_slot_input(default_slot_input())
        # 2026-09-13: preserve the prior ten simulated second kickoff bound: 500 x 20 ms.
        # for attempt in range(100):
        for attempt in range(500):
          if env.get_info().step >= 5:
            break
          env.step_with_input(neutral)
        self.assertEqual(env.get_info().step, 5)
        self.assertFalse(env.is_match_finished())
        saved, expected = env.get_state(''), []
        while not env.is_match_finished():
          self.assertLess(env.get_info().step, 15)
          env.step_with_input(neutral)
          expected.append(engine_digest(env))
        self.assertEqual(env.get_info().step, 15)
        self.assertEqual(env.get_match_end_reason(), 'duration')
        env.set_state(saved)
        self.assertFalse(env.is_match_finished())
        for digest in expected:
          env.step_with_input(neutral)
          self.assertEqual(engine_digest(env), digest)
        self.assertTrue(env.is_match_finished())


if __name__ == '__main__':
  unittest.main()
