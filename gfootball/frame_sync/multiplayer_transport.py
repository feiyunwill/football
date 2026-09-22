# 2026-09-10: versioned cadence replaces the implicit v4 rate agreement.
# """Explicit match-v4 TCP origin and resume on the existing bounded IO owners."""
# 2026-09-10: v6 adds authoritative pause barriers and epoch-scoped input.
# """Explicit match-v5 cadence, origin and resume on bounded IO owners."""
"""Match-v6 cadence, origin, control barriers and recovery on bounded IO owners."""
from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
import asyncio
import itertools
# 2026-09-10: exact negotiated rate validation lives in MatchCadence.
# import math
import time
import struct
from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.client_buffers import ClientFailure
from gfootball.frame_sync.client_reconnect import ReconnectingFrameSyncClient
from gfootball.frame_sync.client_tcp import FrameSyncClient
from gfootball.frame_sync.match_archive import engine_digest, settings_data
# 2026-09-10: explicit resume version prevents interpreting v4 as legacy raw state.
# from gfootball.frame_sync.match_bootstrap import MATCH_VERSION, MatchBuffers, MatchResumeLimits, pack_origin, unpack_origin
from gfootball.frame_sync.match_bootstrap import (
    MATCH_VERSION, MatchBuffers, MatchResumeLimits, pack_origin, unpack_origin,
    pack_match_reconnect, unpack_match_reconnect,
)
from gfootball.frame_sync.match_identity import native_match_engine, require_identity
from gfootball.frame_sync.match_bootstrap import pack_match_ready, unpack_match_ready
from gfootball.frame_sync.match_cadence import MATCH_CADENCE
from gfootball.frame_sync.server_api import FrameSyncServer
from gfootball.frame_sync.server_runtime import ServerRuntime
from gfootball.frame_sync.server_state import ServerFailure
from gfootball.frame_sync.match_lifecycle import match_finished
from gfootball.frame_sync.match_control import (
    MatchControl, RUNNING, PAUSED, RESUMING, pack_control, pack_control_ack,
    unpack_control_ack, pack_epoch_input, unpack_epoch_input,
)


