"""Owned multiplayer player/host loops with real input, reconciliation and exit."""
from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
import math
import os
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.local_runtime import TerminalControls
from gfootball.frame_sync.match_archive import MatchRecorder, capture, input_bytes, positions, write_checkpoint
from gfootball.frame_sync.multiplayer_transport import MatchReconnectingClient, MatchServer
# 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
# from gfootball.frame_sync.server_state import ServerFailure
from gfootball.frame_sync.server_state import ServerFailure
from gfootball.frame_sync.match_control import RUNNING
# 2026-09-10: Host observes the authority's End; it never ends from replica prediction.
# from gfootball.frame_sync.match_lifecycle import match_finished


def _match_transport(transport, udp_limits=None, cookie_limits=None):
  if type(transport) is not str or transport not in ('tcp', 'udp'):
    raise ValueError('Match transport must be tcp or udp')
  if transport == 'tcp':
    if udp_limits is not None or cookie_limits is not None:
      raise ValueError('UDP limits require UDP transport')
    return MatchServer, MatchReconnectingClient
  from gfootball.frame_sync.multiplayer_udp import MatchUDPServer, MatchReconnectingUDPClient
  return MatchUDPServer, MatchReconnectingUDPClient


# 2026-09-10: graphics supplies an interactive exit path.
# def _frame_limit(value):
def _frame_limit(value, *, interactive=False):
  if value is not None and (type(value) is not int or not 1 <= value <= 1000000):
    raise ValueError('Frame limit must be 1..1000000')
  # 2026-09-10: allow unbounded play only with an interactive control source.
  # if value is None and not sys.stdin.isatty():
  if value is None and not sys.stdin.isatty() and not interactive:
    raise ValueError('Noninteractive play requires a frame limit')


def _seconds(value, name, maximum):
  if type(value) not in (int, float) or not math.isfinite(value) or not .01 <= value <= maximum:
    raise ValueError('Invalid ' + name)
  return value


def _cleanup(operation, primary=None):
  try:
    operation()
  except BaseException:
    if primary is None:
      raise
    if hasattr(primary, 'add_note'):
      primary.add_note('Multiplayer cleanup also failed; the original failure is preserved.')


