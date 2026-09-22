"""Single-owner local match with real TCP authority, replica, save and replay."""
from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
import os
import select
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_tcp import FrameSyncClient
from gfootball.frame_sync.match_archive import (
    MatchRecorder, capture, decode_checkpoint, engine_digest, input_bytes, positions,
    read_checkpoint, write_checkpoint,
)
from gfootball.frame_sync.server_api import FrameSyncServer
# 2026-09-10: Use the identified native engine for local archive operations.
# from gfootball.frame_sync.server_runtime import ServerSettings, native_engine
from gfootball.frame_sync.server_runtime import ServerSettings
from gfootball.frame_sync.match_identity import require_identity, native_match_engine as native_engine
# 2026-09-10: authoritative local pause and bounded command ownership.
# from gfootball.frame_sync.match_lifecycle import match_finished
from gfootball.frame_sync.match_lifecycle import match_finished
from gfootball.frame_sync.match_control import MatchControl, RUNNING, PAUSED, RESUMING


class TerminalControls:
  """Terminal direction commands persist until 0; action keys last one frame."""
  def __init__(self):
    self.direction = (0., 0.)
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # self.quit = self.save = False
    self.quit = self.save = self.pause = self._suspended = False
    self._original = self._descriptor = None

  def __enter__(self):
    if os.name != 'nt' and sys.stdin.isatty():
      import termios
      import tty
      self._descriptor = sys.stdin.fileno()
      self._original = termios.tcgetattr(self._descriptor)
      tty.setcbreak(self._descriptor)
    return self

  def __exit__(self, *_):
    if self._original is not None:
      import termios
      termios.tcsetattr(self._descriptor, termios.TCSADRAIN, self._original)
      self._original = None

  # 2026-09-10: bounded pause commands and input release across owner transitions.
  # def read(self):
  #   self.save = False
  def set_suspended(self, suspended):
    if type(suspended) is not bool:
      raise ValueError('Suspension must be boolean')
    if suspended != self._suspended:
      self.direction = (0., 0.)
    self._suspended = suspended

  def read(self):
    self.save = self.pause = False
    buttons = 0
    for _ in range(32):
      if not sys.stdin.isatty():
        break
      if os.name == 'nt':
        import msvcrt
        if not msvcrt.kbhit():
          break
        key = msvcrt.getwch().lower()
      else:
        if not select.select([sys.stdin], [], [], 0)[0]:
          break
        key = os.read(self._descriptor, 1).decode('ascii', errors='ignore').lower()
      if key in ('q', '\x1b'):
        self.quit = True
      # 2026-09-10: bounded pause commands and input release across owner transitions.
      # elif key == 'p':
      #   self.save = True
      elif key == 'p':
        self.save = True
      elif key == 'k':
        self.pause = not self.pause
        self.direction, buttons = (0., 0.), 0
      elif self._suspended or self.pause:
        continue
      elif key in {'w', 's', 'a', 'd', '0'}:
        self.direction = {'w': (0., 1.), 's': (0., -1.), 'a': (-1., 0.), 'd': (1., 0.), '0': (0., 0.)}[key]
      elif key in {'z', 'x', 'c', 'v', ' '}:
        buttons |= 1 << {'z': 2, 'x': 1, 'c': 0, 'v': 3, ' ': 6}[key]
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # return wire.SlotInput(*self.direction, buttons)
    return wire.default_slot_input() if self._suspended or self.pause else wire.SlotInput(*self.direction, buttons)


