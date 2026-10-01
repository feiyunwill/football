"""Two live UDP peers, a native GameEnv replica, and scripted wire faults.

This is an explicit native-only integration test. The fault proxy handles real
datagrams; it never replaces the match reducer or the client protocol.
"""

import heapq
import json
import select
import socket
import struct
import sys
import threading
import time
import unittest

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_udp_resume import ResumableFrameSyncUDPClient
from gfootball.frame_sync.server_runtime import native_engine
from gfootball.frame_sync.server_udp import FrameSyncUDPServer
from gfootball.frame_sync.test_server_budget import until


MEASUREMENTS = {}


class ScriptedRelay:
  """A bounded loopback proxy that delays and faults server DATA datagrams."""

  def __init__(self, port, mode):
    self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.front.bind(('127.0.0.1', 0))
    self.back.connect(('127.0.0.1', port))
    self.port = self.front.getsockname()[1]
    self.mode = mode
    self.stop = threading.Event()
    self.errors = []
    self.seen = set()
    self.dropped = self.duplicated = self.reordered = self.delayed = 0
    self.delivered = 0
    self.out_of_order = 0
    self.delay_ms = set()
    self.actual_delay_ms = []
    self.maximum = 0
    self.thread = threading.Thread(target=self.run, name='football-network-regression-relay')
    self.thread.start()

  def run(self):
    address = None
    queue = []
    held = None
    order = 0
    delivered_keys = set()
    highest_delivered = {}

    def schedule(packet, now, delay):
      nonlocal order
      order += 1
      heapq.heappush(queue, (now + delay, order, now, packet))

    try:
      while not self.stop.is_set():
        now = time.monotonic()
        while queue and queue[0][0] <= now:
          _, _, received, packet = heapq.heappop(queue)
          self.front.sendto(packet, address)
          self.delivered += 1
          self.actual_delay_ms.append((now - received) * 1000)
          epoch = struct.unpack_from('<Q', packet, 1)[0]
          seq = struct.unpack_from('<I', packet, 10)[0]
          key = epoch, seq
          if key not in delivered_keys:
            if seq < highest_delivered.get(epoch, -1):
              self.out_of_order += 1
            highest_delivered[epoch] = max(seq, highest_delivered.get(epoch, -1))
            delivered_keys.add(key)
        if len(queue) > 128:
          raise AssertionError('Fault proxy queue bound exceeded')
        timeout = min(.002, max(0, queue[0][0] - now)) if queue else .002
        readable, _, _ = select.select([self.front, self.back], [], [], timeout)
        for sock in readable:
          try:
            packet, source = sock.recvfrom(1201)
          except ConnectionResetError:
            continue
          self.maximum = max(self.maximum, len(packet))
          if len(packet) > 1200:
            raise AssertionError('Oversized UDP datagram')
          if sock is self.front:
            address = source
            self.back.send(packet)
            continue
          if address is None:
            continue
          # Epoch-tagged UDP DATA; handshake and ACKs are left untouched.
          is_data = len(packet) > 16 and packet[0] == 0x74 and packet[9] == 0
          if not is_data:
            self.front.sendto(packet, address)
            continue
          now = time.monotonic()
          epoch = struct.unpack_from('<Q', packet, 1)[0]
          seq = struct.unpack_from('<I', packet, 10)[0]
          key = epoch, seq
          first = key not in self.seen
          self.seen.add(key)
          if len(self.seen) > 4096:
            raise AssertionError('Fault proxy sequence bound exceeded')
          if self.mode == 'faults' and first and seq % 17 == 3:
            self.dropped += 1
            continue
          delay_ms = (6, 14)[seq % 2] if self.mode == 'latency' else (4, 10)[seq % 2]
          self.delay_ms.add(delay_ms)
          self.delayed += 1
          if self.mode == 'faults' and first and seq % 23 == 4 and held is None:
            held = packet, now
            continue
          schedule(packet, now, delay_ms / 1000)
          if self.mode == 'faults' and first and seq % 19 == 2:
            schedule(packet, now, delay_ms / 1000)
            self.duplicated += 1
          if held is not None:
            previous, received = held
            schedule(previous, received, .025)
            self.reordered += 1
            held = None
        if held is not None and time.monotonic() - held[1] >= .025:
          packet, received = held
          schedule(packet, received, .025)
          held = None
    except BaseException as error:
      self.errors.append(error)
    finally:
      self.front.close()
      self.back.close()

  def close(self):
    self.stop.set()
    self.thread.join(2)
    if self.thread.is_alive():
      raise AssertionError('Fault proxy thread leaked')
    if self.errors:
      raise self.errors[0]