class MatchServerRuntime(ServerRuntime):
  def __init__(self, settings, limits=None, engine_factory=None):
    if settings.handshake != 'negotiated':
      # 2026-09-10: input epochs require explicit v6 negotiation.
      # raise ValueError('Match v4 requires explicit version negotiation')
      # 2026-09-13: v7 is the only supported product match contract.
      # raise ValueError('Match v6 requires explicit version negotiation')
      raise ValueError('Match v7 requires explicit version negotiation')
    # 2026-09-13: both TCP and UDP inherit cooldowns expressed at product cadence.
    # super().__init__(settings, limits, engine_factory or native_match_engine)
    super().__init__(settings, limits, engine_factory or native_match_engine)
    from gfootball.frame_sync.server import BotTakeoverManager
    self.bots = BotTakeoverManager(rate_hz=MATCH_HZ)
    self._origin = None
    self._origin_digest = None
    self._ending = None
    self._end_acks = set()
    self._finish_requested = False
    # 2026-09-21: all concurrent public finish requests share one frame-boundary result.
    self._finish_future = None
    self.control = None
    self._desired_paused = self._driving_control = False

  def initialize(self):
    super().initialize()
    try:
      # One immutable origin shared by initial peers; per-peer output stays charged.
      # 2026-09-10: initialize the same control origin used by every first peer.
      # self._origin = pack_origin(self.settings, self.env, self.limits.snapshot_bytes)
      self.control = MatchControl(0, RUNNING, 0, self._state_hash())
      self._origin = pack_origin(self.settings, self.env, self.limits.snapshot_bytes, control=self.control)
      self._origin_digest = engine_digest(self.env)
    except BaseException:
      env, self.env = self.env, None
      self._origin = None
      self.closed = True
      self._closed_event.set()
      env.close()
      raise

  def _hello(self, peer):
    if self._ending is not None:
      raise ServerFailure('match_finished')
    if self.started:
      raise ServerFailure('session_already_started')
    if not peer.version_seen or not peer.issue_resume_token:
      raise ServerFailure('match_version_required')
    for slot, session in tuple(self.sessions.items()):
      if session.peer is None and self.loop.time() >= getattr(session, '_resume_until', 0):
        self.sessions.pop(slot)
    if self._origin is None or engine_digest(self.env) != self._origin_digest:
      raise ServerFailure('match_origin_changed')
    super()._hello(peer)
    peer.match_origin_control = self.control
    peer.match_pending_control = None
    peer.match_ack_epoch = None
    peer.match_last_ack = None
    self._queue(peer, wire.pack_state_snapshot(0, self._origin))

  def _snapshot_bytes(self):
    if not self.started and self._origin is not None:
      if engine_digest(self.env) != self._origin_digest:
        raise ServerFailure('match_origin_changed')
      return self._origin
    # 2026-09-10: active origins use their current frame/hash and session control.
    # return pack_origin(self.settings, self.env, self.limits.snapshot_bytes)
    control = MatchControl(self.control.epoch, self.control.phase, self.window.frame_id, self._state_hash())
    return pack_origin(self.settings, self.env, self.limits.snapshot_bytes, control=control)

  def _retain_lobby_session(self, session):
    if self.running and session.ever_ready:
      session._resume_until = self.loop.time() + min(30, self.limits.ready_timeout)
      return True
    return False

  def _resume_allowed(self, session):
    return self.started or (session.ever_ready and self._origin is not None
                           and self.loop.time() < getattr(session, '_resume_until', 0))

  def _resume(self, peer, packet):
    peer.match_origin_control = MatchControl(self.control.epoch, self.control.phase,
                                            self.window.frame_id, self._state_hash())
    peer.match_pending_control = None
    peer.match_ack_epoch = None
    peer.match_last_ack = None
    super()._resume(peer, packet)
    if self._ending is not None:
      self._queue(peer, self._ending)

  def _dispatch(self, peer, packet):
    kind = packet[0]
    if kind == wire.MessageType.MatchReady:
      try:
        # 2026-09-10: a snapshot from an abandoned epoch cannot hand back control.
        # unpack_match_ready(packet)
        _, epoch = unpack_match_ready(packet, include_epoch=True)
      except ValueError as error:
        raise ServerFailure('match_cadence_mismatch') from error
      # Release bounded output / hand back only after the v5 confirmation.
      # return super()._dispatch(peer, wire.pack_ready())
      origin = getattr(peer, 'match_origin_control', None)
      if origin is None or epoch != origin.epoch or epoch != self.control.epoch:
        raise ServerFailure('stale_match_ready')
      super()._dispatch(peer, wire.pack_ready())
      peer.match_ack_epoch = epoch
      peer.match_last_ack = origin
      self._drive_control()
      return
    if kind == wire.MessageType.Ready:
      raise ServerFailure('match_cadence_required')
    if kind == wire.MessageType.MatchEndAck:
      frame = struct.unpack_from('<I', packet, 1)[0]
      if self._ending is None or peer.phase != 'streaming' or frame != self.window.frame_id:
        raise ServerFailure('unexpected_match_end_ack')
      self._end_acks.add(peer.session.slot)
      self._changed.set()
      return
    # 2026-09-10: legacy inputs cannot bypass an epoch or reappear after resume.
    # if kind == wire.MessageType.FrameInput and self._ending is not None:
    #   if peer.phase != 'streaming':
    #     raise ServerFailure('input_before_ready')
    #   return
    if kind == wire.MessageType.FrameInput:
      raise ServerFailure('match_input_epoch_required')
    if kind == wire.MessageType.MatchControlAck:
      if peer.phase != 'streaming':
        raise ServerFailure('control_ack_before_ready')
      try:
        epoch, frame, digest = unpack_control_ack(packet)
      except ValueError as error:
        raise ServerFailure('invalid_control_ack') from error
      expected = getattr(peer, 'match_pending_control', None)
      last_ack = getattr(peer, 'match_last_ack', None)
      if last_ack is not None and (epoch, frame, digest) == (last_ack.epoch, last_ack.next_frame, last_ack.state_hash):
        return  # A duplicate cannot acknowledge or disturb a newer barrier.
      if expected is None:
        # A retransmission of the last preparation ACK can follow its commit.
        if (epoch == peer.match_ack_epoch == self.control.epoch
            and (frame, digest) == (self.control.next_frame, self.control.state_hash)):
          return
        raise ServerFailure('unexpected_control_ack')
      if (epoch, frame, digest) != (expected.epoch, expected.next_frame, expected.state_hash):
        raise ServerFailure('invalid_control_ack')
      peer.match_pending_control = None
      peer.match_ack_epoch = epoch
      peer.match_last_ack = expected
      self._changed.set()
      self._drive_control()
      return
    if kind == wire.MessageType.MatchEpochInput:
      if peer.phase != 'streaming':
        raise ServerFailure('input_before_ready')
      try:
        epoch, ordinary = unpack_epoch_input(packet, self.num_slots)
      except ValueError as error:
        raise ServerFailure('invalid_input') from error
      # 2026-09-10: current inputs are validated once by accept; discarded epochs
      # still undergo value/ownership validation without allocating a window row.
      # self.window.validate(ordinary, (peer.session.slot,))
      if epoch > self.control.epoch:
        raise ServerFailure('future_input_epoch')
      if epoch < self.control.epoch or self._ending is not None:
        self.window.validate(ordinary, (peer.session.slot,))
        return
      if self.control.phase != RUNNING or peer.match_ack_epoch != epoch:
        raise ServerFailure('input_while_paused')
      self.window.accept(ordinary, (peer.session.slot,))
      self._changed.set()
      return
    if kind == wire.MessageType.VersionNegotiate:
      version, minimum = wire.unpack_version_negotiate(packet)
      if peer.phase != 'hello' or peer.version_seen or minimum > version or not minimum <= MATCH_VERSION <= version:
        raise ServerFailure('match_version_required')
      peer.version_seen = peer.issue_resume_token = True
      self._hello(peer)
      return
    if kind == wire.MessageType.Connect:
      raise ServerFailure('match_version_required')
    if kind == wire.MessageType.ReconnectRequest:
      raise ServerFailure('match_version_required')
    if kind == wire.MessageType.MatchReconnectRequest:
      if peer.phase != 'hello':
        raise ServerFailure('unexpected_resume')
      try:
        token = unpack_match_reconnect(packet)
      except ValueError as error:
        raise ServerFailure('match_version_required') from error
      self._resume(peer, wire.pack_reconnect_request(token))
      return
    super()._dispatch(peer, packet)

  def _state_hash(self):
    # engine_digest validates bounded canonical data; wire hash is its first 8
    # SHA256 bytes interpreted little-endian, not a second hash of the hex text.
    return struct.unpack('<Q', bytes.fromhex(engine_digest(self.env))[:8])[0]

  def set_paused(self, paused):
    self._require_running()
    if type(paused) is not bool:
      raise ValueError('Pause request must be boolean')
    if self._ending is not None:
      raise ServerFailure('match_finished')
    self._desired_paused = paused
    self._drive_control()
    return self.control

  def _pending_control_peers(self):
    return [peer for peer in self.peers.values() if peer.phase == 'streaming'
            and getattr(peer, 'match_pending_control', None) is not None]

  def _establish_control(self, phase):
    previous = self.control
    epoch = previous.epoch if phase == RUNNING else previous.epoch + 1
    control = MatchControl(epoch, phase, self.window.frame_id, self._state_hash())
    control.validate_after(previous)
    if epoch != previous.epoch:
      self.window.clear()
    self.control = control
    packet = pack_control(control)
    if not self.started:
      self._origin = pack_origin(self.settings, self.env, self.limits.snapshot_bytes, control=control)
    for peer in tuple(self.peers.values()):
      if peer.phase == 'streaming':
        if phase != RUNNING:
          peer.match_pending_control = control
          peer.match_ack_deadline = self.loop.time() + min(3.0, self.limits.ready_timeout)
        self._queue(peer, packet)
      elif peer.phase == 'resuming' and phase == RUNNING:
        # A RESUMING origin can become RUNNING without changing epoch while the
        # snapshot is in flight. Deliver its commit before deferred authority.
        origin = getattr(peer, 'match_origin_control', None)
        if origin is not None and origin.epoch == epoch and origin.phase == RESUMING:
          self._queue(peer, packet, deferred=True)
    self._changed.set()

  def _drive_control(self):
    if (self._driving_control or self.collecting or not self.running or self._ending is not None
        or (not self.started and not self.participants_ready())):
      return
    self._driving_control = True
    try:
      # At most prepare+commit are needed for a latest desired state. Queue/drop
      # callbacks can reenter here, but never nest a second transition driver.
      for _ in range(3):
        if self._pending_control_peers():
          break
        if self.control.phase == RUNNING and self._desired_paused:
          self._establish_control(PAUSED)
        elif self.control.phase == PAUSED and not self._desired_paused:
          self._establish_control(RESUMING)
        elif self.control.phase == RESUMING:
          self._establish_control(RUNNING)
        else:
          break
    finally:
      self._driving_control = False

  def _expired(self, peer, now):
    # 2026-09-10: terminal End supersedes a pending pause ACK; its own bounded
    # finish/transport drain must not be interrupted by the old control timer.
    # if (getattr(peer, 'match_pending_control', None) is not None
    if (self._ending is None and getattr(peer, 'match_pending_control', None) is not None
        and now >= peer.match_ack_deadline):
      return 'control_ack_timeout'
    return super()._expired(peer, now)

  def _drop(self, peer, reason, *, notify=True):
    peer.match_pending_control = None
    super()._drop(peer, reason, notify=notify)
    self._drive_control()

  def participants_ready(self):
    self._owner()
    return len(self.sessions) == self.num_slots and all(
        session.peer is not None and session.peer.phase == 'streaming' for session in self.sessions.values())

  def all_ready(self):
    return self.participants_ready()

  async def run_frame(self, timeout_ms=None):
    self._require_running()
    if self._ending is not None:
      raise ServerFailure('match_finished')
    self._drive_control()
    if self.control.phase != RUNNING:
      raise ServerFailure('match_paused')
    # No first frame may be lost between local Ready enqueue and remote receipt.
    # Pending unassigned sockets do not count as match participants.
    if not self.started and not self.participants_ready():
      raise ServerFailure('participants_not_ready')
    # 2026-09-13: default product input collection fits one nominal frame, manual overrides remain explicit.
    # result = await super().run_frame(timeout_ms)
    # 2026-09-21: preserve the former natural-end-only boundary for review.
    # result = await super().run_frame(MATCH_CADENCE.frame_ms if timeout_ms is None else timeout_ms)
    # self._origin = self._origin_digest = None
    # if match_finished(self.env):
    #   # Authority/hash are already queued and collecting is false. End follows
    #   # the final frame on the same reliable byte stream for TCP and UDP.
    #   self.finish_match()
    # else:
    #   self._drive_control()
    # return result
    try:
      result = await super().run_frame(MATCH_CADENCE.frame_ms if timeout_ms is None else timeout_ms)
      self._origin = self._origin_digest = None
      if self._finish_future is not None or match_finished(self.env):
        # Authority/hash commit before End; no new frame can enter in between.
        self.finish_match()
      else:
        self._drive_control()
      return result
    except BaseException as error:
      if self._finish_future is not None and not self._finish_future.done():
        self._finish_future.set_exception(error)
      raise

  # 2026-09-10: centralize the default match cadence.
  # async def run_loop(self, rate_hz=10, wait_for_ready=True):
  async def run_loop(self, rate_hz=MATCH_HZ, wait_for_ready=True):
    self._require_running()
    # 2026-09-10: v5 peers agreed on a single real-time match cadence.
    # if type(rate_hz) not in (int, float) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
    #   raise ValueError('Invalid match server rate')
    MATCH_CADENCE.require_rate(rate_hz)
    if type(wait_for_ready) is not bool:
      raise ValueError('Expected a wait-for-ready flag')
    try:
      while self.running and self._ending is None and wait_for_ready and not self.participants_ready():
        self._changed.clear()
        await self._changed.wait()
      # 2026-09-10: keep the same async cadence in TCP and UDP match servers.
      # while self.running and self._ending is None:
      #   started = self.loop.time()
      #   await self.run_frame()
      #   await asyncio.sleep(max(0, 1 / rate_hz - (self.loop.time() - started)))
      pacer = FramePacer(rate_hz)
      while self.running and self._ending is None:
        if self.control.phase != RUNNING:
          self._changed.clear()
          await self._changed.wait()
          continue
        await pacer.wait_next_async()
        if not self.running or self._ending is not None:
          break
        # 2026-09-10: an owner request can establish a pause while the pacer waits.
        # await self.run_frame()
        if self.control.phase == RUNNING:
          await self.run_frame()
      deadline = self.loop.time() + 2
      # 2026-09-10: UDP also needs bounded time for final transport ACK retries.
      # while self.running and self._ending is not None and not self.finish_acknowledged():
      while self.running and self._ending is not None and not self.finish_settled():
        remaining = deadline - self.loop.time()
        if remaining <= 0:
          break
        self._changed.clear()
        try:
          await asyncio.wait_for(self._changed.wait(), remaining)
        except asyncio.TimeoutError:
          break
    finally:
      await self.close()

  async def close(self):
    try:
      await super().close()
    finally:
      if self._finish_future is not None and not self._finish_future.done():
        self._finish_future.set_exception(ServerFailure('closed'))
      self._origin = self._origin_digest = None
      self._ending = None
      self._end_acks.clear()

  async def request_finish(self):
    self._require_running()
    if not self.collecting:
      return self.finish_match()
    if self._finish_future is None:
      self._finish_future = self.loop.create_future()
      # A canceled caller cannot cancel the accepted request or another caller.
      # Observe an error even if every caller cancels before owner shutdown.
      self._finish_future.add_done_callback(lambda done: done.exception())
    return await asyncio.shield(self._finish_future)

  def finish_match(self):
    self._require_running()
    if self.collecting:
      raise ServerFailure('frame_in_progress')
    if self._ending is None:
      value = self.env.get_state_digest()
      if type(value) not in (str, bytes) or len(value) > self.limits.snapshot_bytes:
        raise ServerFailure('digest_capacity')
      # 2026-09-10: match the existing 64-bit canonical digest.
      # self._ending = struct.pack('<BII', wire.MessageType.MatchEnd, self.window.frame_id, wire.compute_state_hash(value))
      self._ending = struct.pack('<BIQ', wire.MessageType.MatchEnd, self.window.frame_id, wire.compute_state_hash(value))
      self._finish_requested = True
      for session in self.sessions.values():
        peer = session.peer
        if peer is not None and peer.phase in ('ready', 'streaming', 'resuming'):
          self._queue(peer, self._ending, deferred=peer.phase == 'resuming')
      self._changed.set()
    if self._finish_future is not None and not self._finish_future.done():
      self._finish_future.set_result(self.window.frame_id)
    return self.window.frame_id

  def finish_acknowledged(self):
    self._owner()
    return self._ending is not None and set(self.sessions).issubset(self._end_acks)

  def finish_settled(self):
    return self.finish_acknowledged()

  def stats(self):
    result = super().stats()
    result['origin_payload_bytes'] = len(self._origin) if self._origin is not None else 0
    result['match_protocol'] = MATCH_VERSION
    result['cadence'] = MATCH_CADENCE.to_dict()
    result['finished'] = self._ending is not None
    result['finish_acks'] = len(self._end_acks)
    result['control'] = dict(epoch=self.control.epoch, phase=self.control.phase,
                             next_frame=self.control.next_frame) if self.control is not None else None
    result['control_pending_peers'] = len(self._pending_control_peers())
    result['desired_paused'] = self._desired_paused
    return result


