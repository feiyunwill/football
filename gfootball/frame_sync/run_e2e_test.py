# Copyright 2019 Google LLC
# End-to-end test (task 5.1): 1 server + 2 clients, same scenario, run N frames,
# verify no crash and optionally state consistency.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import hashlib
import socket
import threading
import time

from gfootball.frame_sync.server import FrameSyncServer
from gfootball.frame_sync.client import FrameSyncClient
from gfootball.frame_sync.protocol import default_slot_input, STATE_HASH_INTERVAL_K


def _find_free_port():
  s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  s.bind(('127.0.0.1', 0))
  port = s.getsockname()[1]
  s.close()
  return port


def run_e2e_test(num_frames=20, scenario='academy_empty_goal'):
  port = _find_free_port()
  server = FrameSyncServer(
      listen_host='127.0.0.1',
      listen_port=port,
      scenario_name=scenario,
      left_agents=1,
      right_agents=1,
      game_engine_random_seed=42,
      state_hash_interval=STATE_HASH_INTERVAL_K,
  )
  server.start()
  try:
    time.sleep(0.2)
    client_a = FrameSyncClient('127.0.0.1', port, lambda: [(0, default_slot_input())])
    client_b = FrameSyncClient('127.0.0.1', port, lambda: [(1, default_slot_input())])
    (seed, left, right), slots_a = client_a.connect()
    (_, __, __), slots_b = client_b.connect()
    client_a.send_ready()
    client_b.send_ready()
    time.sleep(0.3)
    server_env = server.get_env()
    for _ in range(num_frames):
      server.run_one_frame(timeout_ms=100)
    state_str = server_env.get_state('')
    state_hash = hashlib.sha256(
        state_str if isinstance(state_str, bytes) else state_str.encode()
    ).hexdigest()[:16]
    print('E2E: server ran %d frames, state hash prefix %s' % (num_frames, state_hash))
    client_a.close()
    client_b.close()
  finally:
    server.stop()
  print('E2E test passed.')


if __name__ == '__main__':
  run_e2e_test()