class NetworkPlayer:
  # 2026-09-10: control notifications clear caller-owned input before ACK.
  # def __init__(self, host='127.0.0.1', port=12345, *, engine_factory=None,
  #              input_provider=None, on_frame=None, client_limits=None, logic_limits=None,
  #              reconnect_limits=None, transport='tcp', udp_limits=None):
  #   for value in (engine_factory, input_provider, on_frame):
  def __init__(self, host='127.0.0.1', port=12345, *, engine_factory=None,
               input_provider=None, on_frame=None, client_limits=None, logic_limits=None,
               reconnect_limits=None, transport='tcp', udp_limits=None, on_control=None):
    for value in (engine_factory, input_provider, on_frame, on_control):
      if value is not None and not callable(value):
        raise ValueError('Expected a callable match hook')
    self._owner, self._pid = threading.current_thread(), os.getpid()
    self._factory, self._input_provider, self._on_frame = engine_factory, input_provider, on_frame
    self._logic_limits = logic_limits
    # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
    # self._on_control = on_control
    self._on_control = on_control
    self._controls = None
    # 2026-09-10: select the real transport without changing engine ownership.
    # self.client = MatchReconnectingClient(host, port, self._sample,
    #     limits=client_limits, reconnect_limits=reconnect_limits)
    _, client_type = _match_transport(transport, udp_limits)
    self.transport = transport
    network_options = dict(udp_limits=udp_limits) if transport == 'udp' else {}
    # self.client = client_type(host, port, self._sample, limits=client_limits,
    #     reconnect_limits=reconnect_limits, **network_options)
    self.client = client_type(host, port, self._sample, limits=client_limits,
        reconnect_limits=reconnect_limits, on_control=self._control_changed, **network_options)
    self.env = self.settings = None
    self.slots = ()
    self._started = self._closed = self._in_tick = self._playing = self._ended = False
    # 2026-09-10: ClientLogicLoop owns lobby input identity and retry timestamps.
    # self._first_input = None
    # self._first_sent = 0.0
    self._control_value = wire.default_slot_input()
    self._last = None
    self._failure = None
    self._final_frame = None

  def _control_changed(self, control):
    self._check()
    # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
    # self._control_value = wire.default_slot_input()
    # if self._on_control is not None:
    self._control_value = wire.default_slot_input()
    if callable(getattr(self._controls, 'set_suspended', None)):
      self._controls.set_suspended(control.phase != RUNNING)
    if self._on_control is not None:
      self._on_control(control)

  def _check(self):
    if threading.current_thread() is not self._owner or os.getpid() != self._pid:
      raise RuntimeError('Network match belongs to its creating thread')

  def _sample(self):
    self._check()
    frame = self.client.logic.get_current_frame_id() if self.client.logic is not None else 0
    value = self._input_provider(frame) if self._input_provider is not None else self._control_value
    input_bytes(value)
    if len(self.slots) != 1:
      raise ClientFailure('unsupported_match_slot_assignment')
    return [(self.slots[0], value)]

  def start(self):
    self._check()
    if self._started or self._closed:
      raise RuntimeError('Create a new network player for a new match')
    self._started = True
    try:
      self.env, self.settings, slots = self.client.connect_match(self._factory, logic_limits=self._logic_limits)
      if len(slots) != 1:
        raise ClientFailure('unsupported_match_slot_assignment')
      self.slots = tuple(slots)
      return self.settings, self.slots
    # 2026-09-10: an initialization failure must survive secondary cleanup errors.
    # except BaseException:
    #   self.close()
    except BaseException as error:
      _cleanup(self.close, error)
      raise

  def tick(self):
    self._check()
    if not self._started or self._closed:
      raise RuntimeError('Network match is not running')
    if self._in_tick:
      raise RuntimeError('Concurrent or reentrant network tick')
    self._in_tick = True
    try:
      return self._tick_owned()
    except BaseException as error:
      self._failure = error.reason if isinstance(error, ClientFailure) else str(error)
      self._in_tick = False
      try:
        self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Network player failure cleanup also failed.')
      raise
    finally:
      self._in_tick = False

  def _tick_owned(self):
    if self._ended:
      return self.stats()
    self.client.tick()
    if self.client.failure_reason:
      raise ClientFailure(self.client.failure_reason)
    if self.client.is_reconnecting:
      return self.stats()
    transport, logic = self.client.client, self.client.logic
    # Let the existing recovery owner classify a newly closed socket. It may
    # observe that closure just after this tick acquired the connected state.
    if transport.is_disconnected():
      return self.stats()
    ending = transport.match_end
    # 2026-09-10: one logic input cache handles lobby retries and pause epochs.
    # if not self._playing and not transport.has_authoritative_frame() and ending is None:
    #   if self._first_input is None:
    #     self._first_input = self._sample()
    #   now = time.monotonic()
    #   if now - self._first_sent >= .1:
    #     if not transport.send_frame_entries(0, self._first_input):
    #       raise ClientFailure(transport.failure_reason or 'input_failed')
    #     self._first_sent = now
    #   return self.stats()
    # self._playing = True
    self._playing |= transport.has_authoritative_frame() or ending is not None
    # 2026-09-10: the duplicate lobby input cache has been removed.
    # self._first_input = None
    if ending is None or logic.get_last_confirmed_frame_id() < ending[0] - 1:
      # 2026-09-10: process barriers in the lobby without speculative advancement.
      # logic.run_one_tick()
      # 2026-09-10: IO loss during sampling or barrier ACK is still recoverable.
      # logic.run_one_tick(allow_prediction=self._playing)
      try:
        logic.run_one_tick(allow_prediction=self._playing)
      except ClientFailure as error:
        if error.reason in self.client._retryable and transport.is_disconnected():
          return self.stats()
        raise
      if logic.failure_reason:
        if logic.failure_reason in self.client._retryable and transport.is_disconnected():
          return self.stats()
        raise ClientFailure(logic.failure_reason)
    # 2026-09-21: authority can arrive after the queue peek and be consumed this tick.
    # Its committed boundary must also release the lobby/prediction barrier.
    self._playing |= logic.get_last_confirmed_frame_id() >= 0
    ending = transport.match_end
    if ending is not None and logic.get_last_confirmed_frame_id() == ending[0] - 1:
      logic.finish_at(*ending)
      if not transport.acknowledge_end(ending[0]):
        raise ClientFailure(transport.failure_reason or 'end_ack_failed')
      self._ended, self._final_frame = True, ending[0]
    ball, _, score = positions(self.env)
    current = dict(frame=logic.get_current_frame_id() - 1,
        confirmed=logic.get_last_confirmed_frame_id(), ball=ball, score=score,
        # 2026-09-10: publish control feedback even when the game frame is unchanged.
        # ended=self._ended, rollbacks=logic.get_rollback_count())
        ended=self._ended, rollbacks=logic.get_rollback_count(),
        control_epoch=logic.control_state.epoch, control_phase=logic.control_state.phase)
    if current != self._last:
      self._last = current
      if self._on_frame is not None:
        self._on_frame(dict(current))
    return self.stats()

  def flush_end_ack(self, seconds=2):
    self._check()
    deadline = time.monotonic() + _seconds(seconds, 'end acknowledgement deadline', 10)
    while self._ended and self.client.client.output_pending():
      if self.client.client.is_disconnected() or time.monotonic() >= deadline:
        raise ClientFailure('end_ack_timeout')
      time.sleep(.001)

  # 2026-09-10: share the run loop with graphical input.
  # def run(self, max_frames=None, *, realtime=True):
  def run(self, max_frames=None, *, realtime=True, controls=None):
    self._check()
    # 2026-09-10: window input supports non-TTY play.
    # _frame_limit(max_frames)
    _frame_limit(max_frames, interactive=getattr(controls, 'is_graphical', False))
    if type(realtime) is not bool:
      raise ValueError('Expected a realtime flag')
    # 2026-09-10: construction failure must enter owner cleanup too.
    # pacer = FramePacer(MATCH_HZ)
    pacer = None
    try:
      pacer = FramePacer(MATCH_HZ)
      # 2026-09-10: commands are polled even with an external action provider.
      # with TerminalControls() as controls:
      # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
      # with (TerminalControls() if controls is None else controls) as controls:
      #   while not self._closed and not self._ended:
      with (TerminalControls() if controls is None else controls) as controls:
        self._controls = controls
        if callable(getattr(controls, 'set_suspended', None)):
          controls.set_suspended(self.client.logic.control_state.phase != RUNNING)
        while not self._closed and not self._ended:
          # 2026-09-10: sample after the absolute deadline; wake for UI exit.
          # started = time.monotonic()
          admitted = pacer.wait_next(getattr(controls, 'wait', None)) if realtime else True
          # 2026-09-10: UI quit must be observed when actions use a provider.
          # if self._input_provider is None:
          #   self._control_value = controls.read()
          #   if controls.quit:
          #     break
          value = controls.read()
          # 2026-09-10: a cancelled wait does not advance the match.
          # if controls.quit:
          if controls.quit or not admitted:
            break
          if self._input_provider is None:
            self._control_value = value
          self.tick()
          if max_frames is not None and self.client.logic.get_last_confirmed_frame_id() + 1 >= max_frames:
            break
          # 2026-09-10: preserve fast-mode I/O fairness; realtime waits before work.
          # time.sleep(max(0.0, .1 - (time.monotonic() - started)) if realtime else .001)
          if not realtime:
            time.sleep(.001)
      self.flush_end_ack()
    except KeyboardInterrupt:
      pass
    finally:
      # 2026-09-10: keep the primary input/transport/engine failure on shutdown.
      # self.close()
      _cleanup(self.close, sys.exc_info()[1])
    # 2026-09-10: scheduling opportunities are separate from authoritative frames.
    # return self.stats()
    # 2026-09-10: interruption during scheduler construction admits no ticks.
    # return dict(self.stats(), pacing=pacer.stats())
    return dict(self.stats(), pacing=None if pacer is None else pacer.stats())

  def stats(self):
    self._check()
    return dict(running=self._started and not self._closed, closed=self._closed,
        waiting_for_players=self._started and not self._playing and not self._closed,
        ended=self._ended, final_frame=self._final_frame, failure=self._failure,
        slots=self.slots, last=dict(self._last) if self._last is not None else None,
        transport=self.client.stats())

  def close(self):
    self._check()
    if self._in_tick:
      raise RuntimeError('Cannot close a network player inside its tick')
    if self._closed:
      return
    error = None
    try:
      self.client.close()
    except BaseException as caught:
      error = caught
    try:
      if self.env is not None:
        self.env.close()
    except BaseException as caught:
      error = error or caught
    finally:
      # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
      # self.env = None
      # # 2026-09-10: the logic owner refunds all input storage on close.
      self.env = None
      self._controls = None
      # 2026-09-10: the logic owner refunds all input storage on close.
      # self._first_input = None
      self._closed = True
    if error is not None:
      raise error

  def __enter__(self):
    self.start()
    return self

  # 2026-09-10: preserve an exception from the context body.
  # def __exit__(self, *_):
  #   self.close()
  def __exit__(self, kind, value, traceback):
    _cleanup(self.close, value)


