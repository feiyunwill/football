"""Cookie/epoch UDP server over the common bounded frame-sync protocol owner.

One IPv4 socket and event loop own every peer and engine operation. Unverified
addresses receive at most one 29-byte challenge per 29-byte request. Snapshot
messages stream through bounded reliable fragments without a fragment list.
This protocol requires ResumableFrameSyncUDPClient; native legacy UDP differs.
"""
import asyncio
import socket

from gfootball.frame_sync import udp_session as session
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.server_api import FrameSyncServer
from gfootball.frame_sync.server_runtime import Peer, ServerRuntime
from gfootball.frame_sync.server_state import ServerFailure
from gfootball.frame_sync.udp_state import UDPLimits, UDPState


class UDPServerRuntime(ServerRuntime):
  def __init__(self, settings, limits=None, engine_factory=None, *, udp_limits=None, cookie_limits=None):
    if udp_limits is not None and type(udp_limits) is not UDPLimits:
      raise ValueError('Expected UDPLimits')
    if settings.handshake != 'negotiated':
      raise ValueError('Cookie/epoch UDP requires negotiated sessions')
    super().__init__(settings, limits, engine_factory)
    self.udp_limits = udp_limits or UDPLimits()
    self.cookies = session.CookieAuthority(cookie_limits)
    self._addresses = {}
    self._epochs = {}
    self.udp_counters = dict(cookie_challenges=0, cookie_rejected=0, epoch_dropped=0,
                             invalid_datagrams=0, socket_dropped=0)

  def _count(self, name):
    self.udp_counters[name] = min(0xffffffffffffffff, self.udp_counters[name] + 1)

  async def start(self):
    self._owner()
    if self.loop is not None or self.closed:
      raise RuntimeError('Create a fresh server runtime for a new session')
    self.loop = asyncio.get_running_loop()
    try:
      if self.env is None:
        self.initialize()
      self.listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      self.listener.setblocking(False)
      self.listener.bind((self.settings.listen_host, self.port))
      self.port = self.listener.getsockname()[1]
      self.running = True
      self._accept_task = asyncio.create_task(self._datagrams(), name='football-server-udp')
      self._timer_task = asyncio.create_task(self._maintain(), name='football-server-timer')
    except BaseException as error:
      try:
        await self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('UDP server startup cleanup also failed.')
      raise

  def _sendto(self, packet, address):
    try:
      return self.listener.sendto(packet, address) == len(packet)
    except BlockingIOError:
      return False
    except OSError as error:
      # A delayed ICMP error has no reliable per-peer attribution on this socket.
      if isinstance(error, ConnectionResetError) or getattr(error, 'winerror', None) == 10054:
        self._count('socket_dropped')
        return False
      raise

  def _cookie(self, packet, parsed, address, now):
    kind, epoch, bucket, cookie = parsed
    if kind not in (session.HELLO, session.CONFIRM) or not self.cookies.allow(now):
      self._count('cookie_rejected')
      return
    if kind == session.HELLO:
      self._sendto(self.cookies.challenge(address, epoch, now), address)
      self._count('cookie_challenges')
      return
    if not self.cookies.verify(address, epoch, bucket, cookie, now):
      self._count('cookie_rejected')
      return
    peer = self._addresses.get(address)
    if peer is not None and peer.phase != 'closed':
      if peer.epoch == epoch:
        self._epochs[address, epoch] = max(self._epochs[address, epoch],
                                           (bucket + 2) * self.cookies.limits.period)
        self._sendto(bytes([session.WELCOME]) + packet[1:], address)
      else:
        self._count('epoch_dropped')
      return
    # Never evict an unexpired tombstone to admit a new peer: a replayed CONFIRM
    # must not reset sequence numbers after that connection has closed.
    for key, expiry in tuple(self._epochs.items()):
      active = self._addresses.get(key[0])
      if now >= expiry and not (active is not None and active.phase != 'closed' and active.epoch == key[1]):
        del self._epochs[key]
    key = address, epoch
    if (key in self._epochs or len(self._epochs) >= self.cookies.limits.recent_epochs or
        len(self.peers) >= self.limits.connections or self._next_peer == 0xffffffffffffffff):
      self._count('cookie_rejected')
      self.rejected = min(0xffffffffffffffff, self.rejected + 1)
      return
    peer = Peer(self._next_peer, None, address, self.limits, self.num_slots, now)
    peer.epoch, peer.udp = epoch, UDPState(self.udp_limits, ack_on_delivery=True)
    peer.receive_event = asyncio.Event()
    peer.delivery, peer.delivery_offset = None, 0
    self._next_peer += 1
    self._epochs[key] = (bucket + 2) * self.cookies.limits.period
    self.peers[peer.identity] = peer
    self._addresses[address] = peer
    self.accepted = min(0xffffffffffffffff, self.accepted + 1)
    peer.task = asyncio.create_task(self._read_peer(peer), name='football-server-peer')
    peer.task.add_done_callback(lambda task, peer=peer: self._peer_done(peer, task))
    self._sendto(bytes([session.WELCOME]) + packet[1:], address)

  def _receive_datagram(self, packet, address, now):
    parsed = session.parse_cookie(packet)
    if parsed is not None:
      self._cookie(packet, parsed, address, now)
      return
    peer = self._addresses.get(address)
    if peer is None or peer.phase == 'closed':
      self._count('invalid_datagrams')
      return
    inner = session.unwrap(peer.epoch, packet)
    if inner is None:
      self._count('epoch_dropped')
      return
    try:
      ack = peer.udp.receive(inner, now)
      if ack is not None:
        self._sendto(session.wrap(peer.epoch, ack), address)
      peer.receive_event.set()
    except ClientFailure as error:
      self._drop(peer, error.reason)

  async def _datagrams(self):
    try:
      while self.running:
        # Bounded synchronous nonblocking batches also work on Python 3.9's
        # Windows Proactor loop, without add_reader or detached polling threads.
        for _ in range(64):
          try:
            packet, address = self.listener.recvfrom(session.MAX_PACKET + 1)
          except BlockingIOError:
            break
          except OSError as error:
            if getattr(error, 'winerror', None) in (10040, 10054) or isinstance(error, ConnectionResetError):
              self._count('invalid_datagrams')
              continue
            raise
          self._receive_datagram(packet, address, self.loop.time())
        for peer in tuple(self.peers.values()):
          if peer.phase == 'closed':
            continue
          try:
            for seq, packet in peer.udp.due(self.loop.time()):
              if not self._sendto(session.wrap(peer.epoch, packet), peer.address):
                break
              peer.udp.mark_sent(seq, self.loop.time())
          except ClientFailure as error:
            self._drop(peer, error.reason)
        await asyncio.sleep(.005)
    except asyncio.CancelledError:
      raise
    except Exception:
      self.failure = 'udp_io_error'
      await self.close()

  async def _receive_peer(self, peer, maximum):
    while peer.phase != 'closed':
      if peer.delivery is None:
        peer.delivery = peer.udp.next_delivery()
        peer.delivery_offset = 0
      if peer.delivery is not None:
        start = peer.delivery_offset
        result = peer.delivery[start:start + maximum]
        peer.delivery_offset += len(result)
        if peer.delivery_offset == len(peer.delivery):
          ack = peer.udp.complete_delivery()
          if ack is not None:
            self._sendto(session.wrap(peer.epoch, ack), peer.address)
          peer.delivery = None
        return result
      peer.receive_event.clear()
      await peer.receive_event.wait()
    raise ServerFailure('closed')

  async def _send_peer(self, peer, packet):
    offset = 0
    while offset < len(packet):
      if peer.phase == 'closed':
        raise ServerFailure('closed')
      fragment = packet[offset:offset + session.MAX_PAYLOAD]
      seq = peer.udp.enqueue(fragment, self.loop.time())
      if seq is None:
        await asyncio.sleep(.005)
      else:
        offset += len(fragment)
        # Let receiving and ACK processing advance under large snapshots.
        if seq % 64 == 63:
          await asyncio.sleep(0)

  def _shutdown_peer(self, peer):
    peer.udp.close('closed')
    peer.receive_event.set()

  def _close_peer(self, peer):
    if peer.udp.active is not None:
      peer.udp.complete_delivery()
    peer.delivery = None
    peer.udp.close('closed')
    if self._addresses.get(peer.address) is peer:
      del self._addresses[peer.address]

  async def _close_owned(self, exclude):
    try:
      await super()._close_owned(exclude)
    finally:
      self._addresses.clear()
      self._epochs.clear()

  def stats(self):
    result = super().stats()
    result.update(transport='udp-cookie-epoch-v1', epoch_history=len(self._epochs), **self.udp_counters)
    for key in ('pending_packets', 'pending_bytes', 'receive_packets', 'receive_bytes', 'receipt_bytes'):
      result['udp_' + key] = sum(peer.udp.stats()[key] for peer in self.peers.values())
    return result


class FrameSyncUDPServer(FrameSyncServer):
  """Synchronous facade with the same engine ownership and limits as TCP."""
  def __init__(self, *args, udp_limits=None, cookie_limits=None, **kwargs):
    self._udp_limits, self._cookie_limits = udp_limits, cookie_limits
    super().__init__(*args, **kwargs)

  def _make_runtime(self, values, limits, engine_factory):
    return UDPServerRuntime(values, limits, engine_factory,
                            udp_limits=self._udp_limits, cookie_limits=self._cookie_limits)
