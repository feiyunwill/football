"""Actual local/TCP/UDP owners and UI handoff; explicit non-native engine/display."""
import json
import contextlib
import os
import sys
from collections import deque
from pathlib import Path
import queue
import threading
import time
import unittest
from unittest import mock

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync import local_runtime, client_tcp
from gfootball.frame_sync.client_buffers import ClientLimits
from gfootball.frame_sync import test_pacing_runtime as local_fixture
from gfootball.frame_sync import test_graphical_runtime as graphical_fixture
from gfootball.frame_sync.graphical_input import InputBuffer, BufferedControls
from gfootball.frame_sync.graphical_runtime import run_graphical
from gfootball.frame_sync.local_runtime import LocalPlayer, TerminalControls
from gfootball.frame_sync.match_archive import engine_digest, playback, decode_checkpoint, read_checkpoint
from gfootball.frame_sync.match_control import RUNNING, PAUSED, RESUMING
from gfootball.frame_sync.multiplayer_runtime import HostedMatch


class PauseCommandTest(unittest.TestCase):
  def test_terminal_pause_clears_persistent_direction_and_keeps_save_quit(self):
    keys = deque()
    with contextlib.ExitStack() as patches:
      patches.enter_context(mock.patch.object(sys.stdin, 'isatty', return_value=True))
      if os.name == 'nt':
        import msvcrt
        patches.enter_context(mock.patch.object(msvcrt, 'kbhit', side_effect=lambda: bool(keys)))
        patches.enter_context(mock.patch.object(msvcrt, 'getwch', side_effect=keys.popleft))
      else:
        import select
        patches.enter_context(mock.patch.object(select, 'select', side_effect=lambda *args: ([sys.stdin] if keys else [], [], [])))
        patches.enter_context(mock.patch.object(os, 'read', side_effect=lambda *args: keys.popleft().encode('ascii')))
      controls = TerminalControls()
      keys.extend('w')
      self.assertEqual(controls.read().dir_y, 1.)
      self.assertEqual(controls.read().dir_y, 1.)
      keys.extend('kv')
      self.assertEqual(controls.read(), wire.default_slot_input())
      self.assertTrue(controls.pause)
      controls.set_suspended(True)
      keys.extend('wpv')
      self.assertEqual(controls.read(), wire.default_slot_input())
      self.assertTrue(controls.save)
      keys.extend('k')
      self.assertEqual(controls.read(), wire.default_slot_input())
      controls.set_suspended(False)
      self.assertEqual(controls.read(), wire.default_slot_input())
      keys.extend('wq')
      self.assertEqual(controls.read().dir_y, 1.)
      self.assertTrue(controls.quit)

  def test_tap_held_key_and_guide_produce_one_command_without_action(self):
    inputs = InputBuffer()
    inputs.feed(keys=('k',))
    self.assertEqual(inputs.commands(), (False, False))  # old readers don't consume pause
    self.assertEqual(inputs.commands(include_pause=True), (False, False, True))
    for _ in range(10):
      inputs.feed(keys=('k',))
      self.assertEqual(inputs.commands(include_pause=True), (False, False, False))
    inputs.feed(connected=True, pressed_buttons=1 << 5)
    self.assertEqual(inputs.commands(include_pause=True), (False, False, True))
    self.assertEqual(inputs.sample().buttons, 0)

  def test_many_unconsumed_toggles_keep_only_final_intent(self):
    inputs = InputBuffer()
    for _ in range(1000):
      inputs.feed(pressed_keys=('k',))
    self.assertFalse(inputs.commands(include_pause=True)[2])
    inputs.feed(pressed_keys=('k',))
    inputs.feed(keys=('p', 'z'))
    self.assertEqual(inputs.commands(include_pause=True), (False, True, True))
    self.assertEqual(inputs.sample().buttons, 4)

  def test_pause_commands_survive_suspension_and_do_not_block_release(self):
    inputs, controls = InputBuffer(), None
    controls = BufferedControls(inputs)
    inputs.set_suspended(True)
    inputs.feed(keys=('k', 'p', 'v'))
    controls.read()
    self.assertTrue(controls.pause and controls.save)
    self.assertEqual(inputs.sample().buttons, 0)
    inputs.set_suspended(False)
    self.assertTrue(inputs.release_required)
    inputs.feed(keys=('k', 'p'))
    self.assertFalse(inputs.release_required)
    inputs.feed(pressed_keys=('v',))
    self.assertEqual(inputs.sample().buttons, 8)

  def test_focus_loss_close_and_invalid_selection_preserve_atomicity(self):
    inputs = InputBuffer()
    inputs.feed(pressed_keys=('k',))
    with self.assertRaises(ValueError):
      inputs.commands(include_pause=1)
    self.assertTrue(inputs.commands(include_pause=True)[2])
    inputs.feed(pressed_keys=('k',))
    inputs.feed(focused=False)
    self.assertFalse(inputs.commands(include_pause=True)[2])
    inputs.feed(pressed_keys=('k',))
    inputs.close()
    self.assertEqual(inputs.commands(include_pause=True), (True, False, False))

  def test_same_phase_reconnect_discards_taps_and_requires_neutral_observation(self):
    inputs = InputBuffer()
    inputs.feed(pressed_keys=('v',))
    inputs.set_suspended(False, reset=True)
    self.assertTrue(inputs.release_required)
    self.assertEqual(inputs.sample().buttons, 0)
    inputs.feed(keys=('w', 'v'))
    self.assertEqual(inputs.sample().buttons, 0)
    inputs.feed()
    inputs.feed(pressed_keys=('v',))
    self.assertEqual(inputs.sample().buttons, 8)
    self.assertEqual(inputs.sample().buttons, 0)


