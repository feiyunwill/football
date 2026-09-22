"""Bounded scheduling of fixed-size simulation or presentation ticks.

Missed wall-clock opportunities are discarded, never simulated as a large dt
or replayed in an unbounded burst. This scheduler does not advance game frames.
"""
import asyncio
import math
import os
import threading
import time

# 2026-09-10: one contract supplies the match scheduler and wire cadence.
# MATCH_HZ = 10
# 2026-09-13: separate generic pacer default from negotiated match frequency.
# from gfootball.frame_sync.match_cadence import MATCH_CADENCE
from gfootball.frame_sync.match_cadence import MATCH_CADENCE, LEGACY_HZ

MATCH_HZ = MATCH_CADENCE.network_hz
MAX_CLOCK_NS = (1 << 63) - 1


class FramePacer:
  """Owner-bound absolute deadlines with one outstanding tick and no history.

  The first tick is immediate. Waiters return True to cancel; a cancelled wait
  does not admit a tick. Sync/async paths use the same deadline calculation.
  A zero-length wait gives cancellation and async I/O an opportunity even when
  work overruns. A rate's interval is rounded once to the nearest nanosecond.
  """
  # 2026-09-13: generic callers retain 10 Hz; match loops pass MATCH_HZ explicitly.
  # def __init__(self, rate_hz=MATCH_HZ, *, clock_ns=None):
  def __init__(self, rate_hz=LEGACY_HZ, *, clock_ns=None):
    if type(rate_hz) not in (int, float) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
      raise ValueError('Pacing rate must be within 1..240 Hz')
    if clock_ns is not None and not callable(clock_ns):
      raise ValueError('Expected a monotonic nanosecond clock')
    self._clock = time.monotonic_ns if clock_ns is None else clock_ns
    self._period = round(1_000_000_000 / rate_hz)
    self._owner, self._pid = threading.current_thread(), os.getpid()
    self._deadline = self._last_now = None
    self._active = False
    self._ticks = self._missed = self._late = self._max_late = 0

  def _check(self):
    if threading.current_thread() is not self._owner or os.getpid() != self._pid:
      raise RuntimeError('Pacer belongs to its creating thread and process')

  def _now(self):
    value = self._clock()
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_NS:
      raise ValueError('Invalid monotonic nanosecond clock')
    if self._last_now is not None and value < self._last_now:
      raise ValueError('Pacing clock moved backwards')
    self._last_now = value
    return value

  def _delays(self):
    self._check()
    if self._active:
      raise RuntimeError('Concurrent or reentrant pacing wait')
    self._active = True
    try:
      now = self._now()
      target = now if self._deadline is None else self._deadline
      yield 0.0  # Check cancellation / yield the event loop before admission.
      now = self._now()
      while now < target:
        before = now
        yield (target - now) / 1_000_000_000
        now = self._now()
        if now == before:
          raise RuntimeError('Pacing waiter returned without advancing time')
      late = now - target
      missed = late // self._period
      deadline = target + (missed + 1) * self._period
      if deadline > MAX_CLOCK_NS or self._ticks == MAX_CLOCK_NS or self._missed + missed > MAX_CLOCK_NS:
        raise OverflowError('Pacing lifetime exhausted')
      self._deadline = deadline
      self._ticks += 1
      self._missed += missed
      self._late, self._max_late = late, max(self._max_late, late)
    finally:
      self._active = False

  def wait_next(self, waiter=None):
    wait = time.sleep if waiter is None else waiter
    if not callable(wait):
      raise ValueError('Expected a pacing waiter')
    delays = self._delays()
    try:
      for seconds in delays:
        if wait(seconds) is True:
          return False
      return True
    finally:
      delays.close()

  async def wait_next_async(self, waiter=None):
    wait = asyncio.sleep if waiter is None else waiter
    if not callable(wait):
      raise ValueError('Expected an async pacing waiter')
    delays = self._delays()
    try:
      for seconds in delays:
        if await wait(seconds) is True:
          return False
      return True
    finally:
      delays.close()

  def stats(self):
    self._check()
    return dict(ticks=self._ticks, missed_deadlines=self._missed, period_ns=self._period,
                last_lateness_ns=self._late, max_lateness_ns=self._max_late)
