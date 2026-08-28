# Copyright 2026 Google LLC & Contributors
# P2 后续：congestion.py / metrics.py 单元测试

import json
import pytest

from gfootball.frame_sync.congestion import CongestionMonitor
from gfootball.frame_sync.metrics import MetricsCollector


# ===== CongestionMonitor 测试 =====

class TestCongestionMonitor:
    def setup_method(self):
        self.mon = CongestionMonitor()

    def test_default_state(self):
        assert self.mon.get_avg_rtt_ms() == 0.0
        assert self.mon.get_loss_rate() == 0.0
        assert self.mon.get_max_queue_depth() == 0
        assert self.mon.get_adaptive_fps() > 0

    def test_update_rtt(self):
        self.mon.update_rtt(50.0)
        assert self.mon.get_avg_rtt_ms() == 50.0
        self.mon.update_rtt(100.0)
        assert abs(self.mon.get_avg_rtt_ms() - 75.0) < 0.01

    def test_max_rtt(self):
        self.mon.update_rtt(30.0)
        self.mon.update_rtt(80.0)
        self.mon.update_rtt(50.0)
        assert self.mon.get_max_rtt_ms() == 80.0

    def test_p95_rtt(self):
        for i in range(100):
            self.mon.update_rtt(float(i))
        p95 = self.mon.get_p95_rtt_ms()
        assert p95 >= 90.0

    def test_update_loss(self):
        for _ in range(10):
            self.mon.update_loss(lost=False)
        self.mon.update_loss(lost=True)
        assert abs(self.mon.get_loss_rate() - 0.1) < 0.01

    def test_update_queue_depth(self):
        self.mon.update_queue_depth(5)
        assert self.mon.get_max_queue_depth() == 5
        self.mon.update_queue_depth(3)
        assert self.mon.get_max_queue_depth() == 5

    def test_low_congestion_high_fps(self):
        self.mon.update_rtt(10.0)
        fps = self.mon.get_adaptive_fps()
        assert fps >= 8.0

    def test_high_congestion_low_fps(self):
        for _ in range(10):
            self.mon.update_rtt(200.0)
            self.mon.update_loss(lost=True)
        fps = self.mon.get_adaptive_fps()
        assert fps <= 5.0

    def test_adaptive_timeout(self):
        timeout = self.mon.get_adaptive_timeout_ms()
        assert timeout >= 100
        self.mon.update_rtt(100.0)
        timeout = self.mon.get_adaptive_timeout_ms()
        assert timeout >= 400

    def test_adaptive_predict_cap(self):
        assert self.mon.get_adaptive_predict_cap() == 3
        self.mon.update_rtt(200.0)
        assert self.mon.get_adaptive_predict_cap() == 1

    def test_jitter(self):
        self.mon.update_jitter(5.0)
        self.mon.update_jitter(15.0)
        assert abs(self.mon.get_avg_jitter_ms() - 10.0) < 0.01

    def test_get_stats(self):
        self.mon.update_rtt(50.0)
        self.mon.update_loss(lost=True)
        self.mon.update_queue_depth(3)
        stats = self.mon.get_stats()
        assert "avg_rtt_ms" in stats
        assert "loss_rate" in stats
        assert "adaptive_fps" in stats
        assert stats["total_frames"] == 1

    def test_reset(self):
        self.mon.update_rtt(100.0)
        self.mon.update_loss(lost=True)
        self.mon.update_queue_depth(10)
        self.mon.reset()
        assert self.mon.get_avg_rtt_ms() == 0.0
        assert self.mon.get_loss_rate() == 0.0
        assert self.mon.get_max_queue_depth() == 0


# ===== MetricsCollector 测试 =====

class TestMetricsCollector:
    def setup_method(self):
        self.mc = MetricsCollector()

    def test_record_rtt(self):
        self.mc.record_rtt(50.0)
        self.mc.record_rtt(80.0)
        stats = self.mc.get_histogram_stats('rtt_ms')
        assert stats['count'] == 2
        assert stats['min'] == 50.0
        assert stats['max'] == 80.0

    def test_record_packet_loss(self):
        self.mc.record_packet_loss()
        self.mc.record_packet_loss()
        assert self.mc.get_counter('packet_loss_total') == 2
        assert self.mc.get_counter('packets_lost') == 2

    def test_record_packet_sent(self):
        for _ in range(5):
            self.mc.record_packet_sent()
        assert self.mc.get_counter('packets_sent') == 5

    def test_record_packet_received(self):
        for _ in range(3):
            self.mc.record_packet_received()
        assert self.mc.get_counter('packets_received') == 3

    def test_record_rollback(self):
        self.mc.record_rollback()
        assert self.mc.get_counter('rollbacks_total') == 1

    def test_record_queue_depth(self):
        self.mc.record_queue_depth(10)
        assert self.mc.get_gauge('queue_depth') == 10

    def test_record_state_hash_mismatch(self):
        self.mc.record_state_hash_mismatch()
        assert self.mc.get_counter('state_hash_mismatches') == 1

    def test_record_jitter(self):
        self.mc.record_jitter(5.0)
        self.mc.record_jitter(15.0)
        stats = self.mc.get_histogram_stats('jitter_ms')
        assert stats['count'] == 2

    def test_record_disconnect_reconnect(self):
        self.mc.record_disconnect()
        self.mc.record_reconnect()
        assert self.mc.get_counter('disconnects_total') == 1
        assert self.mc.get_counter('reconnects_total') == 1

    def test_export_json(self):
        self.mc.record_rtt(50.0)
        self.mc.record_packet_sent()
        exported = self.mc.export_json()
        data = json.loads(exported)
        assert "counters" in data
        assert "gauges" in data
        assert data["counters"]["packets_sent"] == 1

    def test_export_prometheus(self):
        self.mc.record_rtt(50.0)
        self.mc.record_packet_sent()
        prom = self.mc.export_prometheus()
        assert "gfootball_framesync_packets_sent 1" in prom
        assert "gfootball_framesync_rtt_ms_avg" in prom

    def test_get_all_metrics(self):
        self.mc.record_rtt(50.0)
        self.mc.record_packet_sent()
        metrics = self.mc.get_all_metrics()
        assert "counters" in metrics
        assert "gauges" in metrics
        assert "fps" in metrics

    def test_reset(self):
        self.mc.record_rtt(50.0)
        self.mc.record_packet_sent()
        self.mc.reset()
        assert self.mc.get_counter('packets_sent') == 0
        stats = self.mc.get_histogram_stats('rtt_ms')
        assert stats['count'] == 0

    def test_thread_safety(self):
        import threading
        def record_fn():
            for _ in range(100):
                self.mc.record_rtt(50.0)
                self.mc.record_packet_sent()

        threads = [threading.Thread(target=record_fn) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert self.mc.get_counter('packets_sent') == 400
        stats = self.mc.get_histogram_stats('rtt_ms')
        assert stats['count'] == 400
