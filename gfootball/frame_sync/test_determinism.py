#!/usr/bin/env python3
"""End-to-end determinism verification: Multiple clients compare StateHash."""

import sys
import time
import threading

from gfootball.frame_sync.client_udp import FrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput, compute_state_hash


class DeterminismTest:
    """Test determinism by comparing StateHash across multiple clients."""

    def __init__(self, host, port, num_clients=2, num_frames=100):
        self.host = host
        self.port = port
        self.num_clients = num_clients
        self.num_frames = num_frames
        self.clients = []
        self.state_hashes = {}  # frame_id -> list of (client_id, hash)
        self.lock = threading.Lock()

    def run(self):
        print(f"=== Determinism Test: {self.num_clients} clients, {self.num_frames} frames ===")
        print(f"Server: {self.host}:{self.port}")
        print()

        # Create clients
        for i in range(self.num_clients):
            client_id = i
            def get_input(cid=client_id):
                # All clients send the same input for determinism
                return [(0, SlotInput(1.0, 0.0, 0))]
            
            client = FrameSyncUDPClient(self.host, self.port, get_input)
            self.clients.append(client)

        # Connect all clients
        print("Connecting clients...")
        connected = 0
        for i, client in enumerate(self.clients):
            try:
                session, slots = client.connect()
                print(f"  Client {i}: connected, slots={slots}")
                connected += 1
            except Exception as e:
                print(f"  Client {i}: failed - {e}")
        
        if connected < 2:
            print("Need at least 2 clients for determinism test!")
            return False

        # Send ready
        for client in self.clients:
            client.send_ready()

        # Run frame loop
        print(f"\nRunning {self.num_frames} frames...")
        mismatch_count = 0
        
        for frame in range(self.num_frames):
            # Send inputs and collect state hashes
            for i, client in enumerate(self.clients):
                try:
                    client.send_frame_input(frame)
                    auth = client.pop_authoritative_frame()
                    
                    # Check for state hash
                    state_hash = client.pop_state_hash()
                    if state_hash:
                        fid, hash_val = state_hash
                        with self.lock:
                            if fid not in self.state_hashes:
                                self.state_hashes[fid] = []
                            self.state_hashes[fid].append((i, hash_val))
                except Exception as e:
                    print(f"  Client {i} frame {frame} error: {e}")
            
            # Check for mismatches
            with self.lock:
                if frame in self.state_hashes:
                    hashes = self.state_hashes[frame]
                    if len(hashes) >= 2:
                        unique_hashes = set(h for _, h in hashes)
                        if len(unique_hashes) > 1:
                            mismatch_count += 1
                            print(f"  ⚠ Frame {frame}: HASH MISMATCH!")
                            for cid, h in hashes:
                                print(f"    Client {cid}: {h:#018x}")
            
            if frame % 50 == 0:
                print(f"  Frame {frame}/{self.num_frames}...")
            
            time.sleep(0.1)

        # Summary
        print("\n=== Results ===")
        print(f"Total frames: {self.num_frames}")
        print(f"State hashes collected: {len(self.state_hashes)}")
        print(f"Hash mismatches: {mismatch_count}")
        
        if mismatch_count == 0:
            print("✓ DETERMINISM VERIFIED: All clients produced identical state hashes!")
        else:
            print(f"✗ DETERMINISM FAILED: {mismatch_count} frames had mismatched hashes")

        # Cleanup
        for client in self.clients:
            client.close()

        return mismatch_count == 0


def test_two_clients():
    """Test determinism with 2 clients."""
    test = DeterminismTest('127.0.0.1', 12346, num_clients=2, num_frames=100)
    return test.run()


def test_long_run():
    """Test determinism over 1000 frames."""
    test = DeterminismTest('127.0.0.1', 12346, num_clients=2, num_frames=1000)
    return test.run()


if __name__ == '__main__':
    print("Frame Sync Determinism Tests")
    print("=" * 40)
    print("NOTE: C++ server must be running")
    print("  Build: cmake --build build_rl -j 1 --target frame_sync_server_engine")
    print("  Run: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 1 1 42")
    print("=" * 40)

    results = []
    results.append(test_two_clients())
    # Uncomment for long run test
    # results.append(test_long_run())

    print("\n" + "=" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    sys.exit(0 if passed == total else 1)