class MatchServer(FrameSyncServer):
  def set_paused(self, paused):
    return self._call(lambda: self._runtime.set_paused(paused))

  def pause(self):
    return self.set_paused(True)

  def resume(self):
    return self.set_paused(False)

  def _make_runtime(self, values, limits, engine_factory):
    return MatchServerRuntime(values, limits, engine_factory)

  # 2026-09-10: every configured controlled slot must have a ready participant.
  # def participants_ready(self, expected):
  #   if type(expected) is not int or not 1 <= expected <= self.num_slots:
  #     raise ValueError('Expected participant count must fit the match slots')
  #   return self._call(lambda: len(self._runtime.sessions) >= expected and self._runtime.all_ready())
  def participants_ready(self):
    return self._call(self._runtime.participants_ready)

  def finish_match(self):
    # 2026-09-21: serialize a public finish with the current frame commit.
    # return self._call(self._runtime.finish_match)
    return self._call(self._runtime.request_finish)

  def finish_acknowledged(self):
    return self._call(self._runtime.finish_acknowledged)

  def finish_settled(self):
    return self._call(self._runtime.finish_settled)

  # 2026-09-13: public TCP/UDP match facade agrees with its negotiated runtime.
  # def run_loop(self, rate_hz=10, wait_for_ready=True):
  def run_loop(self, rate_hz=MATCH_HZ, wait_for_ready=True):
    try:
      return super().run_loop(rate_hz, wait_for_ready)
    except asyncio.CancelledError:
      # The runtime's explicit match finish can close the owner event loop.
      if not self._runtime._finish_requested:
        raise


