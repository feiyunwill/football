#!/usr/bin/env python3
"""Comprehensive E2E test suite for frame sync system."""

import sys
import subprocess
import time
import os

from gfootball.frame_sync.test_determinism import DeterminismTest
from gfootball.frame_sync.test_performance import PerformanceBenchmark
from gfootball.frame_sync.test_multi_client import MultiClientTest


class E2ETestSuite:
    """Complete end-to-end test suite."""

    def __init__(self, host='127.0.0.1', port=12346):
        self.host = host
        self.port = port
        self.results = {}

    def run_all(self):
        print("=" * 60)
        print("Frame Sync E2E Test Suite")
        print("=" * 60)
        
        tests = [
            ("Multi-Client Connection", self.test_multi_client),
            ("Determinism (2 clients)", self.test_determinism_2),
            ("Determinism (1000 frames)", self.test_determinism_long),
            ("Performance Benchmark", self.test_performance),
        ]
        
        for name, test_func in tests:
            print(f"\n{'=' * 60}")
            print(f"Running: {name}")
            print("=" * 60)
            try:
                result = test_func()
                self.results[name] = result
            except Exception as e:
                print(f"✗ Test failed with exception: {e}")
                self.results[name] = False
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        passed = 0
        total = len(self.results)
        
        for name, result in self.results.items():
            status = "✓ PASSED" if result else "✗ FAILED"
            print(f"  {status}: {name}")
            if result:
                passed += 1
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n⚠ {total - passed} test(s) failed")
        
        return passed == total

    def test_multi_client(self):
        test = MultiClientTest(self.host, self.port, num_clients=2, slots_per_client=1)
        return test.run()

    def test_determinism_2(self):
        test = DeterminismTest(self.host, self.port, num_clients=2, num_frames=100)
        return test.run()

    def test_determinism_long(self):
        test = DeterminismTest(self.host, self.port, num_clients=2, num_frames=1000)
        return test.run()

    def test_performance(self):
        benchmark = PerformanceBenchmark(self.host, self.port, num_frames=500)
        return benchmark.run()


def check_server_running(host, port):
    """Check if server is running."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except:
        return False


if __name__ == '__main__':
    print("Frame Sync E2E Test Suite")
    print("=" * 60)
    print("Prerequisites:")
    print("  1. Build server: cd third_party/gfootball_engine")
    print("     cmake --build build_rl -j 1 --target frame_sync_server_engine")
    print("  2. Run server: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 1 1 42")
    print("=" * 60)
    
    # Check if server is running
    if not check_server_running('127.0.0.1', 12346):
        print("\n⚠ Server not detected on port 12346")
        print("Please start the server first!")
        sys.exit(1)
    
    suite = E2ETestSuite()
    success = suite.run_all()
    sys.exit(0 if success else 1)
