# Copyright 2026 Google LLC & Contributors
# 2026-08-28 帧同步网络指标监控：收集/聚合/导出 RTT、丢包、帧率、抖动等指标。
# 支持 JSON 导出和 Prometheus 格式导出。

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import time
import threading
import collections


class MetricsCollector(object):
  """网络指标收集器：线程安全，支持多维度指标聚合。"""

  def __init__(self, window_size=300):
    """window_size: 滑动窗口大小（秒），默认 5 分钟。"""
    self._lock = threading.Lock()
    self._window_size = window_size
    # 指标存储：metric_name -> deque of (timestamp, value)
    self._counters = {}  # 累计计数器
    self._gauges = {}    # 瞬时值
    self._histograms = {}  # 值分布
    # 帧率统计
    self._frame_times = collections.deque(maxlen=1000)
    self._last_frame_time = 0.0

  def record_rtt(self, rtt_ms):
    """记录 RTT 样本（毫秒）。"""
    self._record_histogram('rtt_ms', rtt_ms)
    self._set_gauge('rtt_latest_ms', rtt_ms)

  def record_packet_loss(self):
    """记录丢包事件。"""
    self._increment_counter('packet_loss_total')
    self._increment_counter('packets_lost')

  def record_packet_sent(self):
    """记录发包事件。"""
    self._increment_counter('packets_sent')

  def record_packet_received(self):
    """记录收包事件。"""
    self._increment_counter('packets_received')

  def record_frame_time(self):
    """记录帧处理时间（自动计算间隔）。"""
    now = time.time()
    if self._last_frame_time > 0:
      interval_ms = (now - self._last_frame_time) * 1000.0
      self._frame_times.append(interval_ms)
      self._record_histogram('frame_interval_ms', interval_ms)
    self._last_frame_time = now
    self._increment_counter('frames_total')

  def record_rollback(self):
    """记录回滚事件。"""
    self._increment_counter('rollbacks_total')

  def record_queue_depth(self, depth):
    """记录发送队列深度。"""
    self._set_gauge('queue_depth', depth)

  def record_state_hash_mismatch(self):
    """记录 state hash 不匹配事件。"""
    self._increment_counter('state_hash_mismatches')

  def record_jitter(self, jitter_ms):
    """记录帧间隔抖动（毫秒）。"""
    self._record_histogram('jitter_ms', jitter_ms)

  def record_disconnect(self):
    """记录断连事件。"""
    self._increment_counter('disconnects_total')

  def record_reconnect(self):
    """记录重连事件。"""
    self._increment_counter('reconnects_total')

  # ===== 内部方法 =====

  def _increment_counter(self, name):
    with self._lock:
      self._counters[name] = self._counters.get(name, 0) + 1

  def _set_gauge(self, name, value):
    with self._lock:
      self._gauges[name] = value

  def _record_histogram(self, name, value):
    now = time.time()
    with self._lock:
      if name not in self._histograms:
        self._histograms[name] = collections.deque(maxlen=10000)
      self._histograms[name].append((now, value))
      # 清理过期数据
      cutoff = now - self._window_size
      while self._histograms[name] and self._histograms[name][0][0] < cutoff:
        self._histograms[name].popleft()

  # ===== 查询方法 =====

  def get_counter(self, name):
    """获取累计计数器值。"""
    with self._lock:
      return self._counters.get(name, 0)

  def get_gauge(self, name):
    """获取瞬时值。"""
    with self._lock:
      return self._gauges.get(name, 0.0)

  def get_histogram_stats(self, name):
    """获取直方图统计：(avg, min, max, p50, p95, p99, count)。"""
    with self._lock:
      if name not in self._histograms or not self._histograms[name]:
        return {'avg': 0, 'min': 0, 'max': 0, 'p50': 0, 'p95': 0, 'p99': 0, 'count': 0}
      values = [v for _, v in self._histograms[name]]
      values.sort()
      count = len(values)
      return {
          'avg': round(sum(values) / count, 2),
          'min': round(values[0], 2),
          'max': round(values[-1], 2),
          'p50': round(values[count // 2], 2),
          'p95': round(values[int(count * 0.95)] if count > 0 else 0, 2),
          'p99': round(values[int(count * 0.99)] if count > 0 else 0, 2),
          'count': count,
      }

  def get_fps(self):
    """计算当前帧率（基于最近帧间隔）。"""
    with self._lock:
      if len(self._frame_times) < 2:
        return 0.0
      avg_interval = sum(self._frame_times) / len(self._frame_times)
      if avg_interval <= 0:
        return 0.0
      return round(1000.0 / avg_interval, 1)

  def get_all_metrics(self):
    """返回所有指标的完整快照。"""
    metrics = {}
    with self._lock:
      metrics['counters'] = dict(self._counters)
      metrics['gauges'] = dict(self._gauges)
    # 直方图统计
    for name in list(self._histograms.keys()):
      metrics[f'hist_{name}'] = self.get_histogram_stats(name)
    metrics['fps'] = self.get_fps()
    return metrics

  def export_json(self):
    """导出 JSON 格式指标。"""
    return json.dumps(self.get_all_metrics(), indent=2, ensure_ascii=False)

  def export_prometheus(self):
    """导出 Prometheus text 格式指标。"""
    lines = []
    with self._lock:
      for name, value in self._counters.items():
        lines.append(f'gfootball_framesync_{name} {value}')
      for name, value in self._gauges.items():
        lines.append(f'gfootball_framesync_{name} {value}')
    # 直方图
    for name in list(self._histograms.keys()):
      stats = self.get_histogram_stats(name)
      lines.append(f'gfootball_framesync_{name}_avg {stats["avg"]}')
      lines.append(f'gfootball_framesync_{name}_p95 {stats["p95"]}')
      lines.append(f'gfootball_framesync_{name}_max {stats["max"]}')
    lines.append(f'gfootball_framesync_fps {self.get_fps()}')
    return '\n'.join(lines)

  def reset(self):
    """重置所有指标。"""
    with self._lock:
      self._counters.clear()
      self._gauges.clear()
      self._histograms.clear()
      self._frame_times.clear()
      self._last_frame_time = 0.0