# 2026-09-10: share application handshake/End across TCP and cookie/epoch UDP.
# class MatchTCPClient(FrameSyncClient):
#   def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, resume_limits=None,
#                handshake='versioned', enable_resume=True):
#     if handshake != 'versioned' or enable_resume is not True:
#       raise ValueError('Match v4 requires versioned snapshot and token bootstrap')
#     if resume_limits is not None and not isinstance(resume_limits, MatchResumeLimits):
#       raise ValueError('Expected MatchResumeLimits')
#     super().__init__(host, port, controlled_slots_callback, limits=limits,
#                      resume_limits=resume_limits or MatchResumeLimits(), enable_resume=True)
# 
#   def _make_buffers(self, resume_token, expected_session, expected_slots, minimum_frame):
#     return MatchBuffers(self.limits, self.resume_limits, restoring=resume_token is not None,
#         expected_session=expected_session, expected_slots=expected_slots, minimum_frame=minimum_frame)
# 
#   def _hello_packet(self, resume_token):
#     # 2026-09-10: keep legacy receivers from treating this as a raw-state resume.
#     # return wire.pack_reconnect_request(resume_token) if resume_token is not None else wire.pack_version_negotiate(MATCH_VERSION, MATCH_VERSION)
#     return pack_match_reconnect(resume_token) if resume_token is not None else wire.pack_version_negotiate(MATCH_VERSION, MATCH_VERSION)
# 
#   @property
#   def match_end(self):
#     with self._lock:
#       return getattr(self._buffers, 'match_end', None)
# 
#   def acknowledge_end(self, frame):
#     if type(frame) is not int or not 0 <= frame <= 0xfffffff7:
#       raise ValueError('Invalid match end frame')
#     with self._lock:
#       if self._buffers.phase != 'streaming' or self._buffers.match_end is None or frame != self._buffers.match_end[0]:
#         raise ClientFailure('unexpected_match_end_ack')
#       return self._enqueue_locked(struct.pack('<BI', wire.MessageType.MatchEndAck, frame))
# 
#   def output_pending(self):
#     with self._lock:
#       return bool(self._send_queue)

