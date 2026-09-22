"""Main-thread SDL presentation with one owned match worker and bounded handoff.

Factories are explicit embedding/test seams. Defaults use actual GameEnv;
missing native bindings or an interactive SDL window are errors, never fallbacks.
"""
from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
import queue
# 2026-09-10: no terminal state or process-global controls are used here.
# import sys
import threading
# 2026-09-10: all frame scheduling now uses FramePacer.
# import time

from gfootball.frame_sync.graphical_input import BufferedControls, InputBuffer
from gfootball.frame_sync.local_runtime import LocalPlayer
from gfootball.frame_sync.match_archive import engine_digest, playback
from gfootball.frame_sync.match_identity import engine_identity, native_match_display, require_identity
from gfootball.frame_sync.multiplayer_runtime import HostedMatch, NetworkPlayer, _frame_limit
from gfootball.frame_sync.presentation_loop import PresentationLoop
from gfootball.frame_sync.presentation_state import LogicStateHolder
# 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
# from gfootball.frame_sync.match_control import RUNNING
from gfootball.frame_sync.match_control import RUNNING, PAUSED, RESUMING
from gfootball.frame_sync.match_lifecycle import match_finished


class _ReplayStopped(Exception):
  """Window cancellation before the terminal replay digest; never verified."""


def run_graphical(mode='local', *, max_frames=None, options=None, engine_factory=None,
                  display_factory=None, on_ready=None):
  """Run local/resume, Host, Join or replay with a separate display snapshot.

  on_ready receives plain match settings/port on the UI thread. The worker owns
  all simulation objects, sockets and archive operations until cleanup finishes.
  """
  if threading.current_thread() is not threading.main_thread():
    raise RuntimeError('Graphical matches require the main thread')
  if mode not in ('local', 'host', 'join', 'replay'):
    raise ValueError('Unknown graphical match mode')
  _frame_limit(max_frames, interactive=True)
  if options is not None and type(options) is not dict:
    raise ValueError('Expected match options')
  for hook in (engine_factory, display_factory, on_ready):
    if hook is not None and not callable(hook):
      raise ValueError('Expected a graphical match hook')
  arguments = dict(options or {})
  # 2026-09-10: only the coordinator owns graphical control/input transitions.
  # if any(key in arguments for key in ('engine_factory', 'input_provider', 'on_frame')):
  if any(key in arguments for key in ('engine_factory', 'input_provider', 'on_frame', 'on_control')):
    raise ValueError('Match hooks belong to the coordinator')
  if mode == 'replay' and (set(arguments) != {'path'} or max_frames is not None):
    raise ValueError('Graphical replay requires one path and no frame limit')
  inputs, holder = InputBuffer(), LogicStateHolder()
  metadata = queue.Queue(maxsize=1)
  ready, done, abort = threading.Event(), threading.Event(), threading.Event()
  # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
  # outcome = {}  # one result or exception, never a frame/event history
  outcome = {}  # one result or exception, never a frame/event history
  status_lock = threading.Lock()
  status = dict(phase=RUNNING, seen=False, waiting=mode in ('host', 'join'), ended=False)

  def control_changed(control):
    with status_lock:
      reset = status['seen'] and status['phase'] == RUNNING and control.phase == RUNNING
      inputs.set_suspended(control.phase != RUNNING, reset=reset)
      status.update(phase=control.phase, seen=True)

  def status_text():
    with status_lock:
      phase, waiting, ended = status['phase'], status['waiting'], status['ended']
      release = inputs.release_required
    if mode == 'replay':
      return 'Replay - Esc: quit'
    if ended:
      return 'Match finished'
    # 2026-09-10: show save controls only when an output is configured.
    # if phase == PAUSED:
    #   return ('Paused - K / Guide: resume - P / Start: save - Esc / Back: quit'
    #           if mode != 'join' else 'Paused by host - Esc / Back: quit')
    save_hint = ' - P / Start: save' if arguments.get('save_path') else ''
    if phase == PAUSED:
      return ('Paused - K / Guide: resume' + save_hint + ' - Esc / Back: quit'
              if mode != 'join' else 'Paused by host - Esc / Back: quit')
    if phase == RESUMING:
      return 'Resuming - waiting for players'
    if waiting:
      return 'Waiting for players - Esc / Back: quit'
    if release:
      return 'Release movement and action controls to continue'
    # 2026-09-10: unavailable save actions must not be advertised.
    # return ('K / Guide: pause - P / Start: save - Esc / Back: quit'
    #         if mode != 'join' else 'Host controls pause - Esc / Back: quit')
    return ('K / Guide: pause' + save_hint + ' - Esc / Back: quit'
            if mode != 'join' else 'Host controls pause - Esc / Back: quit')

  class Controls(BufferedControls):
    def read(self):
      if abort.is_set():
        raise RuntimeError('Graphical presentation failed')
      return super().read()

    def wait(self, seconds):
      if abort.is_set():
        raise RuntimeError('Graphical presentation failed')
      stopped = super().wait(seconds)
      if abort.is_set():
        raise RuntimeError('Graphical presentation failed')
      return stopped

  # 2026-09-10: frozen control metadata accompanies the immutable display state.
  # def publish(env, frame, confirmed=None, discontinuity=False):
  #   holder.write(env.get_state(''), frame, frame if confirmed is None else confirmed,
  #                discontinuity=discontinuity)
  def publish(env, frame, confirmed=None, discontinuity=False, waiting=False):
    holder.write(env.get_state(''), frame, frame if confirmed is None else confirmed,
                 discontinuity=discontinuity, waiting_for_authority=waiting)

  def initialize(settings, env, port=None):
    # 2026-09-10: already finished checkpoints may produce no frame callback.
    with status_lock:
      status['ended'] = match_finished(env)
    publish(env, -1)
    metadata.put_nowait((settings, engine_identity(env), engine_digest(env), port))
    while not ready.wait(.05):
      # 2026-09-10: startup cancellation must not consume a pending save command.
      # if abort.is_set() or inputs.commands()[0]:
      # 2026-09-21: a user close between input feed and ready publication must
      # reach the match owner so it finalizes the zero-frame replay normally.
      # if abort.is_set() or inputs.quit_requested:
      #   raise _ReplayStopped() if mode == 'replay' else RuntimeError('Graphical startup cancelled')
      if abort.is_set():
        raise RuntimeError('Graphical presentation failed')
      if inputs.quit_requested:
        if mode == 'replay':
          raise _ReplayStopped()
        break
    if abort.is_set():
      raise RuntimeError('Graphical presentation failed')

  def worker():
    match = None
    previous_rollbacks = 0
    replay_frames = 0
    try:
      if mode == 'replay':
        replay_pacer = FramePacer(MATCH_HZ)
        replay_controls = Controls(inputs)
        def replay_start(settings, env):
          initialize(settings, env)
          if not replay_pacer.wait_next(replay_controls.wait):
            raise _ReplayStopped()
        def replay_frame(frame, env):
          nonlocal replay_frames
          if abort.is_set():
            raise RuntimeError('Graphical presentation failed')
          # 2026-09-10: inspect quit without draining unrelated commands.
          # if inputs.commands()[0]:
          if inputs.quit_requested:
            raise _ReplayStopped()
          publish(env, frame)
          replay_frames = frame + 1
          # 2026-09-10: include engine/render handoff time in the 10 Hz grid.
          # for _ in range(10):
          #   if abort.wait(.01) or inputs.quit_requested:
          #     raise _ReplayStopped()
          if not replay_pacer.wait_next(replay_controls.wait):
            raise _ReplayStopped()
        outcome['result'] = playback(arguments['path'], engine_factory=engine_factory,
            # 2026-09-10: anchor replay time only after display startup.
            # on_start=initialize, on_frame=replay_frame)
            on_start=replay_start, on_frame=replay_frame)
      else:
        def frame_changed(state):
          nonlocal previous_rollbacks
          if abort.is_set():
            raise RuntimeError('Graphical presentation failed')
          env = match.replica if mode == 'local' else (match.player.env if mode == 'host' else match.env)
          rollbacks = state.get('rollbacks', 0)
          publish(env, state['frame'], state.get('confirmed', state['frame']),
                  # 2026-09-10: pause feedback does not require a new game frame.
                  # discontinuity=rollbacks != previous_rollbacks)
                  discontinuity=rollbacks != previous_rollbacks,
                  waiting=state.get('control_phase', RUNNING) != RUNNING)
          # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
          # previous_rollbacks = rollbacks
          #         kind =
          previous_rollbacks = rollbacks
          with status_lock:
            status['waiting'] = mode in ('host', 'join') and state.get('confirmed', -1) < 0
            status['ended'] = state.get('ended', False)
        kind = {'local': LocalPlayer, 'host': HostedMatch, 'join': NetworkPlayer}[mode]
        # 2026-09-10: match v6 notifies input before ACK; local control comes next.
        # match = kind(**arguments, engine_factory=engine_factory,
        #              input_provider=inputs.sample, on_frame=frame_changed)
        # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
        # control_options = {} if mode == 'local' else dict(
        #     on_control=lambda control: inputs.set_suspended(control.phase != RUNNING))
        control_options = dict(on_control=control_changed)
        match = kind(**arguments, engine_factory=engine_factory,
                     input_provider=inputs.sample, on_frame=frame_changed, **control_options)
        match.start()
        if mode == 'local':
          settings, env, port = match._settings, match.replica, match.port
        elif mode == 'host':
          settings, env, port = match.player.settings, match.player.env, match.port
        else:
          settings, env, port = match.settings, match.env, None
        initialize(settings, env, port)
        outcome['result'] = match.run(max_frames, controls=Controls(inputs))
    except _ReplayStopped:
      outcome['result'] = dict(frames=replay_frames, verified=False, cancelled=True)
    except BaseException as error:
      outcome['error'] = error
    finally:
      try:
        if match is not None:
          if mode == 'local':
            match.stop(finalize=False)
          elif mode == 'host':
            match.close(finalize=False)
          else:
            match.close()
      except BaseException as error:
        if 'error' not in outcome:
          outcome['error'] = error
        elif hasattr(outcome['error'], 'add_note'):
          outcome['error'].add_note('Graphical match cleanup also failed.')
      finally:
        done.set()

  thread = threading.Thread(target=worker, name='football-graphical-logic')
  # 2026-09-10: the UI owns its independent scheduling counters.
  # display = presentation = None
  # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
  # display = presentation = ui_pacer = None
  display = presentation = ui_pacer = None
  displayed_status = None

  def refresh_status():
    nonlocal displayed_status
    text = status_text()
    if text != displayed_status:
      display.set_match_status(text)
      displayed_status = text
  failure = None
  display_stats = None
  started = False
  try:
    thread.start()
    started = True
    while not done.is_set():
      if display is None:
        try:
          settings, identity, digest, port = metadata.get_nowait()
        except queue.Empty:
          done.wait(1 / 60)
          continue
        display = (display_factory or native_match_display)(settings, identity)
        require_identity(display, identity)
        # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
        # if not callable(getattr(display, 'poll_input', None)):
        #   raise RuntimeError('Display engine must support SDL input polling')
        if any(not callable(getattr(display, name, None)) for name in ('poll_input', 'set_match_status')):
          raise RuntimeError('Display engine must support SDL input and match status')
        ui_pacer = FramePacer(60)
        # 2026-09-10: require actual display-pose support for graphical matches.
        # presentation = PresentationLoop(display, holder)
        # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
        # presentation = PresentationLoop(display, holder, interpolate=True, logic_hz=MATCH_HZ)
        # presentation.run_one_frame()
        presentation = PresentationLoop(display, holder, interpolate=True, logic_hz=MATCH_HZ)
        refresh_status()
        presentation.run_one_frame()
        if engine_digest(display) != digest:
          raise RuntimeError('Display origin diverged after rendering')
        inputs.feed(**display.poll_input())
        if on_ready is not None:
          on_ready(dict(settings=settings, port=port))
        # Process closes/actions received during startup before releasing logic.
        inputs.feed(**display.poll_input())
        ready.set()
      # 2026-09-10: drop missed refresh opportunities, never burst old draws.
      # start = time.monotonic()
      if not ui_pacer.wait_next(done.wait):
        break
      # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
      # inputs.feed(**display.poll_input())
      # presentation.run_one_frame()
      inputs.feed(**display.poll_input())
      refresh_status()
      presentation.run_one_frame()
      # 2026-09-10: waiting happens before sampling on the next absolute deadline.
      # done.wait(max(0., 1 / 60 - (time.monotonic() - start)))
    if presentation is not None and 'error' not in outcome:
      # 2026-09-10: final draw reaches the exact reconciled endpoint immediately.
      # presentation.run_one_frame()  # publish the terminal/reconciled snapshot
      # 2026-09-10: input suspension follows actual owner notifications, including staged barriers.
      # presentation.run_one_frame(settle=True)
      refresh_status()
      presentation.run_one_frame(settle=True)
  except KeyboardInterrupt:
    inputs.request_quit()
    ready.set()
  except BaseException as error:
    failure = error
    abort.set()
  finally:
    inputs.request_quit()
    ready.set()
    # Only the worker can close its engines. Never abandon a live owner or close
    # its sockets from the UI thread. Existing transport operations are bounded.
    if started:
      while thread.is_alive():
        thread.join(.05)
    if presentation is not None:
      presentation.stop()
      # 2026-09-10: retain counters only; no timing or frame history.
      # display_stats = presentation.stats()
      display_stats = dict(presentation.stats(), pacing=ui_pacer.stats())
    if display is not None:
      try:
        display.close()
      except BaseException as error:
        if failure is None and 'error' not in outcome:
          failure = error
        else:
          primary = failure if failure is not None else outcome['error']
          if hasattr(primary, 'add_note'):
            primary.add_note('Graphical display cleanup also failed.')
    inputs.close()
    holder.close()
  worker_error = outcome.pop('error', None)
  if failure is not None:
    raise failure
  if worker_error is not None:
    raise worker_error
  return dict(match=outcome.get('result'), presentation=display_stats)
