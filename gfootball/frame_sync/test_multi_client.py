#!/usr/bin/env python3
"""Multi-client test: Multiple Python UDP clients connecting to C++ server."""

import sys
import time
import threading

from gfootball.frame_sync.client_udp import FrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput


class MultiClientTest:
    """Test multiple clients connecting to the same server."""

    def __init__(self, host, port, num_clients, slots_per_client=0):
        self.host = host
        self.port = port
        self.num_clients = num_clients
        self.slots_per_client = slots_per_client
        self.clients = []
        self.results = []

    def run(self):
        print(f"=== Multi-Client Test: {self.num_clients} clients ===")
        print(f"Server: {self.host}:{self.port}")
        print(f"Slots per client: {self.slots_per_client or 'all'}")
        print()

        # Create clients
        for i in range(self.num_clients):
            client_id = i
            def get_input(cid=client_id):
                # Each client controls different slots with different inputs
                return [(cid % 2, SlotInput(float(cid), 0.0, 0))]
            
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
        
        if connected == 0:
            print("No clients connected!")
            return False

        print(f"\n{connected}/{self.num_clients} clients connected")

        # Send ready for all clients
        for i, client in enumerate(self.clients):
            try:
                client.send_ready()
                print(f"  Client {i}: ready sent")
            except Exception as e:
                print(f"  Client {i}: ready failed - {e}")

        # Run frame loop
        print("\nRunning frame loop...")
        frames_per_client = {i: 0 for i in range(len(self.clients))}
        auth_frames_received = {i: 0 for i in range(len(self.clients))}
        
        for frame in range(50):
            for i, client in enumerate(self.clients):
                try:
                    client.send_frame_input(frame)
                    auth = client.pop_authoritative_frame()
                    if auth:
                        auth_frames_received[i] += 1
                        frames_per_client[i] = auth[0]
                except Exception as e:
                    print(f"  Client {i} frame {frame} error: {e}")
            
            if frame % 10 == 0:
                print(f"  Frame {frame}: auth frames = {list(auth_frames_received.values())}")
            
            time.sleep(0.1)

        # Summary
        print("\n=== Results ===")
        for i, client in enumerate(self.clients):
            print(f"  Client {i}: received {auth_frames_received[i]} auth frames")
            print(f"    RTT: {client.get_avg_rtt_ms():.1f}ms avg, {client.get_rtt_ms():.1f}ms last")

        # Cleanup
        for client in self.clients:
            client.close()

        return all(v > 0 for v in auth_frames_received.values())


def test_two_clients():
    """Test 2 clients connecting."""
    test = MultiClientTest('127.0.0.1', 12346, num_clients=2, slots_per_client=1)
    return test.run()


def test_four_clients():
    """Test 4 clients connecting."""
    test = MultiClientTest('127.0.0.1', 12346, num_clients=4, slots_per_client=1)
    return test.run()


if __name__ == '__main__':
    print("Frame Sync Multi-Client Tests")
    print("=" * 40)
    print("NOTE: C++ server must be running with slots_per_client=1")
    print("  Build: cmake --build build_rl -j 1 --target frame_sync_server_engine")
    print("  Run: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 2 2 42 1")
    print("=" * 40)

    results = []
    results.append(test_two_clients())
    # Uncomment to test 4 clients (requires server with 4+ slots)
    # results.append(test_four_clients())

    print("\n" + "=" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    sys.exit(0 if passed == total else 1)
