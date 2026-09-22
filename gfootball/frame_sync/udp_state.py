# Copyright 2026 Google LLC
# 2026-09-10: bounded, ordered reliable UDP state, independent of socket ownership.
"""Legacy C++ DATA/ACK wire format with strict local delivery and resource limits.

Payload budgets charge immutable bytes including their Python object header.
Container metadata is count bounded separately. OS buffers, caller-owned values
and short-lived encoding temporaries are outside these retained-byte budgets.
The owner serializes calls and uses one monotonic clock (seconds).
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import math
import struct
import sys

from gfootball.frame_sync.client_buffers import ClientFailure

DATA = 0
ACK = 255
HEADER_SIZE = 7
ACK_SIZE = 5
MAX_PACKET = 1200
MAX_PAYLOAD = MAX_PACKET - HEADER_SIZE
MASK = 0xffffffff


@dataclass(frozen=True)
class UDPLimits:
  pending_packets: int = 256
  pending_bytes: int = 256 * 1024
  receive_packets: int = 256
  receive_bytes: int = 256 * 1024
  receipt_history: int = 256
  max_retries: int = 5
  gap_timeout: float = 2.0
  delivery_timeout: float = 6.0
  packets_per_second: int = 2000
  burst_packets: int = 512

  def __post_init__(self):
    for name, low, high in (
        ('pending_packets', 1, 1024), ('pending_bytes', 64, 16 * 1024 * 1024),
        ('receive_packets', 1, 1024), ('receive_bytes', 64, 16 * 1024 * 1024),
        ('receipt_history', 1, 1024), ('max_retries', 0, 10),
        ('packets_per_second', 1, 10000), ('burst_packets', 1, 2048)):
      value = getattr(self, name)
      if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid UDP limit: ' + name)
    for name in ('gap_timeout', 'delivery_timeout'):
      value = getattr(self, name)
      if type(value) not in (float, int) or not math.isfinite(value) or not .01 <= value <= 30:
        raise ValueError('Invalid UDP deadline: ' + name)


class UDPState:
  """A terminal failure clears queued work; active delivery stays charged.

  enqueue returns None for recoverable capacity pressure without consuming a
  sequence. Incoming bytes are ACKed only after validation and admission. The
  caller must complete_delivery in finally after processing each returned value.
  """
  # 2026-09-10: epoch streams ACK delivery, retaining sender pressure across gaps.
  # def __init__(self, limits=None):
  def __init__(self, limits=None, *, ack_on_delivery=False):
    if type(ack_on_delivery) is not bool:
      raise ValueError('ack_on_delivery must be bool')
    self.ack_on_delivery = ack_on_delivery
    if limits is not None and not isinstance(limits, UDPLimits):
      raise ValueError('Expected UDPLimits')
    self.limits = limits or UDPLimits()
    self.next_send = 0
    self.next_receive = 0
    self.pending = OrderedDict()
    self.pending_bytes = 0
    self.receiving = {}
    self.receive_bytes = 0
    self.receipts = OrderedDict()
    self.active = None
    self.rtt = deque(maxlen=32)
    self.failure = None
    self._tokens = float(self.limits.burst_packets)
    self._token_time = None
    self.counters = dict(invalid=0, duplicates=0, rate_dropped=0, acknowledged=0,
                         retransmitted=0, delivered=0, capacity_rejected=0)

  def count(self, name):
    self.counters[name] = min(0xffffffffffffffff, self.counters[name] + 1)

  def close(self, reason='closed'):
    if self.failure is None:
      self.failure = reason
    self.pending.clear()
    self.pending_bytes = 0
    active = self.receiving.get(self.active) if self.active is not None else None
    self.receiving.clear()
    self.receive_bytes = 0
    if active is not None:
      self.receiving[self.active] = active
      self.receive_bytes = sys.getsizeof(active[0])
    self.receipts.clear()
    self.rtt.clear()

  def fail(self, reason):
    self.close(reason)
    raise ClientFailure(reason)

  def _open(self):
    if self.failure is not None:
      raise ClientFailure(self.failure)

  def enqueue(self, payload, now):
    self._open()
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_PAYLOAD:
      raise ValueError('UDP payload must be 1..1193 immutable bytes')
    retained = sys.getsizeof(payload) + HEADER_SIZE
    if (len(self.pending) >= self.limits.pending_packets or
        retained > self.limits.pending_bytes - self.pending_bytes):
      self.count('capacity_rejected')
      return None
    seq = self.next_send
    if seq in self.pending:
      self.fail('udp_sequence_exhausted')
    packet = struct.pack('<BIH', DATA, seq, len(payload)) + payload
    # packet, admission time, most recent successful send time, retransmits
    self.pending[seq] = (packet, now, None, 0)
    self.pending_bytes += sys.getsizeof(packet)
    self.next_send = (seq + 1) & MASK
    return seq

  @property
  def rto(self):
    if not self.rtt:
      return .140
    mean = sum(self.rtt) / len(self.rtt)
    deviation = sum(abs(value - mean) for value in self.rtt) / len(self.rtt)
    return max(.05, min(1.0, mean + 4 * deviation))

  def due(self, now, count=64):
    self._open()
    self.check_deadlines(now)
    result = []
    rto = self.rto
    for seq, (packet, admitted, sent, retries) in self.pending.items():
      if sent is None or now - sent >= rto:
        if sent is not None and retries >= self.limits.max_retries:
          self.fail('udp_retry_exhausted')
        result.append((seq, packet))
        if len(result) >= count:
          break
    return result

  def mark_sent(self, seq, now):
    packet, admitted, sent, retries = self.pending[seq]
    if sent is not None:
      retries += 1
      self.count('retransmitted')
    self.pending[seq] = (packet, admitted, now, retries)

  def check_deadlines(self, now):
    self._open()
    if self.pending and now - next(iter(self.pending.values()))[1] >= self.limits.delivery_timeout:
      self.fail('udp_delivery_timeout')
    # Arrival timestamps survive duplicates and changing gaps. The in-order
    # active callback is not a network gap and cannot be forcibly interrupted.
    if self.receiving and self.next_receive not in self.receiving:
      if now - min(value[1] for value in self.receiving.values()) >= self.limits.gap_timeout:
        self.fail('udp_gap_timeout')

  def receive(self, packet, now):
    self._open()
    if self._token_time is None:
      self._token_time = now
    self._tokens = min(float(self.limits.burst_packets),
                       self._tokens + max(0, now - self._token_time) * self.limits.packets_per_second)
    self._token_time = max(now, self._token_time)
    if self._tokens < 1:
      self.count('rate_dropped')
      return None
    self._tokens -= 1
    if type(packet) is not bytes or not packet or len(packet) > MAX_PACKET:
      self.count('invalid')
      return None
    if packet[0] == ACK and len(packet) == ACK_SIZE:
      seq = struct.unpack_from('<I', packet, 1)[0]
      entry = self.pending.get(seq)
      if entry is not None and entry[2] is not None:
        del self.pending[seq]
        self.pending_bytes -= sys.getsizeof(entry[0])
        if entry[3] == 0 and now >= entry[2]:
          self.rtt.append(min(60.0, now - entry[2]))
        self.count('acknowledged')
      return None
    if packet[0] != DATA or len(packet) < HEADER_SIZE:
      self.count('invalid')
      return None
    _, seq, length = struct.unpack_from('<BIH', packet)
    if length == 0 or len(packet) != HEADER_SIZE + length:
      self.count('invalid')
      return None
    distance = (seq - self.next_receive) & MASK
    payload = packet[HEADER_SIZE:]
    # 2026-09-10: exactly half the uint32 space has no defined sequence ordering.
    # if distance >= 0x80000000:
    if distance == 0x80000000:
      self.fail('udp_sequence_window')
    if distance > 0x80000000:
      previous = self.receipts.get(seq)
      if previous is not None and previous != hashlib.blake2s(payload, digest_size=16).digest():
        self.fail('udp_conflicting_duplicate')
      self.count('duplicates')
    elif seq in self.receiving:
      if self.receiving[seq][0] != payload:
        self.fail('udp_conflicting_duplicate')
      self.count('duplicates')
    else:
      if distance >= self.limits.receive_packets:
        self.fail('udp_sequence_window')
      retained = sys.getsizeof(payload)
      if (len(self.receiving) >= self.limits.receive_packets or
          retained > self.limits.receive_bytes - self.receive_bytes):
        self.fail('udp_receive_capacity')
      self.receiving[seq] = (payload, now)
      self.receive_bytes += retained
    # 2026-09-10: ACKing queued future fragments let the sender overrun the
    # receiver while waiting for a missing fragment in a large snapshot.
    # return struct.pack('<BI', ACK, seq)
    if not self.ack_on_delivery or distance > 0x80000000:
      return struct.pack('<BI', ACK, seq)
    return None

  def next_delivery(self):
    self._open()
    if self.active is not None:
      return None
    entry = self.receiving.get(self.next_receive)
    if entry is None:
      return None
    self.active = self.next_receive
    return entry[0]

  def complete_delivery(self):
    if self.active is None:
      raise RuntimeError('No active UDP delivery')
    seq = self.active
    payload, _ = self.receiving.pop(seq)
    self.receive_bytes -= sys.getsizeof(payload)
    self.active = None
    if self.failure is None:
      self.receipts[seq] = hashlib.blake2s(payload, digest_size=16).digest()
      if len(self.receipts) > self.limits.receipt_history:
        self.receipts.popitem(last=False)
      self.next_receive = (seq + 1) & MASK
      self.count('delivered')
      if self.ack_on_delivery:
        return struct.pack('<BI', ACK, seq)

  def stats(self):
    return dict(pending_packets=len(self.pending), pending_bytes=self.pending_bytes,
                receive_packets=len(self.receiving), receive_bytes=self.receive_bytes,
                active_delivery=self.active is not None, receipt_history=len(self.receipts),
                receipt_bytes=sum(sys.getsizeof(value) for value in self.receipts.values()),
                rtt_samples=len(self.rtt), rto_ms=self.rto * 1000,
                failure=self.failure, **self.counters)
