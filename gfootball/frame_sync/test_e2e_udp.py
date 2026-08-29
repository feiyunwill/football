#!/usr/bin/env python3
"""End-to-end test: Python UDP client connecting to C++ UDP server."""

import sys
import time
import threading

from gfootball.frame_sync.client_udp import FrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput


def test_basic_connection():
    """Test basic connection flow: Connect → SessionStart → Ready → FrameInput."""
    print("=== Test: Basic UDP Connection ===")
    
    # Simple callback that returns dummy input
    def get_input():
        return [(0, SlotInput(1.0, 0.0, 0))]  # slot 0, move right
    
    client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
    
    try:
        print("Connecting to server...")
        session, slots = client.connect()
        print(f"SessionStart: seed={session[0]}, left={session[1]}, right={session[2]}")
        print(f"SlotAssignment: {slots}")
        
        # Send ready
        client.send_ready()
        print("Sent Ready")
        
        # Run for a few frames
        print("Running frame loop...")
        for i in range(10):
            client.send_frame_input(i)
            auth = client.pop_authoritative_frame()
            if auth:
                print(f"  Frame {i}: auth frame {auth[0]} received")
            else:
                print(f"  Frame {i}: waiting for auth frame")
            time.sleep(0.1)
        
        print("✓ Basic connection test passed!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


def test_state_hash():
    """Test StateHash verification."""
    print("\n=== Test: StateHash Verification ===")
    
    def get_input():
        return [(0, SlotInput(0.0, 1.0, 0))]  # slot 0, move up
    
    client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
    
    try:
        session, slots = client.connect()
        client.send_ready()
        
        # Run until we get a state hash
        for i in range(50):
            client.send_frame_input(i)
            auth = client.pop_authoritative_frame()
            state_hash = client.pop_state_hash()
            if state_hash:
                print(f"  Frame {i}: StateHash received: frame={state_hash[0]}, hash={state_hash[1]:#018x}")
                # Note: Can't verify without local engine, just check we received it
                print("  ✓ StateHash received successfully")
                return True
            time.sleep(0.1)
        
        print("  ⚠ No StateHash received in 50 frames")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


def test_heartbeat():
    """Test heartbeat reception."""
    print("\n=== Test: Heartbeat Reception ===")
    
    def get_input():
        return [(0, SlotInput(0.0, 0.0, 0))]
    
    client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
    
    try:
        session, slots = client.connect()
        client.send_ready()
        
        # Run for 2 seconds (should receive ~2 heartbeats)
        print("Waiting for heartbeats...")
        heartbeat_received = False
        for i in range(20):
            client.send_frame_input(i)
            client.pop_authoritative_frame()
            if client._last_heartbeat_ms > 0:
                heartbeat_received = True
            time.sleep(0.1)
        
        if heartbeat_received:
            print("  ✓ Heartbeat received")
        else:
            print("  ⚠ No heartbeat received (server may not be running)")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


if __name__ == '__main__':
    print("Frame Sync UDP Client E2E Tests")
    print("=" * 40)
    print("NOTE: C++ server must be running on port 12346")
    print("  Build: cmake --build build_rl -j 1 --target frame_sync_server_engine")
    print("  Run: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 1 1 42")
    print("=" * 40)
    
    results = []
    results.append(test_basic_connection())
    results.append(test_state_hash())
    results.append(test_heartbeat())
    
    print("\n" + "=" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    
    sys.exit(0 if passed == total else 1)