class NetworkRegressionNativeTest(unittest.TestCase):
  def test_two_peers_variable_input_per_frame_native_hash_fault_matrix(self):
    matrix = {}
    for mode in ('baseline', 'latency', 'faults'):
      server = FrameSyncUDPServer(listen_host='127.0.0.1', listen_port=0,
                                  scenario_name='tests.11_vs_11_deterministic',
                                  left_agents=1, right_agents=1, state_hash_interval=1)
      clients = []
      relay = replica = None
      digests = []
      signatures = []
      try:
        server.start()
        if mode != 'baseline':
          relay = ScriptedRelay(server.listen_port, mode)
        replica = native_engine(server._runtime.settings)
        clients = [ResumableFrameSyncUDPClient('127.0.0.1', server.listen_port),
                   ResumableFrameSyncUDPClient('127.0.0.1', relay.port if relay else server.listen_port)]
        for index, client in enumerate(clients):
          self.assertEqual(client.connect(), ((42, 1, 1), [index]))
          client.send_ready()
        until(server.all_clients_ready)
        # Send two future inputs before consuming authority. This creates a
        # real sequence gap for the relay to reorder, rather than merely
        # delaying the only packet in a strict request/response cycle.
        for batch in range(0, 40, 2):
          expected_batch = []
          for frame in (batch, batch + 1):
            expected = [wire.SlotInput(.25 + .05 * (frame % 4), .1 * (frame % 3), frame % 2),
                        wire.SlotInput(-.3 - .05 * (frame % 4), -.1 * (frame % 3), (frame + 1) % 2)]
            packed = [wire.pack_slot_input(value) for value in expected]
            signatures.append(tuple(packed))
            expected_batch.append(packed)
            for index, client in enumerate(clients):
              client.send_frame_entries(frame, [(index, expected[index])])
          authoritative = []
          for offset, packed in enumerate(expected_batch):
            frame = batch + offset
            number, actual = server.run_one_frame(timeout_ms=1000)
            self.assertEqual(number, frame)
            self.assertEqual([wire.pack_slot_input(value) for value in actual], packed)
            replica.step_with_input(b''.join(wire.pack_slot_input(value) for value in actual))
            digest = replica.get_state_digest()
            self.assertNotEqual(digest, 0)
            digests.append(digest)
            authoritative.append((frame, actual, digest))
          for frame, actual, digest in authoritative:
            for client in clients:
              until(client.has_authoritative_frame)
              self.assertEqual(client.pop_authoritative_frame(), (frame, actual))
              until(lambda client=client: frame in client._buffers.hashes)
              self.assertTrue(client.check_state_hash(frame, digest))
        self.assertGreaterEqual(len(set(signatures)), 4)
        self.assertGreaterEqual(len(set(digests)), 2)
        record = {'frames': 40, 'peer_hash_checks': 80,
                  'unique_inputs': len(set(signatures)), 'unique_digests': len(set(digests))}
        if relay:
          record.update(dropped=relay.dropped, duplicated=relay.duplicated,
                        reordered=relay.reordered, out_of_order=relay.out_of_order,
                        delayed=relay.delayed,
                        delay_ms=sorted(relay.delay_ms), delivered=relay.delivered,
                        maximum_datagram=relay.maximum)
          self.assertGreater(relay.delayed, 0)
          self.assertEqual(len(relay.delay_ms), 2)
          self.assertTrue(relay.actual_delay_ms)
          self.assertGreaterEqual(min(relay.actual_delay_ms), min(relay.delay_ms) - 1)
          if mode == 'faults':
            self.assertGreater(relay.dropped, 0)
            self.assertGreater(relay.duplicated, 0)
            self.assertGreater(relay.reordered, 0)
            self.assertGreater(relay.out_of_order, 0)
        matrix[mode] = record
      finally:
        for client in clients:
          client.close()
        if replica:
          replica.close()
        if relay:
          relay.close()
        server.stop()
    MEASUREMENTS['matrix'] = matrix


if __name__ == '__main__':
  result = unittest.main(exit=False).result
  if not result.wasSuccessful():
    sys.exit(1)
  print('NETWORK_MATRIX=' + json.dumps(MEASUREMENTS['matrix'], sort_keys=True))
