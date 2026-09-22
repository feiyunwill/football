# Copyright 2026 Google LLC
# 2026-09-09: consume one coherent publication and restore only changed payloads.
# 2026-09-10: native pose hooks can interpolate separately from opaque physics snapshots.
# """One render owner consumes immutable samples without retaining state history.
# The display environment is borrowed and must be distinct from the logic engine.
# The owner creates/closes it on the appropriate rendering thread. The loop never
# steps logic or claims to interpolate opaque snapshots; render() still runs each
# display tick even when no new logical state has been published.
# """
"""Borrow coherent snapshots and optionally interpolate native display poses.

The separate rendering owner creates/closes the display engine. No logic steps
or serialized-byte interpolation occur here. The holder owns bounded history;
this loop retains scalar timing/revision metadata, never serialized snapshots.
"""
from gfootball.frame_sync.frame_pacing import FramePacer
import collections
import math
import threading
import time

from gfootball.frame_sync.presentation_state import PresentationState


class PresentationLoop:
  # 2026-09-10: opt into explicit native pose interpolation; ordinary consumers retain their API.
  # def __init__(self, display_env, state_holder, rate_hz=60, *, clock=None, jitter_samples=100):
  def __init__(self, display_env, state_holder, rate_hz=60, *, clock=None, jitter_samples=100,
               interpolate=False, logic_hz=10):
    if type(rate_hz) not in (int, float) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
      raise ValueError('Invalid presentation rate')
    if type(jitter_samples) is not int or not 1 <= jitter_samples <= 1024:
      raise ValueError('Invalid jitter sample count')
    for name in ('set_state', 'render'):
      if not callable(getattr(display_env, name, None)):
        raise ValueError('Display environment must implement ' + name)
    if not callable(getattr(state_holder, 'read_sample', None)):
      raise ValueError('State holder must provide atomic read_sample')
    if clock is not None and not callable(clock):
      raise ValueError('Clock must be callable')
    if type(interpolate) is not bool:
      raise ValueError('Expected an interpolation flag')
    if type(logic_hz) not in (int, float) or not math.isfinite(logic_hz) or not 1 <= logic_hz <= 240:
      raise ValueError('Invalid interpolation logic rate')
    if interpolate:
      if not callable(getattr(state_holder, 'read_pair', None)):
        raise ValueError('Interpolation requires atomic read_pair')
      for name in ('save_render_state', 'render_interpolated'):
        if not callable(getattr(display_env, name, None)):
          raise ValueError('Display interpolation requires ' + name)
    self._interpolate, self._logic_hz = interpolate, float(logic_hz)
    self._blend_start = None
    self._correction_active = False
    self._presented_frame = None
    self._interpolated_renders = self._correction_blends = 0
    self._display_env, self._state_holder, self._rate_hz = display_env, state_holder, float(rate_hz)
    self._clock = clock or time.monotonic
    self._last_state_revision = None
    self._last_sample_revision = None
    self._render_count = 0
    self._restore_count = 0
    self._jitter_samples = collections.deque(maxlen=jitter_samples)
    self._last_render_time = None
    self._failure = None
    self._stats_lock = threading.Lock()
    self._frame_lock = threading.Lock()
    self._loop_lock = threading.Lock()
    self._stop_event = threading.Event()
    self._running = False

  def _now(self):
    now = self._clock()
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
      raise ValueError('Invalid monotonic presentation time')
    if self._last_render_time is not None and now < self._last_render_time:
      raise ValueError('Presentation clock moved backwards')
    return float(now)

  # 2026-09-10: finalization can settle the last pose without an extra logic step.
  # def run_one_frame(self):
  def run_one_frame(self, *, settle=False):
    if type(settle) is not bool:
      raise ValueError('Expected a settle flag')
    if not self._frame_lock.acquire(blocking=False):
      raise RuntimeError('Concurrent or reentrant presentation frame')
    stage = 'read_failed'
    try:
      if self._stop_event.is_set():
        return False
      # 2026-09-10: the pair must be from one publication transaction.
      # sample = self._state_holder.read_sample()
      previous = None
      if self._interpolate:
        pair = self._state_holder.read_pair()
        if type(pair) is not tuple or len(pair) != 2:
          raise ValueError('Expected two coherent presentation endpoints')
        previous, sample = pair
        if previous is not None and not isinstance(previous, PresentationState):
          raise ValueError('Expected immutable previous PresentationState')
      else:
        sample = self._state_holder.read_sample()
      if sample is None:
        self._last_state_revision = None
        self._last_sample_revision = None
        self._blend_start = self._presented_frame = None
        self._correction_active = False
        with self._stats_lock:
          self._last_render_time = None
        return False
      if not isinstance(sample, PresentationState):
        raise ValueError('Expected immutable PresentationState')
      stage = 'clock_failed'
      now = self._now()
      # 2026-09-10: preserve regular rendering while opting graphical matches into native poses.
      # if sample.state_revision != self._last_state_revision:
      #   stage = 'restore_failed'
      #   self._display_env.set_state(sample.state)
      #   self._last_state_revision = sample.state_revision
      #   with self._stats_lock:
      #     self._restore_count += 1
      # self._last_sample_revision = sample.revision
      # if self._stop_event.is_set():
      #   return False
      # stage = 'render_failed'
      # self._display_env.render()
      if self._interpolate:
        stage = 'interpolation_failed'
        if not self._render_pair(previous, sample, now, settle):
          return False
      else:
        if sample.state_revision != self._last_state_revision:
          stage = 'restore_failed'
          self._restore(sample)
        if self._stop_event.is_set():
          return False
        stage = 'render_failed'
        self._display_env.render()
      self._last_sample_revision = sample.revision
      with self._stats_lock:
        if self._last_render_time is not None:
          self._jitter_samples.append(abs(now - self._last_render_time - 1.0 / self._rate_hz))
        self._last_render_time = now
        self._render_count += 1
      return True
    except Exception:
      # Retain only a bounded reason, never an exception/traceback and its state.
      with self._stats_lock:
        self._failure = stage
      self._running = False
      self._stop_event.set()
      self._last_state_revision = None
      self._last_sample_revision = None
      raise
    finally:
      self._frame_lock.release()

  def _restore(self, sample):
    self._display_env.set_state(sample.state)
    self._last_state_revision = sample.state_revision
    with self._stats_lock:
      self._restore_count += 1

  def _render_pair(self, previous, sample, now, settle):
    if sample.timestamp > now:
      raise ValueError('Presentation sample is ahead of the render clock')
    changed = (sample.state_revision != self._last_state_revision or sample.frame_id != self._presented_frame
               or (sample.discontinuity and sample.revision != self._last_sample_revision))
    if changed:
      have_display = self._last_state_revision is not None
      consecutive = (previous is not None and previous.frame_id + 1 == sample.frame_id
          and previous.timestamp <= sample.timestamp and not sample.discontinuity
          # 2026-09-10: do not jump to a logical endpoint during an unfinished correction.
          # and (self._presented_frame is None or sample.frame_id > self._presented_frame))
          and (self._presented_frame is None or sample.frame_id > self._presented_frame)
          and not (self._correction_active and self._blend_start is not None
                   and now - self._blend_start < 1 / self._logic_hz))
      if consecutive:
        if self._last_state_revision != previous.state_revision:
          self._restore(previous)
        self._display_env.save_render_state(from_display=False)
        self._blend_start = sample.timestamp
        self._correction_active = False
      elif have_display:
        # A correction has no valid old simulation endpoint. Preserve the last
        # visible pose, then ease toward corrected physics without writing it back.
        self._display_env.save_render_state(from_display=True)
        self._blend_start = now
        self._correction_active = True
        with self._stats_lock:
          self._correction_blends += 1
      else:
        self._blend_start = None
        self._correction_active = False
      if self._last_state_revision != sample.state_revision:
        self._restore(sample)
      self._presented_frame = sample.frame_id
    if self._stop_event.is_set():
      return False
    if self._blend_start is None:
      self._display_env.render()
    else:
      alpha = 1.0 if settle else min(1.0, max(0.0, (now - self._blend_start) * self._logic_hz))
      self._display_env.render_interpolated(alpha)
      with self._stats_lock:
        self._interpolated_renders += 1
      if alpha == 1.0:
        self._blend_start = None  # settled poses cannot rewind on the next draw
        self._correction_active = False
    return True

  def get_jitter_stats(self):
    """Mean/max/nearest-rank p95 of render-start spacing error, in milliseconds."""
    with self._stats_lock:
      samples = list(self._jitter_samples)
    if not samples:
      return 0.0, 0.0, 0.0
    samples.sort()
    p95 = samples[math.ceil(0.95 * len(samples)) - 1]
    return sum(samples) / len(samples) * 1000, samples[-1] * 1000, p95 * 1000

  @property
  def render_count(self):
    with self._stats_lock:
      return self._render_count

  @property
  def failure_reason(self):
    with self._stats_lock:
      return self._failure

  def stats(self):
    with self._stats_lock:
      return dict(render_count=self._render_count, restore_count=self._restore_count,
                  jitter_samples=len(self._jitter_samples), failure=self._failure,
                  # 2026-09-10: expose actual pose renders separately from refresh count.
                  # stopped=self._stop_event.is_set())
                  stopped=self._stop_event.is_set(), interpolation=self._interpolate,
                  interpolated_renders=self._interpolated_renders, correction_blends=self._correction_blends)

  def run_loop(self):
    if not self._loop_lock.acquire(blocking=False):
      raise RuntimeError('Presentation loop is already running')
    if self._frame_lock.locked():
      self._loop_lock.release()
      raise RuntimeError('Cannot start presentation loop during an active frame')
    self._running = True
    # 2026-09-10: reuse fixed deadlines and interrupt waits on stop.
    # period = 1.0 / self._rate_hz
    # try:
    #   while not self._stop_event.is_set():
    #     start = time.monotonic()
    #     self.run_one_frame()
    #     self._stop_event.wait(max(0.0, period - (time.monotonic() - start)))
    # 2026-09-10: scheduler allocation failure also releases the loop guard.
    # pacer = FramePacer(self._rate_hz)
    try:
      pacer = FramePacer(self._rate_hz)
      while not self._stop_event.is_set() and pacer.wait_next(self._stop_event.wait):
        self.run_one_frame()
    finally:
      self._running = False
      self._loop_lock.release()

  def stop(self):
    self._running = False
    self._stop_event.set()
