# 2026-09-10: preserve old false-positive checks; require actual evidence below.
# #!/usr/bin/env python3
# """End-to-end test: Python UDP client connecting to C++ UDP server."""
# 
# # 2026-09-09: collected through asserting wrappers in legacy_network_test.py.
# __test__ = False
# 
# import sys
# import time
# import threading
# 
# from gfootball.frame_sync.client_udp import FrameSyncUDPClient
# from gfootball.frame_sync.protocol import SlotInput
# 
# 
# def test_basic_connection():
#     """Test basic connection flow: Connect → SessionStart → Ready → FrameInput."""
#     print("=== Test: Basic UDP Connection ===")
#     
#     # Simple callback that returns dummy input
#     def get_input():
#         return [(0, SlotInput(1.0, 0.0, 0))]  # slot 0, move right
#     
#     client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
#     
#     try:
#         print("Connecting to server...")
#         session, slots = client.connect()
#         print(f"SessionStart: seed={session[0]}, left={session[1]}, right={session[2]}")
#         print(f"SlotAssignment: {slots}")
#         
#         # Send ready
#         client.send_ready()
#         print("Sent Ready")
#         
#         # Run for a few frames
#         print("Running frame loop...")
#         for i in range(10):
#             client.send_frame_input(i)
#             auth = client.pop_authoritative_frame()
#             if auth:
#                 print(f"  Frame {i}: auth frame {auth[0]} received")
#             else:
#                 print(f"  Frame {i}: waiting for auth frame")
#             time.sleep(0.1)
#         
#         print("✓ Basic connection test passed!")
#         return True
#         
#     except Exception as e:
#         print(f"✗ Test failed: {e}")
#         return False
#     finally:
#         client.close()
# 
# 
# def test_state_hash():
#     """Test StateHash verification."""
#     print("\n=== Test: StateHash Verification ===")
#     
#     def get_input():
#         return [(0, SlotInput(0.0, 1.0, 0))]  # slot 0, move up
#     
#     client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
#     
#     try:
#         session, slots = client.connect()
#         client.send_ready()
#         
#         # Run until we get a state hash
#         for i in range(50):
#             client.send_frame_input(i)
#             auth = client.pop_authoritative_frame()
#             state_hash = client.pop_state_hash()
#             if state_hash:
#                 print(f"  Frame {i}: StateHash received: frame={state_hash[0]}, hash={state_hash[1]:#018x}")
#                 # Note: Can't verify without local engine, just check we received it
#                 print("  ✓ StateHash received successfully")
#                 return True
#             time.sleep(0.1)
#         
#         print("  ⚠ No StateHash received in 50 frames")
#         return True
#         
#     except Exception as e:
#         print(f"✗ Test failed: {e}")
#         return False
#     finally:
#         client.close()
# 
# 
# def test_heartbeat():
#     """Test heartbeat reception."""
#     print("\n=== Test: Heartbeat Reception ===")
#     
#     def get_input():
#         return [(0, SlotInput(0.0, 0.0, 0))]
#     
#     client = FrameSyncUDPClient('127.0.0.1', 12346, get_input)
#     
#     try:
#         session, slots = client.connect()
#         client.send_ready()
#         
#         # Run for 2 seconds (should receive ~2 heartbeats)
#         print("Waiting for heartbeats...")
#         heartbeat_received = False
#         for i in range(20):
#             client.send_frame_input(i)
#             client.pop_authoritative_frame()
#             if client._last_heartbeat_ms > 0:
#                 heartbeat_received = True
#             time.sleep(0.1)
#         
#         if heartbeat_received:
#             print("  ✓ Heartbeat received")
#         else:
#             print("  ⚠ No heartbeat received (server may not be running)")
#         
#         return True
#         
#     except Exception as e:
#         print(f"✗ Test failed: {e}")
#         return False
#     finally:
#         client.close()
# 
# 
# if __name__ == '__main__':
#     print("Frame Sync UDP Client E2E Tests")
#     print("=" * 40)
#     print("NOTE: C++ server must be running on port 12346")
#     print("  Build: cmake --build build_rl -j 1 --target frame_sync_server_engine")
#     print("  Run: GFOOTBALL_DATA_DIR=../data ./frame_sync_server_engine 12346 1 1 42")
#     print("=" * 40)
#     
#     results = []
#     results.append(test_basic_connection())
#     results.append(test_state_hash())
#     results.append(test_heartbeat())
#     
#     print("\n" + "=" * 40)
#     passed = sum(results)
#     total = len(results)
#     print(f"Results: {passed}/{total} passed")
#     
#     sys.exit(0 if passed == total else 1)

#!/usr/bin/env python3
"""Actual UDP session checks; each function needs a fresh one-client server.

These checks require actual authority/hash/heartbeat messages. Receiving a hash
is a transport check; canonical GameEnv equality requires a local native replica.
The CLI runs all three requirements in ONE session because legacy UDP servers
reserve disconnected slots until the match ends.
"""
__test__ = False

import time
from gfootball.frame_sync.client_udp import FrameSyncUDPClient
from gfootball.frame_sync.protocol import SlotInput


def exercise_session(client, *, timeout=10.0, require_hash=True, require_heartbeat=True):
  session, slots = client.connect()
  if not client.send_ready():
    raise RuntimeError('UDP Ready was rejected')
  received = 0
  first_hash = None
  deadline = time.monotonic() + timeout
  next_send = 0.0
  while time.monotonic() < deadline:
    if client.is_disconnected():
      raise RuntimeError('UDP session failed: ' + str(client.failure_reason))
    now = time.monotonic()
    if now >= next_send:
      entries = [(slot, SlotInput(.5, 0.0, 0)) for slot in slots]
      if not client.send_frame_entries(received, entries):
        raise RuntimeError('UDP input was rejected')
      next_send = now + .1
    while client.has_authoritative_frame():
      frame, values = client.pop_authoritative_frame()
      if frame != received or len(values) != session[1] + session[2]:
        raise RuntimeError('Nonconsecutive or invalid authority')
      received += 1
      next_send = 0.0
    while True:
      state_hash = client.pop_state_hash()
      if state_hash is None:
        break
      if first_hash is None:
        first_hash = state_hash
    heartbeat_count = client.stats()['received_heartbeats']
    if received >= 10 and (not require_hash or first_hash is not None) and (not require_heartbeat or heartbeat_count):
      return dict(authority_frames=received, first_hash=first_hash, received_heartbeats=heartbeat_count)
    time.sleep(.005)
  raise RuntimeError('UDP evidence deadline: authority=%d, hash=%r, heartbeats=%d' %
                     (received, first_hash, client.stats()['received_heartbeats']))


def _check(**requirements):
  with FrameSyncUDPClient('127.0.0.1', 12346) as client:
    try:
      evidence = exercise_session(client, **requirements)
      print('UDP session passed:', evidence)
      return True
    except (OSError, RuntimeError, ValueError) as error:
      print('UDP session failed:', error)
      return False


def test_basic_connection():
  return _check(require_hash=False, require_heartbeat=False)


def test_state_hash():
  return _check(require_hash=True, require_heartbeat=False)


def test_heartbeat():
  return _check(require_hash=False, require_heartbeat=True)


if __name__ == '__main__':
  raise SystemExit(0 if _check() else 1)