class MatchClientProtocol:
  """Application protocol hooks on an existing bounded transport owner."""
  def get_match_control(self):
    with self._lock:
      return self._buffers.next_control()

  def acknowledge_control(self, control):
    with self._lock:
      if (type(control) is not MatchControl or control.phase == RUNNING
          or self._buffers.phase != 'streaming' or self._buffers.next_control() != control):
        return False
      if not self._buffers.pending_controls:
        return False
      if not self._enqueue_locked(pack_control_ack(control)):
        return False
      self._buffers.consume_control(control)
      self._buffers.timestamps.clear()
      return True

  def commit_control(self, control):
    with self._lock:
      if (type(control) is not MatchControl or control.phase != RUNNING
          or self._buffers.phase != 'streaming' or self._buffers.next_control() != control
          or not self._buffers.pending_controls):
        return False
      self._buffers.consume_control(control)
      return True

  def _send_frame_entries(self, frame_id, sample):
    with self._lock:
      control = self._buffers.applied_control
      if (self._buffers.phase != 'streaming' or control is None or control.phase != RUNNING
          or self._buffers.pending_controls):
        return False
      generation = self._generation
    try:
      entries = list(itertools.islice(iter(sample()), 23))
      with self._lock:
        if (generation != self._generation or self._buffers.phase != 'streaming'
            or self._buffers.applied_control != control or self._buffers.pending_controls):
          return False
        if not entries:
          return False
        if (len(entries) != len(self._buffers.slots)
            or any(slot != expected for (slot, value), expected in zip(entries, self._buffers.slots))):
          raise ValueError('Invalid owned match input slots')
        packet = pack_epoch_input(control.epoch, frame_id, entries)
        if not self._enqueue_locked(packet):
          return False
        self._buffers.record_send(frame_id, time.monotonic())
        return True
    except Exception:
      with self._lock:
        if generation == self._generation:
          self._fail_locked('invalid_input')
      raise

  def send_ready(self):
    with self._lock:
      if self._buffers.phase == 'streaming':
        return True
      if self._buffers.phase != 'ready' or getattr(self._buffers, 'cadence', None) != MATCH_CADENCE:
        return False
      # 2026-09-10: Ready confirms the control origin consumed by the logic owner.
      # if not self._enqueue_locked(pack_match_ready()):
      control = self._buffers.applied_control
      if control is None or not self._enqueue_locked(pack_match_ready(control.epoch)):
        return False
      self._buffers.phase = 'streaming'
      self._buffers.last_packet = time.monotonic()
      return True

  @property
  def match_cadence(self):
    with self._lock:
      cadence = getattr(self._buffers, 'cadence', None)
      return cadence.to_dict() if cadence is not None else None

  def _heartbeat_locked(self, now):
    # Terminal delivery is still handled by the IO worker. Stop producing new
    # probes so a finished client's UDP output can actually drain before close.
    # 2026-09-10: keep probes while the logic owner catches up to the final frame.
    # if getattr(self._buffers, 'match_end', None) is not None:
    #   return True
    if getattr(self, '_end_ack_queued', False):
      return True
    return super()._heartbeat_locked(now)

  def _make_buffers(self, resume_token, expected_session, expected_slots, minimum_frame):
    self._end_ack_queued = False
    return MatchBuffers(self.limits, self.resume_limits, restoring=resume_token is not None,
        expected_session=expected_session, expected_slots=expected_slots, minimum_frame=minimum_frame)

  def _hello_packet(self, resume_token):
    # 2026-09-10: keep legacy receivers from treating this as a raw-state resume.
    # return wire.pack_reconnect_request(resume_token) if resume_token is not None else wire.pack_version_negotiate(MATCH_VERSION, MATCH_VERSION)
    return pack_match_reconnect(resume_token) if resume_token is not None else wire.pack_version_negotiate(MATCH_VERSION, MATCH_VERSION)

  @property
  def match_end(self):
    with self._lock:
      return getattr(self._buffers, 'match_end', None)

  def acknowledge_end(self, frame):
    if type(frame) is not int or not 0 <= frame <= 0xfffffff7:
      raise ValueError('Invalid match end frame')
    with self._lock:
      if self._buffers.phase != 'streaming' or self._buffers.match_end is None or frame != self._buffers.match_end[0]:
        raise ClientFailure('unexpected_match_end_ack')
      # 2026-09-10: stop producing probes only after the final Ack is admitted.
      # return self._enqueue_locked(struct.pack('<BI', wire.MessageType.MatchEndAck, frame))
      accepted = self._enqueue_locked(struct.pack('<BI', wire.MessageType.MatchEndAck, frame))
      if accepted:
        self._end_ack_queued = True
      return accepted

  def output_pending(self):
    with self._lock:
      return bool(self._send_queue)


