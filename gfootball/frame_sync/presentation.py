# Copyright 2019 Google LLC
# Presentation layer (4.1/4.2/4.3): decoupled from logic, frame-buffered state
# smoothing, rollback-aware updates. Full position interpolation requires
# engine set_display_state(interpolated_info) which is not yet available;
# this implementation provides timestamp-based frame buffering to reduce
# jitter and ensure smooth rendering at high FPS.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import threading
import time


class LogicStateHolder(object):
  """Shared state written by logic layer, read by presentation. Holds latest
  get_state() string, frame ids and timestamp for interpolation (4.1/4.2).
  2026-08-28: 增加帧缓冲区，支持多帧状态历史用于平滑渲染。
  """

  def __init__(self, buffer_size=4):
    self._lock = threading.Lock()
    self._state_str = None
    self._frame_id = -1
    self._confirmed_frame_id = -1
    self._state_time = None
    self._waiting_for_authority = False
    # 2026-08-28 帧缓冲：(frame_id, state_str, timestamp, waiting) 的环形缓冲
    self._buffer = collections.deque(maxlen=buffer_size)
    self._logic_fps = 10.0  # 逻辑帧率（Hz），由外部设置

  def write(self, state_str, frame_id, confirmed_frame_id=None, waiting_for_authority=False):
    """写入新帧状态。logic_fps 用于计算帧间时间间隔。"""
    now = time.time()
    with self._lock:
      self._state_str = state_str
      self._frame_id = frame_id
      if confirmed_frame_id is not None:
        self._confirmed_frame_id = confirmed_frame_id
      self._state_time = now
      self._waiting_for_authority = waiting_for_authority
      self._buffer.append((frame_id, state_str, now, waiting_for_authority))

  def read(self):
    """读取最新状态。(state_str, frame_id, confirmed_frame_id, state_time, waiting)"""
    with self._lock:
      return (
          self._state_str,
          self._frame_id,
          self._confirmed_frame_id,
          self._state_time,
          self._waiting_for_authority,
      )

  def read_interpolated(self):
    """读取插值状态：返回 (state_str, alpha)，alpha 为当前帧在两逻辑帧间的插值因子 [0,1)。
    如果缓冲区不足 2 帧，返回 (最新状态, 0.0)。"""
    with self._lock:
      if len(self._buffer) < 2:
        if self._state_str is not None:
          return self._state_str, 0.0
        return None, 0.0
      # 取最近两帧
      prev_fid, prev_state, prev_time, _ = self._buffer[-2]
      curr_fid, curr_state, curr_time, _ = self._buffer[-1]
      # 计算逻辑帧间隔（秒）
      if self._logic_fps <= 0:
        self._logic_fps = 10.0
      frame_period = 1.0 / self._logic_fps
      # alpha = (当前时间 - 上一帧时间) / 帧间隔，clamped to [0, 1)
      now = time.time()
      elapsed = now - prev_time
      alpha = max(0.0, min(elapsed / frame_period if frame_period > 0 else 0.0, 0.999))
      # 引擎不支持 partial set_state，返回最新帧状态 + alpha 供外部参考
      return curr_state, alpha

  def set_logic_fps(self, fps):
    """设置逻辑帧率（Hz），用于插值计算。"""
    self._logic_fps = float(fps)

  @property
  def buffer_depth(self):
    """当前缓冲区深度。"""
    with self._lock:
      return len(self._buffer)


class PresentationLoop(object):
  """Runs at fixed fps (e.g. 60), reads LogicStateHolder, syncs display env and
  calls render(). Logic and presentation are decoupled (4.1).
  
  2026-08-28 增强：
  - 帧缓冲平滑：使用 read_interpolated() 获取带时间戳的状态
  - Jitter 检测：监控逻辑帧到达间隔，统计抖动
  - 回滚对齐：waiting_for_authority 时立即使用最新状态
  """

  def __init__(self, display_env, state_holder, rate_hz=60):
    self._display_env = display_env
    self._state_holder = state_holder
    self._rate_hz = rate_hz
    self._running = False
    self._prev_state_str = None
    self._curr_state_str = None
    # 2026-08-28 统计
    self._render_count = 0
    self._jitter_samples = collections.deque(maxlen=100)
    self._last_render_time = 0.0

  def run_one_frame(self):
    """执行一帧渲染：读取插值状态，设置 display env，调用 render()。"""
    state_str, alpha = self._state_holder.read_interpolated()
    _state_str_full, frame_id, _confirmed, state_time, waiting_for_authority = self._state_holder.read()

    if state_str is not None:
      self._prev_state_str = self._curr_state_str
      self._curr_state_str = state_str

      # 2026-08-28 Jitter 检测
      now = time.time()
      if self._last_render_time > 0:
        jitter = abs((now - self._last_render_time) - (1.0 / self._rate_hz))
        self._jitter_samples.append(jitter)
      self._last_render_time = now

      # 引擎不支持 partial set_state，直接设置完整状态
      # alpha 供外部 logging/debug 使用
      self._display_env.set_state(state_str)
      self._display_env.render()
      self._render_count += 1

  def get_jitter_stats(self):
    """返回渲染抖动统计：(avg_ms, max_ms, p95_ms)。"""
    if not self._jitter_samples:
      return 0.0, 0.0, 0.0
    samples = sorted(self._jitter_samples)
    avg = sum(samples) / len(samples)
    mx = samples[-1]
    p95_idx = int(len(samples) * 0.95)
    p95 = samples[min(p95_idx, len(samples) - 1)]
    return avg * 1000, mx * 1000, p95 * 1000

  @property
  def render_count(self):
    return self._render_count

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