class LocalPlayer:
  """One main-thread replica and one server-owned engine; no free-port race.

  engine_factory is an explicit embedding seam; omission constructs GameEnv.
  start, step, save and stop belong to the creating thread. No simulation owner
  is shared with file I/O: snapshot capture runs through the server's owner.
  """
  def __init__(self, scenario='academy_empty_goal', port=None, left_agents=1,
               right_agents=0, seed=42, controlled_slots=None, *, engine_factory=None,
               record_path=None, save_path=None, resume_path=None, replay_limits=None,
               # 2026-09-10: authoritative local pause and bounded command ownership.
               # input_provider=None, on_frame=None):
               input_provider=None, on_frame=None, on_control=None):
    if controlled_slots is not None and controlled_slots not in ([0], (0,)):
      raise ValueError('Local keyboard controls exactly the assigned slot 0')
    if engine_factory is not None and not callable(engine_factory):
      raise ValueError('Expected an engine factory')
    if input_provider is not None and not callable(input_provider):
      raise ValueError('Expected an input provider')
    # 2026-09-10: authoritative local pause and bounded command ownership.
    # if on_frame is not None and not callable(on_frame):
    #   raise ValueError('Expected a frame callback')
    if any(hook is not None and not callable(hook) for hook in (on_frame, on_control)):
      raise ValueError('Expected a match callback')
    self._settings = ServerSettings(listen_host='127.0.0.1', listen_port=0 if port is None else port,
        scenario_name=scenario, left_agents=left_agents, right_agents=right_agents,
        game_engine_random_seed=seed, state_hash_interval=1)
    for value in (record_path, save_path, resume_path):
      if value is not None and (type(value) is not str or not 1 <= len(value) <= 4096 or '\0' in value):
        raise ValueError('Expected a bounded file path string')
    self._owner, self._pid = threading.current_thread(), os.getpid()
    self._factory = engine_factory or native_engine
    self._record_path, self._save_path, self._resume_path = record_path, save_path, resume_path
    self._replay_limits, self._input_provider, self._on_frame = replay_limits, input_provider, on_frame
    self.server = self.client = self.replica = self._recorder = None
    self._started = self._closed = self._running = False
    self._stepping = False
    self.frame = 0
    self.port = self._settings.listen_port
    self._last = None
    self._controls = None
    # 2026-09-10: authoritative local pause and bounded command ownership.
    # self._ended = False
    self._ended = False
    self._on_control, self._control = on_control, None
    self._desired_paused = self._changing_control = False

  def _check_owner(self):
    if os.getpid() != self._pid or threading.current_thread() is not self._owner:
      raise RuntimeError('Local match must stay on its creating thread')

  def _ready(self):
    self._check_owner()
    if not self._running or self._closed:
      raise RuntimeError('Local match is not running')

  def start(self):
    self._check_owner()
    if self._started or self._closed:
      raise RuntimeError('Create a new local player for a new match')
    self._started = True
    # 2026-09-10: Keep validated identity with the startup snapshot.
    # snapshot = expected = None
    # try:
    snapshot = expected = compatibility = None
    try:
      if self._resume_path is not None:
        # 2026-09-10: Restore requires explicit checkpoint compatibility metadata.
        # restored, snapshot, expected = decode_checkpoint(read_checkpoint(self._resume_path))
        restored, snapshot, expected, compatibility = decode_checkpoint(read_checkpoint(self._resume_path))
        from dataclasses import replace
        self._settings = replace(restored, listen_host='127.0.0.1', listen_port=self.port, state_hash_interval=1)
      def server_engine(settings):
        env = self._factory(settings)
        try:
          if snapshot is not None:
            # 2026-09-10: Reject incompatible saved state before set_state.
            # env.set_state(snapshot)
            require_identity(env, compatibility)
            env.set_state(snapshot)
            if engine_digest(env) != expected:
              raise RuntimeError('Saved match is incompatible with this engine')
          return env
        except BaseException:
          env.close()
          raise
      self.server = FrameSyncServer(**vars(self._settings), engine_factory=server_engine)
      self.server.start()
      self.port = self.server.listen_port
      # Restore the exact authority origin even when scenario construction uses
      # external content; seed-only reconstruction is not accepted as equality.
      origin = self.server._call(lambda: capture(self._settings, self.server._runtime.env))
      # 2026-09-10: Carry authority identity into replica initialization.
      # _, state, digest = decode_checkpoint(origin)
      _, state, digest, origin_identity = decode_checkpoint(origin)
      self.replica = self._factory(self._settings)
      # 2026-09-10: Check replica build/content identity before native restoration.
      # self.replica.set_state(state)
      require_identity(self.replica, origin_identity)
      self.replica.set_state(state)
      del state, origin
      if engine_digest(self.replica) != digest:
        raise RuntimeError('Local replica origin differs from authority')
      self.client = FrameSyncClient('127.0.0.1', self.port)
      identity, slots = self.client.connect()
      if identity != (self._settings.game_engine_random_seed, self._settings.left_agents, self._settings.right_agents) or slots != [0]:
        raise RuntimeError('Unexpected local slot assignment')
      if self._record_path is not None:
        self._recorder = self.server._call(lambda: MatchRecorder(self._settings, self.server._runtime.env,
                                                                 limits=self._replay_limits))
      if not self.client.send_ready():
        raise RuntimeError('Could not mark the local replica ready')
      self._wait(self.server.all_clients_ready)
      self._running = True
      # 2026-09-10: authoritative local pause and bounded command ownership.
      # self._ended = match_finished(self.replica)
      # return identity, slots
      self._ended = match_finished(self.replica)
      self._control = MatchControl(0, RUNNING, 0, int.from_bytes(bytes.fromhex(digest)[:8], 'little'))
      if self._on_control is not None:
        self._on_control(self._control)
        self._ready()
      return identity, slots
    except BaseException as error:
      try:
        self.stop(finalize=False)
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Local match startup cleanup also failed.')
      raise
    finally:
      # The server factory closure must not retain a whole initial snapshot.
      # 2026-09-10: Release all captured startup state after initialization.
      # snapshot = expected = None
      snapshot = expected = compatibility = None

  def _wait(self, predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while not predicate():
      if self.client is not None and self.client.is_disconnected():
        raise RuntimeError(self.client.failure_reason or 'Local transport disconnected')
      if time.monotonic() >= deadline:
        raise TimeoutError('Local match synchronization timed out')
      time.sleep(.001)

  def step(self, value=None):
    self._ready()
    if self._ended:
      raise RuntimeError('Local match has ended')
    # 2026-09-10: authoritative local pause and bounded command ownership.
    # if self._stepping:
    #   raise RuntimeError('Concurrent or reentrant local frame')
    if self._stepping or self._changing_control:
      raise RuntimeError('Concurrent or reentrant local frame')
    self._apply_pause_request()
    if self._control.phase != RUNNING:
      if self.client.is_disconnected():
        raise RuntimeError(self.client.failure_reason or 'Local transport disconnected')
      return None
    self._stepping = True
    try:
      # 2026-09-10: authoritative local pause and bounded command ownership.
      # return self._step_owned(value)
      result = self._step_owned(value)
      self._apply_pause_request()
      return result
    finally:
      self._stepping = False

  def _step_owned(self, value):
    if value is None:
      value = self._input_provider(self.frame) if self._input_provider is not None else wire.default_slot_input()
    input_bytes(value)
    try:
      if not self.client.send_frame_entries(self.frame, [(0, value)]):
        raise RuntimeError(self.client.failure_reason or 'Input admission failed')
      frame, inputs = self.server.run_one_frame(timeout_ms=500)
      self._wait(self.client.has_authoritative_frame)
      received_frame, authority = self.client.pop_authoritative_frame()
      if frame != self.frame or received_frame != frame or inputs != authority:
        raise RuntimeError('Local authoritative frame differs')
      self.replica.step_with_input(b''.join(input_bytes(item) for item in authority))
      # 2026-09-10: consume every required wire hash before advancing again.
      # Direct replica comparison alone left one retained hash per frame until
      # a long local match exhausted the client's bounded hash store.
      # digest = self.server._call(lambda: engine_digest(self.server._runtime.env))
      # if engine_digest(self.replica) != digest:
      #   raise RuntimeError('Local replica state diverged')
      digest = engine_digest(self.replica)
      received_hash = None
      def hash_arrived():
        nonlocal received_hash
        received_hash = self.client.pop_state_hash()
        return received_hash is not None
      self._wait(hash_arrived)
      expected_hash = int.from_bytes(bytes.fromhex(digest)[:8], 'little')
      if received_hash != (frame, expected_hash):
        raise RuntimeError('Local authoritative state hash differs')
      if self.server._call(lambda: engine_digest(self.server._runtime.env)) != digest:
        raise RuntimeError('Local replica state diverged')
      self._ended = match_finished(self.replica)
      if self._recorder is not None:
        self.server._call(self._recorder.record, frame, authority, self.server._runtime.env)
      self.frame += 1
      ball, _, score = positions(self.replica)
      # 2026-09-10: publish the terminal frame before run finalizes its outputs.
      # self._last = dict(frame=frame, digest=digest, ball=ball, score=score)
      # 2026-09-10: authoritative local pause and bounded command ownership.
      # self._last = dict(frame=frame, digest=digest, ball=ball, score=score, ended=self._ended)
      self._last = dict(frame=frame, digest=digest, ball=ball, score=score, ended=self._ended,
                        control_epoch=self._control.epoch, control_phase=self._control.phase)
      if self._on_frame is not None:
        self._on_frame(dict(self._last))
      return dict(self._last)
    except BaseException as error:
      try:
        self.stop(finalize=False)
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Local match frame cleanup also failed.')
      raise

  def set_paused(self, paused):
    """Request a boundary on this owner's synchronous authority/replica pair."""
    self._ready()
    if type(paused) is not bool:
      raise ValueError('Pause request must be boolean')
    if self._ended or self._changing_control:
      raise RuntimeError('Cannot change control during completion or a control callback')
    self._desired_paused = paused
    if not self._stepping:
      self._apply_pause_request()
    return self._control

  def pause(self):
    return self.set_paused(True)

  def resume(self):
    return self.set_paused(False)

  def _apply_pause_request(self):
    if self._ended or (self._control.phase == PAUSED) == self._desired_paused:
      return
    self._changing_control = True
    try:
      def boundary():
        runtime = self.server._runtime
        # 2026-09-10: use the actual authority cursor exposed by FrameInputWindow.
        # if runtime.collecting or runtime.window.frame != self.frame:
        if runtime.collecting or runtime.window.frame_id != self.frame:
          raise RuntimeError('Local pause requires a completed authority boundary')
        runtime.window.clear()
        return engine_digest(runtime.env)
      digest = self.server._call(boundary)
      if engine_digest(self.replica) != digest:
        raise RuntimeError('Local pause boundary diverged')
      state_hash = int.from_bytes(bytes.fromhex(digest)[:8], 'little')
      phases = (PAUSED,) if self._desired_paused else (RESUMING, RUNNING)
      for phase in phases:
        epoch = self._control.epoch + (phase != RUNNING)
        control = MatchControl(epoch, phase, self.frame, state_hash)
        control.validate_after(self._control)
        # 2026-09-10: bounded pause commands and input release across owner transitions.
        # self._control = control
        # if self._on_control is not None:
        self._control = control
        if callable(getattr(self._controls, 'set_suspended', None)):
          self._controls.set_suspended(phase != RUNNING)
        if self._on_control is not None:
          self._on_control(control)
          self._ready()
      ball, _, score = positions(self.replica)
      self._last = dict(frame=self.frame - 1, digest=digest, ball=ball, score=score,
          ended=self._ended, control_epoch=self._control.epoch, control_phase=self._control.phase)
      if self._on_frame is not None:
        self._on_frame(dict(self._last))
        self._ready()
    except BaseException as error:
      try:
        self.stop(finalize=False)
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Local pause cleanup also failed.')
      raise
    finally:
      self._changing_control = False

  def save(self, path=None):
    self._ready()
    target = self._save_path if path is None else path
    if target is None:
      raise ValueError('Choose a checkpoint path before saving')
    checkpoint = self.server._call(lambda: capture(self._settings, self.server._runtime.env))
    write_checkpoint(target, checkpoint)
    return dict(frames=self.frame, digest=checkpoint['digest'], path=target)

  # 2026-09-10: accept an owner-safe graphical command source.
  # def run(self, max_frames=None, *, realtime=True):
  def run(self, max_frames=None, *, realtime=True, controls=None):
    self._ready()
    if max_frames is not None and (type(max_frames) is not int or not 1 <= max_frames <= 1000000):
      raise ValueError('max_frames must be 1..1000000')
    if type(realtime) is not bool:
      raise ValueError('realtime must be bool')
    # 2026-09-10: a graphical window provides interactive exit without a TTY.
    # if max_frames is None and not sys.stdin.isatty():
    if max_frames is None and not sys.stdin.isatty() and not getattr(controls, 'is_graphical', False):
      raise ValueError('Noninteractive matches require a frame limit')
    # 2026-09-10: own a fixed deadline grid for this run.
    # completed = False
    # try:
    #   # 2026-09-10: borrow graphical controls
    completed = False
    # 2026-09-10: construction failure must enter owner cleanup too.
    # pacer = FramePacer(MATCH_HZ)
    pacer = None
    try:
      pacer = FramePacer(MATCH_HZ)
      # 2026-09-10: borrow graphical controls without acquiring terminal state.
      # with TerminalControls() as controls:
      with (TerminalControls() if controls is None else controls) as controls:
        self._controls = controls
        for_frame = 0
        # 2026-09-10: completed checkpoints remain inspectable without stepping.
        # while self._running and (max_frames is None or for_frame < max_frames):
        while self._running and not self._ended and (max_frames is None or for_frame < max_frames):
          # 2026-09-10: wait before sampling; cancellation cannot execute another frame.
          # start = time.monotonic()
          # value = controls.read()
          # if controls.quit:
          admitted = pacer.wait_next(getattr(controls, 'wait', None)) if realtime else True
          value = controls.read()
          if controls.quit or not admitted:
            break
          # 2026-09-10: authoritative local pause and bounded command ownership.
          # self.step(None if self._input_provider is not None else value)
          if getattr(controls, 'pause', False):
            self.set_paused(not self._desired_paused)
          if callable(getattr(controls, 'set_suspended', None)):
            controls.set_suspended(self._control.phase != RUNNING)
          advanced = self.step(None if self._input_provider is not None else value)
          # 2026-09-10: P without a configured output must not terminate a match.
          # if controls.save:
          #   self.save()
          if controls.save and self._save_path is not None:
            self.save()
          # 2026-09-10: authoritative local pause and bounded command ownership.
          # for_frame += 1
          if advanced is not None:
            for_frame += 1
          elif not realtime:
            time.sleep(.001)
          # 2026-09-10: do not drift or sleep after the terminal frame.
          # if realtime:
          #   time.sleep(max(0, .1 - (time.monotonic() - start)))
          # The next iteration waits on the same absolute grid.
      if self._save_path is not None:
        self.save()
      completed = True
    except KeyboardInterrupt:
      completed = True
    finally:
      self._controls = None
      # 2026-09-10: terminal/file cleanup cannot replace a primary match error.
      # self.stop(finalize=completed)
      primary = sys.exc_info()[1]
      try:
        self.stop(finalize=completed)
      except BaseException:
        if primary is None:
          raise
        if hasattr(primary, 'add_note'):
          primary.add_note('Local match cleanup also failed; the original failure is preserved.')
    # 2026-09-10: report bounded scheduling counters, independently of game frame IDs.
    # return self.stats()
    # 2026-09-10: interruption during scheduler construction admits no ticks.
    # return dict(self.stats(), pacing=pacer.stats())
    return dict(self.stats(), pacing=None if pacer is None else pacer.stats())

  def stop(self, *, finalize=True):
    self._check_owner()
    if self._closed:
      return
    self._running = False
    failures = []
    try:
      if self._recorder is not None and self.server is not None:
        try:
          if finalize:
            replay = self.server._call(self._recorder.finish, self.server._runtime.env)
            replay.save(self._record_path)
          else:
            self.server._call(self._recorder.close)
        except BaseException as error:
          failures.append(error)
      for owner in (self.client, self.server, self.replica):
        if owner is not None:
          try:
            owner.close()
          except BaseException as error:
            failures.append(error)
    finally:
      if self._recorder is not None:
        self._recorder.manager.close()
      self.server = self.client = self.replica = self._recorder = None
      self._closed = True
    if failures:
      raise failures[0]

  def stats(self):
    self._check_owner()
    # 2026-09-10: lifecycle completion is separate from explicit resource close.
    # return dict(running=self._running, closed=self._closed, frames=self.frame,
    return dict(running=self._running, closed=self._closed, frames=self.frame, ended=self._ended,
                # 2026-09-10: authoritative local pause and bounded command ownership.
                # last=None if self._last is None else dict(self._last), port=self.port)
                last=None if self._last is None else dict(self._last), port=self.port,
                # 2026-09-10: bounded pause commands and input release across owner transitions.
                # control=self._control, desired_paused=self._desired_paused)
                control=None if self._control is None else dict(epoch=self._control.epoch,
                    phase=self._control.phase, next_frame=self._control.next_frame, state_hash=self._control.state_hash),
                desired_paused=self._desired_paused)

  close = stop

  def __enter__(self):
    self.start()
    return self

  def __exit__(self, kind, error, traceback):
    try:
      self.stop(finalize=kind is None)
    except BaseException:
      if error is None:
        raise
      if hasattr(error, 'add_note'):
        error.add_note('Local match cleanup also failed.')


def main(argv=None):
  import argparse
  from gfootball.frame_sync.match_archive import playback
  parser = argparse.ArgumentParser(description='Local football with verified save and replay')
  parser.add_argument('--scenario', default='academy_empty_goal')
  parser.add_argument('--port', type=int, default=0)
  parser.add_argument('--left', type=int, default=1, help='Controlled slots on the left team')
  parser.add_argument('--right', type=int, default=0, help='Controlled slots on the right team; other players use engine AI')
  parser.add_argument('--seed', type=int, default=42)
  parser.add_argument('--frames', type=int)
  parser.add_argument('--controlled', default='0', choices=['0'])
  parser.add_argument('--record', help='Write a complete match replay when play finishes')
  parser.add_argument('--save', help='Checkpoint path for P and normal match completion')
  parser.add_argument('--resume', help='Load a saved local match; its scenario and teams take precedence')
  parser.add_argument('--replay', help='Replay and verify a saved match file')
  parser.add_argument('--fast', action='store_true', help='Run a bounded match without wall-clock pacing')
  args = parser.parse_args(argv)
  if args.replay:
    print(playback(args.replay))
    return
  if args.frames is not None and not 1 <= args.frames <= 1000000:
    parser.error('--frames must be 1..1000000')
  if args.frames is None and not sys.stdin.isatty():
    parser.error('Noninteractive play requires --frames')
  player = LocalPlayer(args.scenario, args.port, args.left, args.right, args.seed,
      record_path=args.record, save_path=args.save, resume_path=args.resume,
      on_frame=lambda state: print('Frame {frame}  score={score}  ball={ball}'.format(**state)))
  try:
    player.start()
    print('WASD: set direction | 0: stop | Z/X/C: pass | V: shoot | Space: pressure | P: save | Q: exit')
    player.run(args.frames, realtime=not args.fast)
  finally:
    player.stop(finalize=False)
