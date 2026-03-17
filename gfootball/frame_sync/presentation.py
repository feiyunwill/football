# Copyright 2019 Google LLC
# Presentation layer (task 4.1/4.2/4.3): decoupled from logic, optional interpolation,
# rollback-aware state updates. On rollback (4.3), logic writes the corrected state
# to the holder; presentation picks it up on next run_one_frame() (instant alignment).

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import threading
import time


class LogicStateHolder(object):
  """Shared state written by logic layer, read by presentation. Holds latest
  get_state() string, frame ids and timestamp for interpolation (4.1/4.2).
  """

  def __init__(self):
    self._lock = threading.Lock()
    self._state_str = None
    self._frame_id = -1
    self._confirmed_frame_id = -1
    self._state_time = None
    self._waiting_for_authority = False

  def write(self, state_str, frame_id, confirmed_frame_id=None, waiting_for_authority=False):
    with self._lock:
      self._state_str = state_str
      self._frame_id = frame_id
      if confirmed_frame_id is not None:
        self._confirmed_frame_id = confirmed_frame_id
      self._state_time = time.time()
      self._waiting_for_authority = waiting_for_authority

  def read(self):
    with self._lock:
      return (
          self._state_str,
          self._frame_id,
          self._confirmed_frame_id,
          self._state_time,
          self._waiting_for_authority,
      )


class PresentationLoop(object):
  """Runs at fixed fps (e.g. 60), reads LogicStateHolder, syncs display env and
  calls render(). Logic and presentation are decoupled (4.1).
  Interpolation (4.2): engine has no API to set only positions; we keep
  prev/curr state in holder and use latest state for render. Full linear
  interpolation would require engine set_display_state(interpolated_info) or
  parsing state pickle.
  """

  def __init__(self, display_env, state_holder, rate_hz=60):
    self._display_env = display_env
    self._state_holder = state_holder
    self._rate_hz = rate_hz
    self._running = False
    self._prev_state_str = None
    self._curr_state_str = None

  def run_one_frame(self):
    state_str, frame_id, _confirmed, state_time, waiting_for_authority = self._state_holder.read()
    if state_str is not None:
      self._prev_state_str = self._curr_state_str
      self._curr_state_str = state_str
      self._display_env.set_state(state_str)
      self._display_env.render()
      # 4.3: When waiting_for_authority, state is already corrected; instant alignment done above.
      # Full interpolation (4.2) would use state_time and prev/curr to blend; engine has no partial set_state.

  def run_loop(self):
    period = 1.0 / self._rate_hz
    self._running = True
    while self._running:
      t0 = time.time()
      self.run_one_frame()
      elapsed = time.time() - t0
      if elapsed < period:
        time.sleep(period - elapsed)

  def stop(self):
    self._running = False