class HostedMatch:
  """Host is also a real player. Main thread drives one server-owned match."""
  def __init__(self, *, scenario='academy_empty_goal', left=1, right=1, seed=42,
               listen_host='0.0.0.0', port=0, engine_factory=None, input_provider=None,
               on_frame=None, record_path=None, save_path=None, replay_limits=None,
               server_limits=None, client_limits=None, logic_limits=None, reconnect_limits=None,
               # 2026-09-10: input owner is notified at the same host-client barrier.
               # transport='tcp', udp_limits=None, cookie_limits=None):
               transport='tcp', udp_limits=None, cookie_limits=None, on_control=None):
    self._owner, self._pid = threading.current_thread(), os.getpid()
    for path in (record_path, save_path):
      if path is not None and (type(path) is not str or not 1 <= len(path) <= 4096 or '\0' in path):
        raise ValueError('Invalid match output path')
    # 2026-09-10: both transports use the same authoritative match lifecycle.
    # self.server = MatchServer(listen_host=listen_host, listen_port=port, scenario_name=scenario,
    #     left_agents=left, right_agents=right, game_engine_random_seed=seed, state_hash_interval=1,
    #     engine_factory=engine_factory, limits=server_limits)
    server_type, _ = _match_transport(transport, udp_limits, cookie_limits)
    self.transport = transport
    network_options = dict(udp_limits=udp_limits, cookie_limits=cookie_limits) if transport == 'udp' else {}
    self.server = server_type(listen_host=listen_host, listen_port=port, scenario_name=scenario,
        left_agents=left, right_agents=right, game_engine_random_seed=seed, state_hash_interval=1,
        engine_factory=engine_factory, limits=server_limits, **network_options)
    self._player_options = dict(engine_factory=engine_factory, input_provider=input_provider, on_frame=on_frame,
        client_limits=client_limits, logic_limits=logic_limits, reconnect_limits=reconnect_limits,
        transport=transport, udp_limits=udp_limits)
    self._player_options['on_control'] = on_control
    self.player = self._recorder = None
    self._record_path, self._save_path, self._replay_limits = record_path, save_path, replay_limits
    self._started = self._closed = False
    self._advancing = False
    self.frame = 0
    self.port = port
    self.end_acknowledged = False

  def _check(self):
    if threading.current_thread() is not self._owner or os.getpid() != self._pid:
      raise RuntimeError('Hosted match belongs to its creating thread')

  def start(self):
    self._check()
    if self._started or self._closed:
      raise RuntimeError('Create a new host for a new match')
    self._started = True
    try:
      self.server.start()
      self.port = self.server.listen_port
      if self._record_path is not None:
        self._recorder = self.server._call(lambda: MatchRecorder(self.server._runtime.settings,
            self.server._runtime.env, limits=self._replay_limits))
      self.player = NetworkPlayer('127.0.0.1', self.port, **self._player_options)
      self.player.start()
      return self.port
    # 2026-09-10: preserve factory failure even if shutdown also fails.
    # except BaseException:
    #   self.close(finalize=False)
    except BaseException as error:
      _cleanup(lambda: self.close(finalize=False), error)
      raise

  def save(self):
    self._check()
    if self._closed or not self._started or self._save_path is None:
      raise RuntimeError('A running host and checkpoint path are required')
    value = self.server._call(lambda: capture(self.server._runtime.settings, self.server._runtime.env))
    write_checkpoint(self._save_path, value)
    return dict(frame=self.frame, digest=value['digest'], path=self._save_path)

  def set_paused(self, paused):
    self._check()
    if self._closed or not self._started:
      raise RuntimeError('Hosted match is not running')
    return self.server.set_paused(paused)

  def pause(self):
    return self.set_paused(True)

  def resume(self):
    return self.set_paused(False)

  def advance(self):
    self._check()
    if not self._started or self._closed:
      raise RuntimeError('Hosted match is not running')
    if self._advancing:
      raise RuntimeError('Concurrent or reentrant host frame')
    self._advancing = True
    try:
      return self._advance_owned()
    except BaseException as error:
      self._advancing = False
      _cleanup(lambda: self.close(finalize=False), error)
      raise
    finally:
      self._advancing = False

  def _advance_owned(self):
    self.player.tick()
    if self.server._call(lambda: self.server._runtime._ending is not None):
      return False
    if not self.server._call(lambda: self.server._runtime.started) and not self.server.participants_ready():
      return False
    try:
      # 2026-09-13: use the match authority collection budget instead of a fixed 100 ms wait.
      # frame, inputs = self.server.run_one_frame(100)
      frame, inputs = self.server.run_one_frame()
    except ServerFailure as error:
      # 2026-09-10: a frozen authority still lets player IO/control ticks run.
      # if error.reason == 'participants_not_ready':
      if error.reason in ('participants_not_ready', 'match_paused'):
        return False
      raise
    if self._recorder is not None:
      self.server._call(lambda: self._recorder.record(frame, inputs, self.server._runtime.env))
    self.frame = frame + 1
    self.player.tick()
    return True

  def finish(self, grace_seconds=2):
    self._check()
    grace_seconds = _seconds(grace_seconds, 'finish grace period', 10)
    self.server.finish_match()
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
      self.player.tick()
      # 2026-09-10: acknowledge status and UDP final retry grace are distinct.
      # if self.server.finish_acknowledged():
      #   self.end_acknowledged = True
      #   break
      self.end_acknowledged = self.server.finish_acknowledged()
      if self.server.finish_settled():
        # 2026-09-10: an Ack can arrive between the two server-owner calls.
        # break
        self.end_acknowledged = True
        break
      time.sleep(.001)
    self.player.flush_end_ack()
    return self.end_acknowledged

  # 2026-09-10: share the host loop with graphical input.
  # def run(self, max_frames=None, *, realtime=True, lobby_timeout=60, finish_grace=2):
  def run(self, max_frames=None, *, realtime=True, lobby_timeout=60, finish_grace=2, controls=None):
    self._check()
    # 2026-09-10: window input supports non-TTY play.
    # _frame_limit(max_frames)
    _frame_limit(max_frames, interactive=getattr(controls, 'is_graphical', False))
    _seconds(lobby_timeout, 'lobby timeout', 300)
    _seconds(finish_grace, 'finish grace period', 10)
    if type(realtime) is not bool:
      raise ValueError('Expected a realtime flag')
    completed = False
    # 2026-09-10: construction failure must enter owner cleanup too.
    # pacer = FramePacer(MATCH_HZ)
    pacer = None
    try:
      pacer = FramePacer(MATCH_HZ)
      # 2026-09-10: bounded pause commands and input release across owner transitions.
      # lobby_deadline = time.monotonic() + lobby_timeout
      lobby_deadline = time.monotonic() + lobby_timeout
      lobby_ready = False
      # 2026-09-10: commands are polled even with an external action provider.
      # with TerminalControls() as controls:
      # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
      # with (TerminalControls() if controls is None else controls) as controls:
      #   # 2026-09-10: authority may finish naturally before the caller's limit.
      with (TerminalControls() if controls is None else controls) as controls:
        self.player._controls = controls
        if callable(getattr(controls, 'set_suspended', None)):
          controls.set_suspended(self.player.client.logic.control_state.phase != RUNNING)
        # 2026-09-10: authority may finish naturally before the caller's limit.
        # while max_frames is None or self.frame < max_frames:
        while (max_frames is None or self.frame < max_frames) and not self.server._call(
            lambda: self.server._runtime._ending is not None):
          # 2026-09-10: sample after the absolute deadline; wake for UI exit.
          # started = time.monotonic()
          admitted = pacer.wait_next(getattr(controls, 'wait', None)) if realtime else True
          # 2026-09-10: quit/save are independent of the action provider.
          # if self._player_options['input_provider'] is None:
          #   self.player._control_value = controls.read()
          #   if controls.quit:
          #     break
          #   if controls.save and self._save_path is not None:
          #     self.save()
          value = controls.read()
          # 2026-09-10: a cancelled wait does not advance the match.
          # if controls.quit:
          if controls.quit or not admitted:
            break
          if controls.save and self._save_path is not None:
            self.save()
          # 2026-09-10: bounded pause commands and input release across owner transitions.
          # if self._player_options['input_provider'] is None:
          #   self.player._control_value = value
          # advanced = self.advance()
          # if not advanced and self.frame == 0 and time.monotonic() >= lobby_deadline:
          if getattr(controls, 'pause', False):
            desired = self.server._call(lambda: self.server._runtime._desired_paused)
            self.set_paused(not desired)
          # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
          # phase = self.player.client.logic.control_state.phase
          # if callable(getattr(controls, 'set_suspended', None)):
          #   controls.set_suspended(phase != 'running')
          # Subsequent suspension is applied by NetworkPlayer._control_changed.
          if self._player_options['input_provider'] is None:
            self.player._control_value = value
          advanced = self.advance()
          lobby_ready |= self.server.participants_ready()
          if not advanced and self.frame == 0 and not lobby_ready and time.monotonic() >= lobby_deadline:
            raise TimeoutError('Waiting for match participants timed out')
          # 2026-09-10: preserve fast-mode I/O fairness; realtime waits before work.
          # time.sleep(max(0.0, .1 - (time.monotonic() - started)) if realtime else .001)
          if not realtime:
            time.sleep(.001)
      self.finish(finish_grace)
      if self._save_path is not None:
        self.save()
      completed = True
    except KeyboardInterrupt:
      self.finish(finish_grace)
      completed = True
    finally:
      # 2026-09-10: cleanup failure cannot replace the original simulation error.
      # self.close(finalize=completed)
      _cleanup(lambda: self.close(finalize=completed), sys.exc_info()[1])
    # 2026-09-10: scheduling opportunities are separate from authoritative frames.
    # return self.stats()
    # 2026-09-10: interruption during scheduler construction admits no ticks.
    # return dict(self.stats(), pacing=pacer.stats())
    return dict(self.stats(), pacing=None if pacer is None else pacer.stats())

  def stats(self):
    self._check()
    return dict(running=self._started and not self._closed, closed=self._closed, frame=self.frame,
        port=self.port, end_acknowledged=self.end_acknowledged,
        player=self.player.stats() if self.player is not None else None)

  def close(self, *, finalize=True):
    self._check()
    if self._advancing:
      raise RuntimeError('Cannot close a host inside its active frame')
    if self._closed:
      return
    errors = []
    try:
      if self._recorder is not None:
        try:
          if finalize:
            replay = self.server._call(lambda: self._recorder.finish(self.server._runtime.env))
            replay.save(self._record_path)
        finally:
          # 2026-09-10: after an engine failure the owner may already be closed.
          # Refund native-independent storage without submitting to a dead loop.
          # self.server._call(self._recorder.close)
          if not self.server._runtime.closed:
            self.server._call(self._recorder.close)
          self._recorder.manager.close()
    except BaseException as error:
      errors.append(error)
    for operation in (self.player.close if self.player is not None else None, self.server.stop):
      if operation is not None:
        try:
          operation()
        except BaseException as error:
          errors.append(error)
    if self._recorder is not None:
      self._recorder.manager.close()
      self._recorder = None
    self._closed = True
    if errors:
      raise errors[0]

  def __enter__(self):
    self.start()
    return self

  # 2026-09-10: preserve the exception from the caller's context body.
  # def __exit__(self, kind, *_):
  #   self.close(finalize=kind is None)
  def __exit__(self, kind, value, traceback):
    _cleanup(lambda: self.close(finalize=kind is None), value)
