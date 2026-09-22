"""UDP session envelope and stateless return-address validation.

This explicit protocol is separate from legacy native DATA/ACK datagrams.
Every attempt chooses a fresh uint64 epoch. Cookies validate the return path;
they do not encrypt or authenticate the server against an on-path attacker.
"""
from dataclasses import dataclass
import hashlib
import hmac
import math
import secrets
import socket
import struct

HELLO = 0x70
CHALLENGE = 0x71
CONFIRM = 0x72
WELCOME = 0x73
ENVELOPE = 0x74
COOKIE_PACKET = struct.Struct('<BQI16s')
ENVELOPE_HEADER = struct.Struct('<BQ')
MAX_PACKET = 1200
MAX_PAYLOAD = MAX_PACKET - ENVELOPE_HEADER.size - 7


def epoch_value(value):
  if type(value) is not int or not 1 <= value <= 0xffffffffffffffff:
    raise ValueError('UDP epoch must be a nonzero uint64')
  return value


def new_epoch():
  for _ in range(32):
    value = secrets.randbits(64)
    if value:
      return value
  raise RuntimeError('UDP epoch entropy unavailable')


def hello(epoch):
  return COOKIE_PACKET.pack(HELLO, epoch_value(epoch), 0, bytes(16))


def parse_cookie(packet):
  if type(packet) is not bytes or len(packet) != COOKIE_PACKET.size:
    return None
  kind, epoch, bucket, cookie = COOKIE_PACKET.unpack(packet)
  if kind not in (HELLO, CHALLENGE, CONFIRM, WELCOME) or not epoch:
    return None
  if kind == HELLO and (bucket != 0 or cookie != bytes(16)):
    return None
  return kind, epoch, bucket, cookie


def wrap(epoch, packet):
  epoch_value(epoch)
  if type(packet) is not bytes or not 1 <= len(packet) <= MAX_PACKET - ENVELOPE_HEADER.size:
    raise ValueError('Invalid encapsulated UDP datagram')
  return ENVELOPE_HEADER.pack(ENVELOPE, epoch) + packet


def unwrap(epoch, packet):
  if type(packet) is not bytes or not ENVELOPE_HEADER.size < len(packet) <= MAX_PACKET:
    return None
  kind, received_epoch = ENVELOPE_HEADER.unpack_from(packet)
  if kind != ENVELOPE or received_epoch != epoch:
    return None
  return packet[ENVELOPE_HEADER.size:]


@dataclass(frozen=True)
class CookieLimits:
  period: float = 30.0
  requests_per_second: int = 1000
  burst_requests: int = 128
  recent_epochs: int = 1024

  def __post_init__(self):
    if type(self.period) not in (float, int) or not math.isfinite(self.period) or not .1 <= self.period <= 60:
      raise ValueError('Invalid UDP cookie period')
    for name, maximum in (('requests_per_second', 10000), ('burst_requests', 2048), ('recent_epochs', 8192)):
      value = getattr(self, name)
      if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('Invalid UDP cookie limit: ' + name)


class CookieAuthority:
  """Constant-space cookie generation; the server separately bounds admitted epochs."""
  def __init__(self, limits=None):
    if limits is not None and type(limits) is not CookieLimits:
      raise ValueError('Expected CookieLimits')
    self.limits = limits or CookieLimits()
    self._secret = secrets.token_bytes(32)
    self._tokens = float(self.limits.burst_requests)
    self._last = None

  def allow(self, now):
    if self._last is None:
      self._last = now
    self._tokens = min(float(self.limits.burst_requests), self._tokens +
                       max(0, now - self._last) * self.limits.requests_per_second)
    self._last = max(now, self._last)
    if self._tokens < 1:
      return False
    self._tokens -= 1
    return True

  def _cookie(self, address, epoch, bucket):
    ip, port = address
    message = socket.inet_pton(socket.AF_INET, ip) + struct.pack('<HQI', port, epoch, bucket)
    return hmac.new(self._secret, message, hashlib.sha256).digest()[:16]

  def challenge(self, address, epoch, now):
    epoch_value(epoch)
    bucket = int(now / self.limits.period)
    if not 0 <= bucket <= 0xffffffff:
      raise ValueError('UDP cookie clock exhausted')
    return COOKIE_PACKET.pack(CHALLENGE, epoch, bucket, self._cookie(address, epoch, bucket))

  def verify(self, address, epoch, bucket, cookie, now):
    current = int(now / self.limits.period)
    return (bucket in (current, current - 1) and
            hmac.compare_digest(cookie, self._cookie(address, epoch, bucket)))
