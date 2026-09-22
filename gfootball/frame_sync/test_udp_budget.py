# Copyright 2026 Google LLC
"""State contracts plus actual loopback UDP delivery; no native engine substitute."""
from dataclasses import replace
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest

from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.udp_state import UDPState, UDPLimits, MAX_PACKET, MAX_PAYLOAD
from gfootball.frame_sync.udp_transport import ReliableUDPClient


def data_packet(seq, payload):
  return struct.pack('<BIH', 0, seq, len(payload)) + payload


def ack_packet(seq):
  return struct.pack('<BI', 255, seq)


def drain(state):
  result = []
  while True:
    value = state.next_delivery()
    if value is None:
      return result
    result.append(value)
    state.complete_delivery()


class UDPStateTest(unittest.TestCase):
  def test_limits_reject_invalid_types_bounds_and_nonfinite(self):
    for name in UDPLimits.__dataclass_fields__:
      for value in (True, None, '1', -1, float('inf'), float('nan')):
        with self.subTest(name=name, value=value), self.assertRaises(ValueError):
          UDPLimits(**{name: value})
    with self.assertRaises(ValueError):
      UDPState(False)

  def test_wire_known_bytes_and_cpp_constants(self):
    state = UDPState()
    state.enqueue(b'ABC', 0)
    self.assertEqual(state.due(0), [(0, b'\x00\x00\x00\x00\x00\x03\x00ABC')])
    self.assertEqual(state.receive(data_packet(0, b'X'), 0), b'\xff\0\0\0\0')
    # 2026-09-10: Windows locale is not the repository's UTF-8 encoding.
    # cpp = (Path(__file__).resolve().parents[2] / 'engine/src/frame_sync/reliable_udp.hpp').read_text()
    cpp = (Path(__file__).resolve().parents[2] / 'engine/src/frame_sync/reliable_udp.hpp').read_text(encoding='utf-8')
    self.assertRegex(cpp, r'kReliableUDP_MaxPacketSize\s*=\s*1200')
    self.assertRegex(cpp, r'kReliableUDP_MaxRetries\s*=\s*5')
    self.assertEqual((MAX_PACKET, MAX_PAYLOAD), (1200, 1193))

  def test_send_count_backpressure_ack_refund_no_sequence_consumption(self):
    state = UDPState(UDPLimits(pending_packets=2))
    self.assertEqual(state.enqueue(b'a', 0), 0)
    self.assertEqual(state.enqueue(b'b', 0), 1)
    retained = state.pending_bytes
    self.assertIsNone(state.enqueue(b'c', 0))
    self.assertEqual((state.next_send, state.pending_bytes), (2, retained))
    state.mark_sent(0, 0)
    state.receive(ack_packet(0), .01)
    self.assertEqual(state.enqueue(b'c', .01), 2)
    self.assertEqual(state.pending_bytes, retained)
    state.close()
    self.assertEqual((len(state.pending), state.pending_bytes), (0, 0))

  def test_send_actual_byte_budget_and_max_datagram(self):
    state = UDPState(UDPLimits(pending_bytes=1233))
    self.assertEqual(state.enqueue(b'x' * MAX_PAYLOAD, 0), 0)
    self.assertEqual(state.pending_bytes, sys.getsizeof(state.pending[0][0]))
    self.assertIsNone(state.enqueue(b'x', 0))
    for payload in (b'', b'x' * 1194, bytearray(b'x'), 'x'):
      with self.assertRaises(ValueError):
        state.enqueue(payload, 0)
    self.assertEqual(state.next_send, 1)

  def test_untransmitted_ack_unknown_ack_and_trailing_ack_cannot_refund(self):
    state = UDPState()
    state.enqueue(b'x', 0)
    state.receive(ack_packet(0), .01)
    state.mark_sent(0, .02)
    state.receive(ack_packet(100), .03)
    state.receive(ack_packet(0) + b'x', .04)
    self.assertEqual(len(state.pending), 1)
    state.receive(ack_packet(0), .05)
    self.assertEqual(len(state.pending), 0)

  def test_rtt_bounds_karn_and_no_retransmission_before_deadline(self):
    state = UDPState()
    for i in range(40):
      state.enqueue(b'x', i)
      state.mark_sent(i, i)
      self.assertEqual(state.due(i + .01), [])
      state.receive(ack_packet(i), i + .02)
    self.assertEqual(len(state.rtt), 32)
    self.assertEqual(state.rto, .05)
    state.enqueue(b'x', 50)
    state.mark_sent(40, 50)
    self.assertEqual(len(state.due(50.06)), 1)
    state.mark_sent(40, 50.06)
    old = list(state.rtt)
    state.receive(ack_packet(40), 51)
    self.assertEqual(list(state.rtt), old)

  def test_retry_exhaustion_closes_whole_stream(self):
    state = UDPState(UDPLimits(max_retries=1))
    state.enqueue(b'a', 0)
    state.enqueue(b'b', 0)
    state.mark_sent(0, 0)
    state.mark_sent(0, .2)
    with self.assertRaisesRegex(ClientFailure, 'udp_retry_exhausted'):
      state.due(.4)
    self.assertEqual((state.pending_bytes, len(state.pending)), (0, 0))
    with self.assertRaises(ClientFailure):
      state.enqueue(b'c', 1)

  def test_unsent_write_deadline_is_absolute(self):
    state = UDPState(UDPLimits(delivery_timeout=.1))
    state.enqueue(b'a', 0)
    self.assertEqual(len(state.due(.09)), 1)
    with self.assertRaisesRegex(ClientFailure, 'udp_delivery_timeout'):
      state.due(.1)

  def test_out_of_order_duplicates_deliver_exactly_once(self):
    state = UDPState()
    for seq in (2, 2, 1, 1):
      self.assertEqual(state.receive(data_packet(seq, bytes([seq + 65])), 0), ack_packet(seq))
      self.assertEqual(drain(state), [])
    state.receive(data_packet(0, b'A'), 0)
    self.assertEqual(drain(state), [b'A', b'B', b'C'])
    for seq in range(3):
      state.receive(data_packet(seq, bytes([seq + 65])), .01)
    self.assertEqual(drain(state), [])
    self.assertEqual((state.receive_bytes, state.stats()['duplicates']), (0, 5))

  def test_conflicting_buffered_and_delivered_duplicates_are_terminal(self):
    for delivered in (False, True):
      state = UDPState()
      state.receive(data_packet(0, b'a'), 0)
      if delivered:
        drain(state)
      with self.assertRaisesRegex(ClientFailure, 'udp_conflicting_duplicate'):
        state.receive(data_packet(0, b'b'), .01)
      self.assertEqual(state.receive_bytes, 0)

  def test_history_eviction_does_not_redeliver_old_packets(self):
    state = UDPState(UDPLimits(receipt_history=2))
    for i in range(10):
      state.receive(data_packet(i, b'x'), i)
      self.assertEqual(drain(state), [b'x'])
    self.assertEqual(state.stats()['receipt_history'], 2)
    self.assertEqual(state.receive(data_packet(0, b'x'), 11), ack_packet(0))
    self.assertEqual(drain(state), [])

  def test_sequence_wrap_order_ack_and_pending_collision(self):
    state = UDPState()
    state.next_send = state.next_receive = 0xffffffff
    self.assertEqual(state.enqueue(b'z', 0), 0xffffffff)
    self.assertEqual(state.enqueue(b'a', 0), 0)
    state.receive(data_packet(0, b'a'), 0)
    self.assertEqual(drain(state), [])
    state.receive(data_packet(0xffffffff, b'z'), 0)
    self.assertEqual(drain(state), [b'z', b'a'])
    self.assertEqual(state.next_receive, 1)
    state.mark_sent(0xffffffff, 0)
    state.receive(ack_packet(0xffffffff), .01)
    self.assertEqual(list(state.pending), [0])
    state.next_send = 0
    with self.assertRaisesRegex(ClientFailure, 'udp_sequence_exhausted'):
      state.enqueue(b'collision', .02)

  def test_gap_deadline_is_not_extended_by_duplicates_or_ack(self):
    state = UDPState(UDPLimits(gap_timeout=.1))
    state.receive(data_packet(1, b'b'), 0)
    state.receive(data_packet(1, b'b'), .09)
    state.receive(ack_packet(0), .099)
    with self.assertRaisesRegex(ClientFailure, 'udp_gap_timeout'):
      state.check_deadlines(.1)
    self.assertEqual(state.receive_bytes, 0)

  def test_remaining_gap_preserves_original_arrival_time(self):
    state = UDPState(UDPLimits(gap_timeout=.1))
    state.receive(data_packet(3, b'd'), 0)
    state.receive(data_packet(0, b'a'), .05)
    self.assertEqual(drain(state), [b'a'])
    with self.assertRaisesRegex(ClientFailure, 'udp_gap_timeout'):
      state.check_deadlines(.1)

  def test_capacity_and_window_reject_without_ack(self):
    state = UDPState(UDPLimits(receive_bytes=64))
    with self.assertRaisesRegex(ClientFailure, 'udp_receive_capacity'):
      state.receive(data_packet(0, b'x' * 32), 0)
    self.assertEqual(state.receive_bytes, 0)
    state = UDPState(UDPLimits(receive_packets=2))
    with self.assertRaisesRegex(ClientFailure, 'udp_sequence_window'):
      state.receive(data_packet(2, b'x'), 0)

  def test_active_payload_stays_charged_through_close_and_refunds_finally(self):
    state = UDPState()
    state.receive(data_packet(0, b'a'), 0)
    state.receive(data_packet(1, b'b'), 0)
    self.assertEqual(state.next_delivery(), b'a')
    self.assertIsNone(state.next_delivery())
    state.close()
    self.assertEqual((state.receive_bytes, len(state.receiving)), (sys.getsizeof(b'a'), 1))
    state.complete_delivery()
    self.assertEqual((state.receive_bytes, len(state.receiving)), (0, 0))

  def test_malformed_exact_length_no_ack_or_state_allocation(self):
    state = UDPState()
    invalid = [b'', b'\0', b'\xff', b'\1xxxx', data_packet(0, b''),
               data_packet(0, b'x')[:-1], data_packet(0, b'x') + b'y',
               data_packet(0, b'x' * 1194)]
    for packet in invalid:
      self.assertIsNone(state.receive(packet, 0))
    self.assertEqual(state.stats()['invalid'], len(invalid))
    self.assertEqual((state.next_receive, state.receive_bytes, len(state.receipts)), (0, 0, 0))

  def test_receive_rate_limit_and_saturating_counters(self):
    state = UDPState(UDPLimits(burst_packets=1, packets_per_second=10))
    state.receive(b'', 0)
    self.assertIsNone(state.receive(data_packet(0, b'a'), .09))
    self.assertEqual(state.receive(data_packet(0, b'a'), .1), ack_packet(0))
    self.assertEqual(drain(state), [b'a'])
    state.counters['duplicates'] = 0xffffffffffffffff
    state.receive(data_packet(0, b'a'), .2)
    self.assertEqual(state.counters['duplicates'], 0xffffffffffffffff)


