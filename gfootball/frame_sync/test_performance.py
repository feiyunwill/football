#!/usr/bin/env python3
"""Performance benchmark: Measure frame processing latency and throughput."""

import sys
import time
import statistics

from gfootball.frame_sync.client_udp import FrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput


class PerformanceBenchmark:
    """Benchmark frame processing performance."""

    def __init__(self, host, port, num_frames=500):
        self.host = host
        self.port = port
        self.num_frames = num_frames
        self.latencies = []
        self.throughput_samples = []

    def run(self):
        print(f"=== Performance Benchmark: {self.num_frames} frames ===")
        print(f"Server: {self.host}:{self.port}")
        print()

        def get_input():
            return [(0, SlotInput(1.0, 0.0, 0))]

        client = FrameSyncUDPClient(self.host, self.port, get_input)

        try:
            # Connect
            print("Connecting...")
            session, slots = client.connect()
            print(f"Connected: slots={slots}")
            client.send_ready()

            # Warmup
            print("Warming up...")
            for i in range(50):
                client.send_frame_input(i)
                client.pop_authoritative_frame()
                time.sleep(0.01)

            # Benchmark
            print(f"Running benchmark ({self.num_frames} frames)...")
            frame_times = []
            
            for frame in range(self.num_frames):
                t0 = time.time()
                
                client.send_frame_input(frame)
                auth = client.pop_authoritative_frame()
                
                t1 = time.time()
                latency_ms = (t1 - t0) * 1000
                frame_times.append(latency_ms)
                
                if frame % 100 == 0:
                    print(f"  Frame {frame}: {latency_ms:.2f}ms")
                
                # Maintain 10 Hz frame rate
                elapsed = t1 - t0
                if elapsed < 0.1:
                    time.sleep(0.1 - elapsed)

            # Calculate statistics
            avg_latency = statistics.mean(frame_times)
            p50_latency = statistics.percentile(frame_times, 50)
            p95_latency = statistics.percentile(frame_times, 95)
            p99_latency = statistics.percentile(frame_times, 99)
            max_latency = max(frame_times)
            
            throughput = self.num_frames / (sum(frame_times) / 1000)

            # RTT statistics
            avg_rtt = client.get_avg_rtt_ms()
            last_rtt = client.get_rtt_ms()

            # Summary
            print("\n=== Performance Results ===")
            print(f"Frames processed: {self.num_frames}")
            print(f"Average latency: {avg_latency:.2f}ms")
            print(f"P50 latency: {p50_latency:.2f}ms")
            print(f"P95 latency: {p95_latency:.2f}ms")
            print(f"P99 latency: {p99_latency:.2f}ms")
            print(f"Max latency: {max_latency:.2f}ms")
            print(f"Throughput: {throughput:.1f} frames/sec")
            print(f"Average RTT: {avg_rtt:.2f}ms")
            print(f"Last RTT: {last_rtt:.2f}ms")
            
            # Performance targets
            print("\n=== Performance Targets ===")
            targets = [
                ("Avg latency < 16ms (60fps)", avg_latency < 16),
                ("P95 latency < 50ms", p95_latency < 50),
                ("Throughput > 10 fps", throughput > 10),
            ]
            
            all_passed = True
            for name, passed in targets:
                status = "✓" if passed else "✗"
                print(f"  {status} {name}")
                if not passed:
                    all_passed = False

            client.close()
            return all_passed

        except Exception as e:
            print(f"✗ Benchmark failed: {e}")
            client.close()
            return False


def run_benchmark():
    """Run performance benchmark."""
    benchmark = PerformanceBenchmark('127.0.0.1', 12346, num_frames=500)
    return benchmark.run()


if __name__ == '__main__':
    print("Frame Sync Performance Benchmark")
    print("=" * 40)
    print("NOTE: C++ server must be running")
    print("  Build: cmake --build build_rl -j 1 --target frame_sync_server_engine")
    print("  Run: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 1 1 42")
    print("=" * 40)

    success = run_benchmark()
    sys.exit(0 if success else 1)