class LocalPauseTest(unittest.TestCase):
  setUp = local_fixture.PacingRuntimeTest.setUp
  tearDown = local_fixture.PacingRuntimeTest.tearDown
  factory = local_fixture.PacingRuntimeTest.factory

  def test_each_authoritative_hash_is_verified_and_refunded_with_one_hash_capacity(self):
    def client(host, port):
      return client_tcp.FrameSyncClient(host, port, limits=ClientLimits(hashes=1))
    with mock.patch.object(local_runtime, 'FrameSyncClient', client):
      with LocalPlayer(engine_factory=self.factory) as match:
        for frame in range(64):
          self.assertEqual(match.step()['frame'], frame)
        self.assertEqual(match.client.stats()['hashes'], 0)
        match.pause()
        self.assertIsNone(match.step())
        match.resume()
        self.assertEqual(match.step()['frame'], 64)
        self.assertEqual(match.client.stats()['hashes'], 0)

  def test_fragmented_hash_arrives_after_authority_without_leaking(self):
    with LocalPlayer(engine_factory=self.factory) as match:
      def split():
        runtime = match.server._runtime
        original = runtime.broadcast
        def broadcast(data):
          if data[0] == wire.MessageType.AuthoritativeFrame:
            original(data[:-13])
            runtime.loop.call_later(.01, original, data[-13:])
          else:
            original(data)
        runtime.broadcast = broadcast
      match.server._call(split)
      for frame in range(3):
        self.assertEqual(match.step()['frame'], frame)
      self.assertEqual(match.client.stats()['hashes'], 0)

  def test_wrong_hash_frame_or_value_fails_before_recording_publication(self):
    for bad_frame, bad_hash in ((1, 0), (0, 0)):
      with self.subTest(frame=bad_frame):
        replay = self.root / 'bad-hash.replay'
        replay.write_bytes(b'prior recording')
        with LocalPlayer(engine_factory=self.factory, record_path=str(replay)) as match:
          def corrupt():
            runtime = match.server._runtime
            original = runtime.broadcast
            def broadcast(data):
              if data[0] == wire.MessageType.AuthoritativeFrame:
                data = data[:-13] + wire.pack_state_hash(bad_frame, bad_hash)
              original(data)
            runtime.broadcast = broadcast
          match.server._call(corrupt)
          with self.assertRaisesRegex(RuntimeError, 'state hash'):
            match.step()
          self.assertTrue(match.stats()['closed'])
        self.assertEqual(replay.read_bytes(), b'prior recording')

  def test_authority_and_replica_freeze_before_first_frame_without_sampling(self):
    sampled, controls = [], []
    with LocalPlayer(engine_factory=self.factory,
                     input_provider=lambda frame: sampled.append(frame), on_control=controls.append) as match:
      initial = engine_digest(match.replica)
      paused = match.pause()
      self.assertEqual((paused.epoch, paused.phase, paused.next_frame), (1, PAUSED, 0))
      for _ in range(1000):
        self.assertIsNone(match.step())
      self.assertEqual(match.frame, 0)
      self.assertFalse(sampled)
      self.assertEqual(engine_digest(match.replica), initial)
      self.assertEqual(match.server._call(lambda: engine_digest(match.server._runtime.env)), initial)
      self.assertEqual(len(controls), 2)
      self.assertTrue(match.server.all_clients_ready())
      json.dumps(match.stats())

  def test_request_during_sampling_finishes_exactly_one_authority_frame(self):
    sampled = []
    def sample(frame):
      sampled.append(frame)
      match.pause()
      return wire.SlotInput(1., 0., 8)
    with LocalPlayer(engine_factory=self.factory, input_provider=sample) as match:
      result = match.step()
      self.assertEqual(result['frame'], 0)
      self.assertEqual(match.stats()['control']['next_frame'], 1)
      self.assertEqual(match.stats()['control']['phase'], PAUSED)
      self.assertIsNone(match.step())
      self.assertEqual(sampled, [0])
      self.assertEqual(match.frame, 1)
      self.assertEqual(match.server._call(lambda: engine_digest(match.server._runtime.env)), engine_digest(match.replica))

  def test_paused_save_resume_release_and_recording_replay(self):
    inputs, phases, sampled = InputBuffer(), [], []
    save, replay = str(self.root / 'match.save'), str(self.root / 'match.replay')
    def control(value):
      phases.append(value.phase)
      inputs.set_suspended(value.phase != RUNNING)
    def sample(frame):
      value = inputs.sample(frame)
      sampled.append((frame, value.buttons))
      return value
    with LocalPlayer(engine_factory=self.factory, input_provider=sample, on_control=control,
                     save_path=save, record_path=replay) as match:
      inputs.feed(keys=('w', 'v'))
      match.step()
      before = engine_digest(match.replica)
      match.pause()
      match.save()
      self.assertEqual(decode_checkpoint(read_checkpoint(save))[2], before)
      inputs.feed(keys=('w', 'v'))
      self.assertIsNone(match.step())
      resumed = match.resume()
      self.assertEqual((resumed.epoch, resumed.phase, resumed.next_frame), (2, RUNNING, 1))
      self.assertEqual(engine_digest(match.replica), before)
      inputs.feed(keys=('w', 'v'))
      match.step()
      inputs.feed()
      inputs.feed(pressed_keys=('v',))
      match.step()
      inputs.feed()
      match.step()
      final = engine_digest(match.replica)
    self.assertEqual(sampled, [(0, 8), (1, 0), (2, 8), (3, 0)])
    self.assertEqual(phases, [RUNNING, PAUSED, RESUMING, RUNNING])
    self.assertEqual(playback(replay, engine_factory=self.factory)['digest'], final)
    with LocalPlayer(engine_factory=self.factory, resume_path=save) as match:
      self.assertEqual(engine_digest(match.replica), before)
      self.assertEqual(match.stats()['control']['phase'], RUNNING)

  def test_run_processes_save_and_quit_while_paused_without_using_frame_limit(self):
    inputs, sampled = InputBuffer(), []
    save, replay = str(self.root / 'paused.save'), str(self.root / 'paused.replay')
    parent = self
    class Controls(BufferedControls):
      calls = 0
      def read(self):
        self.calls += 1
        if self.calls == 1:
          self.buffer.feed(pressed_keys=('k', 'v'))
        elif self.calls == 3:
          self.buffer.feed(pressed_keys=('p',))
        elif self.calls == 4:
          parent.assertTrue(Path(save).exists())
        elif self.calls == 5:
          self.buffer.request_quit()
        return super().read()
    with LocalPlayer(engine_factory=self.factory, input_provider=lambda frame: sampled.append(frame),
                     on_control=lambda c: inputs.set_suspended(c.phase != RUNNING),
                     save_path=save, record_path=replay) as match:
      result = match.run(1, realtime=False, controls=Controls(inputs))
    self.assertEqual(result['frames'], 0)
    self.assertEqual(result['control']['phase'], PAUSED)
    self.assertFalse(sampled)
    self.assertEqual(playback(replay, engine_factory=self.factory)['frames'], 0)

  def test_duplicate_request_and_invalid_thread_types_or_reentry_are_bounded(self):
    controls, errors = [], []
    def control(value):
      controls.append(value)
      if value.phase == PAUSED:
        with self.assertRaisesRegex(RuntimeError, 'control callback'):
          match.resume()
        with self.assertRaisesRegex(RuntimeError, 'reentrant'):
          match.step()
    with LocalPlayer(engine_factory=self.factory, on_control=control) as match:
      for invalid in (1, None, 'pause'):
        with self.assertRaises(ValueError):
          match.set_paused(invalid)
      def wrong_owner():
        try:
          match.pause()
        except RuntimeError as error:
          errors.append(str(error))
      worker = threading.Thread(target=wrong_owner)
      worker.start()
      worker.join(2)
      self.assertFalse(worker.is_alive())
      for _ in range(100):
        match.pause()
      self.assertEqual(len(controls), 2)
      self.assertEqual(len(errors), 1)
      match.resume()
      self.assertEqual(match.frame, 0)

  def test_callback_failure_closes_resources_and_preserves_prior_recording(self):
    replay = self.root / 'previous.replay'
    replay.write_bytes(b'previous complete recording')
    def control(value):
      if value.phase == PAUSED:
        raise RuntimeError('Injected pause input failure')
    with LocalPlayer(engine_factory=self.factory, record_path=str(replay), on_control=control) as match:
      with self.assertRaisesRegex(RuntimeError, 'Injected pause input failure'):
        match.pause()
      self.assertTrue(match.stats()['closed'])
    self.assertEqual(replay.read_bytes(), b'previous complete recording')

  def test_divergent_replica_cannot_acknowledge_local_pause(self):
    with LocalPlayer(engine_factory=self.factory) as match:
      match.replica.step_with_input(wire.pack_slot_input(wire.default_slot_input()))
      with self.assertRaisesRegex(RuntimeError, 'boundary diverged'):
        match.pause()
      self.assertTrue(match.stats()['closed'])

  def test_ready_host_can_remain_paused_before_frame_zero_past_lobby_deadline(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        inputs = InputBuffer()
        class Controls(BufferedControls):
          started = None
          def read(self):
            if self.started is None:
              self.started = time.monotonic()
              self.buffer.feed(pressed_keys=('k',))
            elif time.monotonic() - self.started > .15:
              self.buffer.request_quit()
            return super().read()
        with HostedMatch(left=1, right=0, transport=transport, engine_factory=self.factory,
                         input_provider=inputs.sample) as match:
          result = match.run(1, realtime=False, lobby_timeout=.03, controls=Controls(inputs))
        self.assertEqual(result['frame'], 0)
        self.assertTrue(result['end_acknowledged'])

  def test_pause_request_does_not_disable_missing_participant_deadline(self):
    for transport in ('tcp', 'udp'):
      with self.subTest(transport=transport):
        inputs = InputBuffer()
        inputs.feed(pressed_keys=('k',))
        with HostedMatch(transport=transport, engine_factory=self.factory,
                         input_provider=inputs.sample) as match:
          with self.assertRaisesRegex(TimeoutError, 'participants timed out'):
            match.run(1, realtime=False, lobby_timeout=.04, controls=BufferedControls(inputs))
          self.assertTrue(match.stats()['closed'])
          self.assertEqual(match.frame, 0)

  def test_real_heartbeat_keeps_paused_local_transport_alive(self):
    with LocalPlayer(engine_factory=self.factory) as match:
      match.pause()
      digest = engine_digest(match.replica)
      deadline = time.monotonic() + 3.2
      while time.monotonic() < deadline:
        self.assertIsNone(match.step())
        time.sleep(.02)
      self.assertTrue(match.server.all_clients_ready())
      match.resume()
      self.assertEqual(engine_digest(match.replica), digest)
      self.assertEqual(match.step()['frame'], 0)


class GraphicalPauseTest(unittest.TestCase):
  setUp = graphical_fixture.GraphicalRuntimeTest.setUp
  tearDown = graphical_fixture.GraphicalRuntimeTest.tearDown
  factory = graphical_fixture.GraphicalRuntimeTest.factory
  display_factory = graphical_fixture.GraphicalRuntimeTest.display_factory
  run_match = graphical_fixture.GraphicalRuntimeTest.run_match
  spawn = graphical_fixture.GraphicalRuntimeTest.spawn

  def pause_case(self, mode, transport='tcp'):
    save, replay = str(self.root / 'paused.save'), str(self.root / 'paused.replay')
    observed = dict(paused=0, release=False, resumed=False)
    phase = 'pause'
    deadline = time.monotonic() + 8
    def ready(info):
      def poll():
        nonlocal phase
        self.display.check()
        if time.monotonic() >= deadline:
          raise TimeoutError('Graphical pause scenario did not complete')
        label = self.display.statuses[-1]
        if phase == 'pause':
          phase = 'wait_pause'
          return dict(keys=('k', 'w', 'v'))
        if phase == 'wait_pause' and label.startswith('Paused -'):
          phase = 'save'
        if phase == 'save':
          self.assertEqual(self.display.frames, 0)
          observed['paused'] += 1
          if observed['paused'] == 8:
            return dict(keys=('w', 'v'), pressed_keys=('p',))
          if observed['paused'] > 12 and Path(save).exists():
            phase = 'wait_release'
            return dict(keys=('w', 'v'), pressed_keys=('k',))
        if phase == 'wait_release' and label.startswith('Release movement'):
          observed['release'] = True
          phase = 'released'
          return dict()
        if phase == 'released':
          observed['resumed'] = True
          return dict(keys=('w',), pressed_keys=('v',))
        return dict(keys=('w', 'v'))
      self.display.poll_input = poll
    options = dict(save_path=save, record_path=replay)
    if mode == 'host':
      options.update(left=1, right=0, transport=transport)
    result = self.run_match(mode, max_frames=5, options=options, on_ready=ready)
    self.assertGreaterEqual(observed['paused'], 12)
    self.assertTrue(observed['release'] and observed['resumed'])
    self.assertEqual(result['match'].get('frames', result['match'].get('frame')), 5)
    self.assertTrue(playback(replay, engine_factory=self.factory)['verified'])
    self.assertLessEqual(len(self.display.statuses), 8)
    self.assertTrue(any('Paused -' in text for text in self.display.statuses))

  def test_local_ui_pause_save_release_resume_and_natural_finish(self):
    self.pause_case('local')

  def test_tcp_host_ui_pause_save_release_resume_and_natural_finish(self):
    self.pause_case('host', 'tcp')

  def test_udp_host_ui_pause_save_release_resume_and_natural_finish(self):
    self.pause_case('host', 'udp')

  def join_case(self, transport):
    port = queue.Queue(maxsize=1)
    resume = threading.Event()
    results, paused_polls = [], 0
    def host():
      with HostedMatch(transport=transport, engine_factory=self.factory) as match:
        port.put_nowait(match.port)
        match.pause()
        deadline = time.monotonic() + 8
        while match.frame < 5:
          if time.monotonic() >= deadline:
            raise TimeoutError('Join pause scenario did not complete')
          if resume.is_set():
            match.resume()
          match.advance()
          time.sleep(.005)
        results.append(match.finish())
    def ready(info):
      def poll():
        nonlocal paused_polls
        self.display.check()
        if self.display.statuses[-1].startswith('Paused by host'):
          paused_polls += 1
          self.assertEqual(self.display.frames, 0)
          if paused_polls == 14:
            resume.set()
          # A Join pause key cannot change host authority.
          return dict(pressed_keys=('k',), keys=('v',))
        return dict()
      self.display.poll_input = poll
    self.spawn(host)
    result = self.run_match('join', max_frames=100,
        options=dict(port=port.get(timeout=4), transport=transport), on_ready=ready)
    for worker in self.workers:
      worker.join(8)
    self.assertGreaterEqual(paused_polls, 14)
    self.assertTrue(result['match']['ended'])
    self.assertEqual(results, [True])

  def test_tcp_join_shows_host_pause_and_cannot_resume_authority(self):
    self.join_case('tcp')

  def test_udp_join_shows_host_pause_and_cannot_resume_authority(self):
    self.join_case('udp')

  def test_hud_failure_closes_all_owners_and_preserves_recording(self):
    replay = self.root / 'prior.replay'
    replay.write_bytes(b'prior output')
    def ready(info):
      # 2026-09-10: one held key models one pause request; repeated edge events toggle intent.
      # self.display.input = dict(pressed_keys=('k',))
      self.display.input = dict(keys=('k',))
      original = self.display.set_match_status
      def failed(text):
        if text.startswith('Paused -'):
          raise RuntimeError('Injected HUD failure')
        original(text)
      self.display.set_match_status = failed
    with self.assertRaisesRegex(RuntimeError, 'Injected HUD failure'):
      self.run_match(max_frames=1, options=dict(record_path=str(replay)), on_ready=ready)
    self.assertEqual(replay.read_bytes(), b'prior output')


if __name__ == '__main__':
  unittest.main()