class UDPTransportTest(unittest.TestCase):
  def setUp(self):
    self.sockets = []
    self.channels = []

  def tearDown(self):
    for channel in self.channels:
      channel.stop()
    for sock in self.sockets:
      sock.close()

  def pair(self, callback, **kwargs):
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
    for sock in sockets:
      self.sockets.append(sock)
      sock.bind(('127.0.0.1', 0))
      sock.setblocking(False)
    channel = ReliableUDPClient(sockets[0], sockets[1].getsockname(), callback, **kwargs)
    self.channels.append(channel)
    return channel, sockets

  def test_constructor_requires_borrowed_nonblocking_numeric_endpoint(self):
    channel, (sock, peer) = self.pair(lambda _: None)
    for address in (('localhost', 1), ('127.0.0.1', 0), ('127.0.0.1', True)):
      with self.assertRaises(ValueError):
        ReliableUDPClient(sock, address, lambda _: None)
    sock.setblocking(True)
    with self.assertRaises(ValueError):
      ReliableUDPClient(sock, peer.getsockname(), lambda _: None)

  def test_real_socket_send_ack_and_borrowed_socket_after_stop(self):
    channel, (sock, peer) = self.pair(lambda _: None)
    channel.start(background=False)
    self.assertTrue(channel.send(b'test'))
    peer.settimeout(.5)
    packet, remote = peer.recvfrom(1201)
    self.assertEqual(packet, data_packet(0, b'test'))
    peer.sendto(ack_packet(0), remote)
    deadline = time.monotonic() + .5
    while channel.stats()['pending_packets'] and time.monotonic() < deadline:
      try:
        packet, address = sock.recvfrom(1201)
        channel.handle_received(packet, address)
      except BlockingIOError:
        time.sleep(.001)
    self.assertEqual(channel.stats()['pending_bytes'], 0)
    channel.stop()
    self.assertGreaterEqual(sock.fileno(), 0)
    self.assertFalse(channel.send(b'closed'))
    with self.assertRaises(ClientFailure):
      channel.start()

  def test_thread_start_idempotence_retry_exhaustion_and_join(self):
    channel, _ = self.pair(lambda _: None, limits=UDPLimits(max_retries=0))
    channel.start()
    worker = channel._retransmit_thread
    channel.start()
    self.assertIs(channel._retransmit_thread, worker)
    self.assertFalse(worker.daemon)
    channel.send(b'no ack')
    worker.join(1)
    self.assertFalse(worker.is_alive())
    self.assertEqual(channel.failure_reason, 'udp_retry_exhausted')
    self.assertEqual(channel.stats()['pending_packets'], 0)

  def test_callback_reentry_and_stop_keep_active_charged(self):
    delivered = []
    def callback(payload):
      delivered.append(payload)
      self.assertTrue(channel.handle_received(data_packet(0, payload)))
      self.assertTrue(channel.send(b'reply'))
      channel.stop()
      self.assertEqual(channel.stats()['receive_bytes'], sys.getsizeof(payload))
    channel, _ = self.pair(callback)
    channel.start(background=False)
    self.assertFalse(channel.handle_received(data_packet(0, b'one')))
    self.assertEqual(delivered, [b'one'])
    self.assertEqual(channel.stats()['receive_bytes'], 0)

  def test_callback_failure_is_terminal_and_refunds(self):
    def callback(_):
      raise ValueError('application failure')
    channel, _ = self.pair(callback)
    channel.start(background=False)
    with self.assertRaisesRegex(ValueError, 'application failure'):
      channel.handle_received(data_packet(0, b'a'))
    self.assertEqual(channel.failure_reason, 'udp_callback_failed')
    self.assertEqual(channel.stats()['receive_bytes'], 0)

  def test_source_filter_does_not_ack_or_deliver_foreign_data(self):
    delivered = []
    channel, (_, peer) = self.pair(delivered.append)
    channel.start(background=False)
    self.assertTrue(channel.handle_received(data_packet(0, b'a'), ('127.0.0.2', 1)))
    self.assertEqual(delivered, [])
    with self.assertRaises(BlockingIOError):
      peer.recvfrom(1201)

  def test_hard_socket_send_failure_is_terminal(self):
    channel, (sock, _) = self.pair(lambda _: None)
    channel.start(background=False)
    channel.send(b'pending')
    sock.close()
    self.assertFalse(channel.send(b'failure'))
    self.assertEqual(channel.failure_reason, 'udp_io_error')
    self.assertEqual(channel.stats()['pending_bytes'], 0)

  def test_concurrent_receivers_serialize_in_order_callback(self):
    entered, release = threading.Event(), threading.Event()
    delivered = []
    def callback(value):
      if value == b'a':
        entered.set()
        self.assertTrue(release.wait(1))
      delivered.append(value)
    channel, _ = self.pair(callback)
    channel.start(background=False)
    first = threading.Thread(target=channel.handle_received, args=(data_packet(0, b'a'),), name='football-udp-test-delivery')
    second = threading.Thread(target=channel.handle_received, args=(data_packet(1, b'b'),), name='football-udp-test-delivery')
    try:
      first.start()
      self.assertTrue(entered.wait(1))
      second.start()
      self.assertEqual(channel.stats()['receive_bytes'], sys.getsizeof(b'a'))
    finally:
      release.set()
      first.join(1)
      if second.ident is not None:
        second.join(1)
    self.assertEqual(delivered, [b'a', b'b'])
    self.assertFalse(first.is_alive() or second.is_alive())

  def test_real_bidirectional_loss_duplicate_reorder_and_complete_refund(self):
    left_values, right_values = [], []
    left, (a, b) = self.pair(left_values.append)
    right = ReliableUDPClient(b, a.getsockname(), right_values.append)
    self.channels.append(right)
    left.start(background=False)
    right.start(background=False)
    for i in range(40):
      self.assertTrue(left.send(struct.pack('<I', i)))
      self.assertTrue(right.send(struct.pack('<I', i + 100)))
    dropped = set()
    reordered = 0
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
      for index, (sock, channel) in enumerate(((a, left), (b, right))):
        batch = []
        while True:
          try:
            packet, address = sock.recvfrom(1201)
          except BlockingIOError:
            break
          seq = struct.unpack_from('<I', packet, 1)[0]
          key = index, packet[0], seq
          if seq % 7 == 0 and key not in dropped:
            dropped.add(key)  # Lose first copies of DATA and ACK both ways.
            continue
          batch.append((packet, address))
        reordered += len(batch) > 1
        for packet, address in reversed(batch):
          channel.handle_received(packet, address)
          channel.handle_received(packet, address)
        self.assertTrue(channel.poll(), channel.failure_reason)
      if (len(left_values) == len(right_values) == 40 and
          not left.stats()['pending_packets'] and not right.stats()['pending_packets']):
        break
      time.sleep(.002)
    self.assertEqual(left_values, [struct.pack('<I', i + 100) for i in range(40)])
    self.assertEqual(right_values, [struct.pack('<I', i) for i in range(40)])
    self.assertGreater(len(dropped), 0)
    self.assertGreater(reordered, 0)
    for channel in (left, right):
      self.assertGreater(channel.stats()['retransmitted'], 0)
      self.assertGreater(channel.stats()['duplicates'], 0)
      self.assertEqual((channel.stats()['pending_bytes'], channel.stats()['receive_bytes']), (0, 0))


if __name__ == '__main__':
  unittest.main()