class MatchTCPClient(MatchClientProtocol, FrameSyncClient):
  def __init__(self, host, port, controlled_slots_callback=None, *, limits=None, resume_limits=None,
               handshake='versioned', enable_resume=True):
    if handshake != 'versioned' or enable_resume is not True:
      # 2026-09-10: v5 requires explicit cadence confirmation too.
      # raise ValueError('Match v4 requires versioned snapshot and token bootstrap')
      # raise ValueError('Match v5 requires versioned cadence, snapshot and token bootstrap')
      raise ValueError('Match v6 requires versioned cadence, control, snapshot and token bootstrap')
    if resume_limits is not None and not isinstance(resume_limits, MatchResumeLimits):
      raise ValueError('Expected MatchResumeLimits')
    super().__init__(host, port, controlled_slots_callback, limits=limits,
                     resume_limits=resume_limits or MatchResumeLimits(), enable_resume=True)

class MatchReconnectingClient(ReconnectingFrameSyncClient):
  def _make_logic(self, client, env, options, initial_frame_id=0):
    loop = super()._make_logic(client, env, dict(options, on_control=self._on_match_control), initial_frame_id)
    loop.initialize_control(client.get_match_control())
    return loop

  def attach_logic(self, env, *, rate_hz=MATCH_HZ, state_holder=None, limits=None):
    MATCH_CADENCE.require_rate(rate_hz)
    return super().attach_logic(env, rate_hz=rate_hz, state_holder=state_holder, limits=limits)

  # 2026-09-10: input state is cleared by its owner before control acknowledgements.
  # def __init__(self, *args, **kwargs):
  def __init__(self, *args, on_control=None, **kwargs):
    if on_control is not None and not callable(on_control):
      raise ValueError('Expected a control callback')
    self._on_match_control = on_control
    self._match_settings = None
    super().__init__(*args, **kwargs)

  def _new_client(self):
    return MatchTCPClient(self.host, self.port, self.controlled_slots_callback, **self._client_options)

  def connect_match(self, engine_factory=None, *, logic_limits=None):
    """Construct and initialize an owned engine from the verified wire origin."""
    env = None
    try:
      session, slots = self.connect()
      snapshot = self.client.take_resume_snapshot()
      if snapshot is None or snapshot[0] != 0:
        raise ClientFailure('missing_match_origin')
      settings, raw, digest, identity = unpack_origin(snapshot[1], session)
      env = (engine_factory or native_match_engine)(settings)
      require_identity(env, identity)
      env.set_state(raw)
      if engine_digest(env) != digest:
        raise ClientFailure('match_origin_digest')
      self._match_settings = settings_data(settings)
      self.attach_logic(env, limits=logic_limits)
      return env, settings, slots
    except BaseException as error:
      try:
        self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Match transport initialization cleanup also failed.')
      if env is not None:
        try:
          env.close()
        except BaseException:
          if hasattr(error, 'add_note'):
            error.add_note('Match engine initialization cleanup also failed.')
      raise

  def _restore_snapshot(self, payload):
    settings, raw, digest, identity = unpack_origin(payload, self._session)
    if settings_data(settings) != self._match_settings:
      raise ClientFailure('resume_match_settings_mismatch')
    require_identity(self._env, identity)
    self._env.set_state(raw)
    if engine_digest(self._env) != digest:
      raise ClientFailure('resume_match_digest')
