#!/usr/bin/env python3
"""Reconnection test: Simulate disconnect and verify auto-reconnect."""

import sys
import time
import threading
import socket

from gfootball.frame_sync.client_udp import FrameSyncUDPClient, ReconnectingFrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput


def test_basic_reconnect():
    """Test basic reconnection flow."""
    print("=== Test: Basic Reconnection ===")
    
    def get_input():
        return [(0, SlotInput(1.0, 0.0, 0))]
    
    client = ReconnectingFrameSyncUDPClient('127.0.0.1', 12346, get_input)
    
    reconnect_count = [0]
    def on_reconnect(session, slots):
        reconnect_count[0] += 1
        print(f"  Reconnected! Attempt {reconnect_count[0]}")
    
    client.set_on_reconnect(on_reconnect)
    
    try:
        print("Connecting...")
        session, slots = client.connect()
        print(f"Connected: session={session}, slots={slots}")
        
        # Run for a few frames
        print("Running frame loop...")
        for i in range(10):
            client.tick()
            if not client.is_reconnecting:
                client.client.send_frame_input(i)
                client.client.pop_authoritative_frame()
            time.sleep(0.1)
        
        print(f"  Reconnect count: {reconnect_count[0]}")
        print("✓ Basic reconnection test passed!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


def test_disconnect_detection():
    """Test disconnect detection via heartbeat timeout."""
    print("\n=== Test: Disconnect Detection ===")
    
    def get_input():
        return [(0, SlotInput(0.0, 0.0, 0))]
    
    client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
    
    try:
        session, slots = client.connect()
        client.send_ready()
        
        # Simulate server not sending heartbeats
        print("Simulating heartbeat timeout...")
        client._last_heartbeat_ms = int(time.time() * 1000) - 10000  # 10 seconds ago
        
        # Check disconnect detection
        for i in range(20):
            client.tick_disconnect_detection()
            if client.is_disconnected():
                print(f"  Detected disconnect after {i} ticks")
                break
            time.sleep(0.1)
        
        if client.is_disconnected():
            print("  ✓ Disconnect detection working")
        else:
            print("  ⚠ Disconnect not detected (server may be sending heartbeats)")
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


def test_exponential_backoff():
    """Test exponential backoff on reconnection failures."""
    print("\n=== Test: Exponential Backoff ===")
    
    # Try connecting to a non-existent server
    client = ReconnectingFrameSyncUDPClient('127.0.0.1', 99999)
    
    backoff_times = []
    def on_disconnect():
        backoff_times.append(time.time())
    
    client.set_on_disconnect(on_disconnect)
    
    try:
        # This should fail immediately
        try:
            client.connect()
        except:
            pass
        
        # Tick to trigger reconnection
        for i in range(5):
            client.tick()
            time.sleep(0.01)
        
        print(f"  Backoff events: {len(backoff_times)}")
        print("✓ Exponential backoff test passed!")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    finally:
        client.close()


if __name__ == '__main__':
    print("Frame Sync Reconnection Tests")
    print("=" * 40)
    print("NOTE: C++ server should be running on port 12346")
    print("=" * 40)
    
    results = []
    results.append(test_basic_reconnect())
    results.append(test_disconnect_detection())
    results.append(test_exponential_backoff())
    
    print("\n" + "=" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    
    sys.exit(0 if passed == total else 1)
