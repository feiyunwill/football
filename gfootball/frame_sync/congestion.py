# Copyright 2026 Google LLC & Contributors
# 2026-08-28 帧同步拥塞控制：基于 RTT 的发送速率调整 + 队列深度监控。
# TCP 自身处理传输层拥塞控制；本模块在应用层实现：
# 1. 发送速率限制：RTT 高时降低逻辑帧率
# 2. 队列深度监控：检测积压并告警
# 3. 自适应超时：根据 RTT 动态调整 FRAME_INPUT_TIMEOUT

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time
import collections


class CongestionMonitor(object):
  """拥塞监控器：跟踪 RTT、丢包率、队列深度，提供自适应参数。"""

  def __init__(self, target_fps=10.0):
    self._target_fps = target_fps
    self._rtt_samples = collections.deque(maxlen=100)
    self._loss_count = 0
    self._total_frames = 0
    self._queue_depths = collections.deque(maxlen=50)
    self._last_adjust_time = time.time()
    self._current_fps = target_fps
    self._jitter_samples = collections.deque(maxlen=50)

  def update_rtt(self, rtt_ms):
    """更新 RTT 样本（毫秒）。"""
    self._rtt_samples.append(rtt_ms)

  def update_loss(self, lost=True):
    """更新丢包事件。"""
    self._total_frames += 1
    if lost:
      self._loss_count += 1

  def update_queue_depth(self, depth):
    """更新发送队列深度。"""
    self._queue_depths.append(depth)

  def update_jitter(self, jitter_ms):
    """更新帧间隔抖动（毫秒）。"""
    self._jitter_samples.append(jitter_ms)

  def get_adaptive_fps(self):
    """根据网络状况返回自适应帧率。

    策略：
    - RTT < 50ms 且丢包率 < 1% → 目标帧率
    - RTT 50-100ms 或丢包率 1-5% → 降低 20%
    - RTT > 100ms 或丢包率 > 5% → 降低 50%
    - 队列深度 > 5 → 降低 30%
    """
    avg_rtt = self.get_avg_rtt_ms()
    loss_rate = self.get_loss_rate()
    max_queue = self.get_max_queue_depth()

    fps = self._target_fps

    # RTT 调整
    if avg_rtt > 100:
      fps *= 0.5
    elif avg_rtt > 50:
      fps *= 0.8

    # 丢包率调整
    if loss_rate > 0.05:
      fps *= 0.5
    elif loss_rate > 0.01:
      fps *= 0.8

    # 队列深度调整
    if max_queue > 5:
      fps *= 0.7

    self._current_fps = max(1.0, fps)
    return self._current_fps

  def get_adaptive_timeout_ms(self):
    """根据 RTT 返回自适应超时（毫秒）。"""
    avg_rtt = self.get_avg_rtt_ms()
    if avg_rtt <= 0:
      return 200  # 默认
    # 超时 = 3 × RTT + 100ms 余量
    return max(100, int(avg_rtt * 3 + 100))

  def get_adaptive_predict_cap(self):
    """根据 RTT 返回自适应预测帧数上限。"""
    avg_rtt = self.get_avg_rtt_ms()
    if avg_rtt > 150:
      return 1
    elif avg_rtt > 80:
      return 2
    return 3

  def get_avg_rtt_ms(self):
    """返回平均 RTT（毫秒）。"""
    if not self._rtt_samples:
      return 0.0
    return sum(self._rtt_samples) / len(self._rtt_samples)

  def get_max_rtt_ms(self):
    """返回最大 RTT（毫秒）。"""
    if not self._rtt_samples:
      return 0.0
    return max(self._rtt_samples)

  def get_p95_rtt_ms(self):
    """返回 P95 RTT（毫秒）。"""
    if not self._rtt_samples:
      return 0.0
    sorted_samples = sorted(self._rtt_samples)
    idx = int(len(sorted_samples) * 0.95)
    return sorted_samples[min(idx, len(sorted_samples) - 1)]

  def get_loss_rate(self):
    """返回丢包率 [0, 1]。"""
    if self._total_frames == 0:
      return 0.0
    return self._loss_count / self._total_frames

  def get_max_queue_depth(self):
    """返回最大队列深度。"""
    if not self._queue_depths:
      return 0
    return max(self._queue_depths)

  def get_avg_jitter_ms(self):
    """返回平均帧间隔抖动（毫秒）。"""
    if not self._jitter_samples:
      return 0.0
    return sum(self._jitter_samples) / len(self._jitter_samples)

  def get_stats(self):
    """返回完整统计字典。"""
    return {
        'avg_rtt_ms': round(self.get_avg_rtt_ms(), 2),
        'max_rtt_ms': round(self.get_max_rtt_ms(), 2),
        'p95_rtt_ms': round(self.get_p95_rtt_ms(), 2),
        'loss_rate': round(self.get_loss_rate(), 4),
        'max_queue_depth': self.get_max_queue_depth(),
        'avg_jitter_ms': round(self.get_avg_jitter_ms(), 2),
        'adaptive_fps': round(self._current_fps, 1),
        'adaptive_timeout_ms': self.get_adaptive_timeout_ms(),
        'adaptive_predict_cap': self.get_adaptive_predict_cap(),
        'total_frames': self._total_frames,
    }

  def reset(self):
    """重置所有统计。"""
    self._rtt_samples.clear()
    self._loss_count = 0
    self._total_frames = 0
    self._queue_depths.clear()
    self._jitter_samples.clear()
    self._current_fps = self._target_fps
