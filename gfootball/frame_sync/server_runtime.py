# 2026-09-10: one asynchronous owner for both TCP server APIs and native stepping.
"""Bounded sockets, input windows, resume history and explicit owner shutdown."""
from gfootball.frame_sync.frame_pacing import FramePacer, MATCH_HZ
import asyncio
from dataclasses import dataclass
import math
import secrets
import socket
import sys
import threading
import time

from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.resume_protocol import RESUME_VERSION, pack_session_token
from gfootball.frame_sync.server_state import (
    FrameInputWindow, MAX_FRAME, ServerDecoder, ServerFailure, ServerLimits, ServerSendQueue,
)
# 2026-09-13: generic v2/v3 engines keep the legacy configuration.
# from gfootball.frame_sync.match_cadence import MATCH_CADENCE
from gfootball.frame_sync.match_cadence import MATCH_CADENCE, LEGACY_HZ, LEGACY_PHYSICS_STEPS


@dataclass(frozen=True)
class ServerSettings:
  listen_host: str = '0.0.0.0'
  listen_port: int = 12345
  scenario_name: str = 'academy_empty_goal'
  left_agents: int = 1
  right_agents: int = 0
  game_engine_random_seed: int = 42
  state_hash_interval: int = 0
  handshake: str = 'negotiated'

  def __post_init__(self):
    if (type(self.listen_host) is not str or not 1 <= len(self.listen_host) <= 253
        or '\0' in self.listen_host or type(self.listen_port) is not int
        or not 0 <= self.listen_port <= 65535):
      raise ValueError('Invalid server address')
    if type(self.scenario_name) is not str or not 1 <= len(self.scenario_name) <= 256:
      raise ValueError('Invalid scenario name')
    if (any(type(value) is not int or not 0 <= value <= 11 for value in (self.left_agents, self.right_agents))
        or not 1 <= self.left_agents + self.right_agents <= 22):
      raise ValueError('Server requires 1..22 controlled slots and at most eleven per team')
    if type(self.game_engine_random_seed) is not int or not 0 <= self.game_engine_random_seed <= 0xffffffff:
      raise ValueError('Invalid engine seed')
    if type(self.state_hash_interval) is not int or not 0 <= self.state_hash_interval <= 1000000:
      raise ValueError('Invalid state hash interval')
    if self.handshake not in ('negotiated', 'server_first'):
      raise ValueError('Unknown server handshake mode')


# 2026-09-10: match factories share Core admission and own fresh, uncached leases.
# def native_engine(settings):
#   from gfootball_engine import GameEnv, GameState
#   from gfootball.frame_sync.server import get_scenario_config
#   env = GameEnv()
#   try:
#     env.game_config.render = False
#     env.game_config.physics_steps_per_frame = 10
#     env.game_config.render_resolution_x = 1280
#     env.game_config.render_resolution_y = 720
#     env.start_game()
#     scenario = get_scenario_config(settings.scenario_name, settings.left_agents,
#                                    settings.right_agents, settings.game_engine_random_seed)
#     env.state = GameState.game_running
#     env.reset(scenario, False)
#     return env
#   except BaseException as error:
#     try:
#       env.close()
#     except BaseException:
#       if hasattr(error, 'add_note'):
#         error.add_note('Native server engine construction cleanup also failed.')
#     raise

# 2026-09-10: share raw initialization inside one lease, including archive identity I/O.
# def native_engine(settings):
#   from gfootball_engine import GameEnv, GameState
#   from gfootball.engine_pool import EngineKey
#   from gfootball.owned_engine import create_owned_engine
#   from gfootball.frame_sync.server import get_scenario_config
#   if not isinstance(settings, ServerSettings):
#     raise ValueError('Expected ServerSettings')
#   key = EngineKey.current(1280, 720)
# 
#   def initialize():
#     # Admission precedes scenario work and native construction. A fresh lease
#     # prevents a matching cached training engine from skipping this setup.
#     scenario = get_scenario_config(settings.scenario_name, settings.left_agents,
#                                    settings.right_agents, settings.game_engine_random_seed)
#     env = GameEnv()
#     try:
#       env.game_config.render = False
#       env.game_config.physics_steps_per_frame = 10
#       env.game_config.render_resolution_x = key.width
#       env.game_config.render_resolution_y = key.height
#       env.start_game()
#       env.state = GameState.game_running
#       env.reset(scenario, False)
#       return env
#     except BaseException as error:
#       try:
#         env.close()
#       except BaseException:
#         if hasattr(error, 'add_note'):
#           error.add_note('Native server engine construction cleanup also failed.')
#       raise
# 
#   return create_owned_engine(key, initialize)

# 2026-09-10: display copies share scenario/cadence initialization under their own lease.
# def _initialize_native_engine(settings, key):
# 2026-09-13: only identified match owners opt into the negotiated cadence.
# def _initialize_native_engine(settings, key, *, rendering=False):
def _initialize_native_engine(settings, key, *, rendering=False, match_cadence=None):
  """Construct within an already reserved lease; never call without admission."""
  from gfootball_engine import GameEnv, GameState
  from gfootball.frame_sync.server import get_scenario_config
  scenario = get_scenario_config(settings.scenario_name, settings.left_agents,
                                 settings.right_agents, settings.game_engine_random_seed)
  # 2026-09-13: scale only a fresh match scenario before allocation/reset; legacy remains unchanged.
  # env = GameEnv()
  # try:
  #   # 2026-09-10: select rendering before native initialization.
  if match_cadence is not None:
    if type(match_cadence) is not type(MATCH_CADENCE) or match_cadence != MATCH_CADENCE:
      raise ValueError('Expected the supported match cadence')
    scenario.game_duration = match_cadence.scenario_frames(scenario.game_duration)
  env = GameEnv()
  try:
    # 2026-09-10: select rendering before native initialization.
    # env.game_config.render = False
    env.game_config.render = rendering
    # 2026-09-10: native construction uses the same simulated-time contract.
    # env.game_config.physics_steps_per_frame = 10
    # 2026-09-13: legacy callers do not inherit the v7 physical step count.
    # env.game_config.physics_steps_per_frame = MATCH_CADENCE.physics_steps
    env.game_config.physics_steps_per_frame = (LEGACY_PHYSICS_STEPS if match_cadence is None
                                               else match_cadence.physics_steps)
    env.game_config.render_resolution_x = key.width
    env.game_config.render_resolution_y = key.height
    env.start_game()
    env.state = GameState.game_running
    env.reset(scenario, False)
    return env
  except BaseException as error:
    try:
      env.close()
    except BaseException:
      if hasattr(error, 'add_note'):
        error.add_note('Native server engine construction cleanup also failed.')
    raise


def native_engine(settings):
  # The package establishes default data/font paths before the startup key.
  import gfootball_engine
  from gfootball.engine_pool import EngineKey
  from gfootball.owned_engine import create_owned_engine
  if not isinstance(settings, ServerSettings):
    raise ValueError('Expected ServerSettings')
  key = EngineKey.current(1280, 720)
  return create_owned_engine(key, lambda: _initialize_native_engine(settings, key))


class Session:
  def __init__(self, slot, token, peer):
    self.slot, self.token, self.peer = slot, token, peer
    self.ever_ready = False


class Peer:
  def __init__(self, identity, sock, address, limits, num_slots, now):
    self.identity, self.socket, self.address = identity, sock, address
    self.decoder = ServerDecoder(limits, num_slots)
    self.output = ServerSendQueue(limits)
    self.send_event = asyncio.Event()
    self.created = self.last_complete = self.rate_time = now
    self.tokens = float(limits.message_burst)
    self.partial_since = self.ready_since = None
    self.phase = 'hello'
    self.session = None
    self.task = self.writer_task = None
    self.version_seen = self.connect_seen = False
    self.issue_resume_token = False


class ServerRuntime:
  """Every operation, including engine calls, runs on the owning event loop."""
  def __init__(self, settings, limits=None, engine_factory=None):
    if not isinstance(settings, ServerSettings) or (limits is not None and not isinstance(limits, ServerLimits)):
      raise ValueError('Expected server settings and limits')
    if engine_factory is not None and not callable(engine_factory):
      raise ValueError('engine_factory must be callable')
    self.settings = settings
    self.limits = limits if limits is not None else ServerLimits()
    self.engine_factory = engine_factory or native_engine
    self.num_slots = settings.left_agents + settings.right_agents
    self.window = FrameInputWindow(self.limits, self.num_slots)
    self.env = self.listener = self.loop = None
    self._engine_thread = None
    self._accept_task = self._timer_task = None
    self.peers = {}
    self.sessions = {}
    self._next_peer = 0
    self._changed = asyncio.Event()
    self.running = self.started = self.collecting = False
    self.closed = False
    self._closing = False
    self._closing_task = None
    self._closed_event = asyncio.Event()
    self.failure = None
    self.last_peer_failure = None
    self.accepted = self.rejected = self.disconnected = 0
    self.port = settings.listen_port
    from gfootball.frame_sync.server import BotTakeoverManager
    self.bots = BotTakeoverManager()

  def _owner(self):
    if self._engine_thread is not None and threading.current_thread() is not self._engine_thread:
      raise RuntimeError('Server engine must stay on its owner thread')
    if self.loop is not None and asyncio.get_running_loop() is not self.loop:
      raise RuntimeError('Server operations must run on the owning event loop')

  def _require_running(self):
    self._owner()
    if not self.running or self.closed:
      raise ServerFailure('closed')

  def initialize(self):
    self._owner()
    if self.env is not None or self.closed:
      raise RuntimeError('Server engine already initialized or closed')
    # 2026-09-10: synchronous async-facade initialization owns its failure path.
    # self.env = self.engine_factory(self.settings)
    # if not all(callable(getattr(self.env, name, None)) for name in ('step_with_input', 'close')):
    #   raise ValueError('Server engine must provide step_with_input and close')
    try:
      # 2026-09-10: synchronous initialization may precede event-loop startup.
      # Keep the thread object, since thread identifiers may be reused after exit.
      self._engine_thread = threading.current_thread()
      self.env = self.engine_factory(self.settings)
      if not all(callable(getattr(self.env, name, None)) for name in ('step_with_input', 'close')):
        raise ValueError('Server engine must provide step_with_input and close')
    except BaseException as error:
      env, self.env = self.env, None
      self.closed = True
      self._closed_event.set()
      close = getattr(env, 'close', None)
      if callable(close):
        try:
          close()
        except BaseException:
          if hasattr(error, 'add_note'):
            error.add_note('Server engine validation cleanup also failed.')
      raise

  async def start(self):
    # 2026-09-10: reject migration before changing loop/socket ownership.
    self._owner()
    if self.loop is not None or self.closed:
      raise RuntimeError('Create a fresh server runtime for a new session')
    self.loop = asyncio.get_running_loop()
    try:
      # 2026-09-10: preserve the asyncio facade's synchronous start() engine setup.
      # self.env = self.engine_factory(self.settings)
      # if not all(callable(getattr(self.env, name, None)) for name in ('step_with_input', 'close')):
      #   raise ValueError('Server engine must provide step_with_input and close')
      if self.env is None:
        self.initialize()
      self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      self.listener.setblocking(False)
      self.listener.bind((self.settings.listen_host, self.port))
      self.listener.listen(min(self.limits.connections, 32))
      self.port = self.listener.getsockname()[1]
      self.running = True
      self._accept_task = asyncio.create_task(self._accept(), name='football-server-accept')
      self._timer_task = asyncio.create_task(self._maintain(), name='football-server-timer')
    except BaseException as error:
      try:
        await self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Server startup cleanup also failed.')
      raise

  async def _accept(self):
    try:
      while self.running:
        sock, address = await self.loop.sock_accept(self.listener)
        if len(self.peers) >= self.limits.connections or self._next_peer == 0xffffffffffffffff:
          self.rejected = min(0xffffffffffffffff, self.rejected + 1)
          sock.close()
          await asyncio.sleep(0)
          continue
        try:
          sock.setblocking(False)
          sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
          sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
          peer = Peer(self._next_peer, sock, address, self.limits, self.num_slots, self.loop.time())
          self._next_peer += 1
          self.peers[peer.identity] = peer
          self.accepted = min(0xffffffffffffffff, self.accepted + 1)
          peer.task = asyncio.create_task(self._read_peer(peer), name='football-server-peer')
          peer.task.add_done_callback(lambda task, owner=peer: self._peer_done(owner, task))
        except BaseException:
          sock.close()
          raise
        # Admission and worker counts are bounded even when rejected peers flood.
        await asyncio.sleep(0)
    except asyncio.CancelledError:
      raise
    except Exception:
      self.failure = 'accept_error'
      await self.close()

  def _queue(self, peer, data, *, deferred=False):
    if peer.phase == 'closed':
      return False
    try:
      # 2026-09-10: use the owner's monotonic clock for queue and write deadlines.
      # peer.output.enqueue(data, deferred=deferred)
      peer.output.enqueue(data, deferred=deferred, now=self.loop.time())
      peer.send_event.set()
      return True
    except ServerFailure as error:
      self._drop(peer, error.reason)
      return False

  def broadcast(self, data):
    self._require_running()
    if type(data) is not bytes or not data or sys.getsizeof(data) > self.limits.send_bytes:
      raise ServerFailure('invalid_output')
    for peer in tuple(self.peers.values()):
      if peer.phase in ('streaming', 'resuming'):
        self._queue(peer, data, deferred=peer.phase == 'resuming')

  def _hello(self, peer):
    if self.started:
      raise ServerFailure('session_already_started')
    free = next((slot for slot in range(self.num_slots) if slot not in self.sessions), None)
    if free is None:
      raise ServerFailure('session_capacity')
    # Host applications retrieve these opaque capabilities through session_tokens;
    # the legacy v2 wire has no token-issuance message. Never guess from seed/slot.
    # 2026-09-10: bound even a broken entropy provider's duplicate retry path.
    # token = secrets.randbits(64)
    # while token == 0 or any(session.token == token for session in self.sessions.values()):
    #   token = secrets.randbits(64)
    for _ in range(32):
      token = secrets.randbits(64)
      if token and not any(session.token == token for session in self.sessions.values()):
        break
    else:
      raise ServerFailure('token_unavailable')
    session = Session(free, token, peer)
    self.sessions[free] = peer.session = session
    peer.phase = 'ready'
    peer.ready_since = self.loop.time()
    # 2026-09-10: issue the random capability only to explicitly negotiated v3 peers.
    # self._queue(peer, wire.pack_session_start(self.settings.game_engine_random_seed,
    # self.settings.left_agents, self.settings.right_agents) + wire.pack_slot_assignment([free]))
    bootstrap = (wire.pack_session_start(self.settings.game_engine_random_seed,
                 self.settings.left_agents, self.settings.right_agents) + wire.pack_slot_assignment([free]))
    if peer.issue_resume_token:
      bootstrap += pack_session_token(session.token)
    self._queue(peer, bootstrap)
    self._changed.set()

  def _resume(self, peer, packet):
    token = wire.unpack_reconnect_request(packet)
    session = next((session for session in self.sessions.values() if session.token == token), None)
    if session is None or session.peer is not None:
      raise ServerFailure('invalid_resume_token')
    # 2026-09-10: match v4 may retain a bounded ready participant lease in its lobby.
    # if not self.started:
    #   raise ServerFailure('resume_requires_started_session')
    if not self._resume_allowed(session):
      raise ServerFailure('resume_requires_started_session')
    # 2026-09-10: Share resume lifecycle while allowing bounded versioned snapshot envelopes.
    # state = self.env.get_state('')
    # if type(state) is str:
    #   if len(state) > self.limits.snapshot_bytes:
    #     raise ServerFailure('snapshot_capacity')
    #   state = state.encode()
    # if type(state) is not bytes or not state or len(state) > self.limits.snapshot_bytes:
    #   raise ServerFailure('snapshot_capacity')
    state = self._snapshot_bytes()
    session.peer = peer
    peer.session = session
    peer.phase = 'resuming'
    peer.ready_since = self.loop.time()
    bootstrap = (wire.pack_session_start(self.settings.game_engine_random_seed,
                     self.settings.left_agents, self.settings.right_agents)
                 + wire.pack_slot_assignment([session.slot])
                 + wire.pack_state_snapshot(self.window.frame_id, state))
    self._queue(peer, bootstrap)
    for slot in self.bots.get_bot_slots():
      self._queue(peer, wire.pack_takeover_notify(slot, self.window.frame_id))

  def _snapshot_bytes(self):
    state = self.env.get_state('')
    if type(state) is str:
      if len(state) > self.limits.snapshot_bytes:
        raise ServerFailure('snapshot_capacity')
      state = state.encode()
    if type(state) is not bytes or not state or len(state) > self.limits.snapshot_bytes:
      raise ServerFailure('snapshot_capacity')
    return state

  def _resume_allowed(self, session):
    return self.started

  def _retain_lobby_session(self, session):
    return False

  def _dispatch(self, peer, packet):
    kind = packet[0]
    if kind == wire.MessageType.Disconnect:
      self._drop(peer, 'peer_disconnect')
      return
    if kind == wire.MessageType.VersionNegotiate:
      version, minimum = wire.unpack_version_negotiate(packet)
      # 2026-09-10: v3 adds token issuance without changing legacy v2 messages.
      # if peer.version_seen or minimum > version or not minimum <= wire.PROTOCOL_VERSION <= version:
      # raise ServerFailure('invalid_version')
      # peer.version_seen = True
      supports_resume = minimum <= RESUME_VERSION <= version
      supports_legacy = minimum <= wire.PROTOCOL_VERSION <= version
      if peer.version_seen or minimum > version or not (supports_resume or supports_legacy):
        raise ServerFailure('invalid_version')
      peer.version_seen = True
      peer.issue_resume_token = supports_resume
      if peer.phase == 'hello':
        self._hello(peer)
      elif self.settings.handshake != 'server_first' or peer.phase != 'ready':
        raise ServerFailure('unexpected_handshake')
      elif peer.issue_resume_token:
        self._queue(peer, pack_session_token(peer.session.token))
      return
    if kind == wire.MessageType.Connect:
      if peer.connect_seen:
        raise ServerFailure('unexpected_handshake')
      peer.connect_seen = True
      if peer.phase == 'hello':
        self._hello(peer)
      elif self.settings.handshake != 'server_first' or peer.phase != 'ready':
        raise ServerFailure('unexpected_handshake')
      return
    if kind == wire.MessageType.ReconnectRequest:
      if peer.phase != 'hello':
        raise ServerFailure('unexpected_resume')
      self._resume(peer, packet)
      return
    if kind == wire.MessageType.Heartbeat:
      if peer.phase == 'hello':
        raise ServerFailure('unexpected_heartbeat')
      wire.unpack_heartbeat(packet)
      return
    if kind == wire.MessageType.Ready:
      if peer.phase not in ('ready', 'resuming'):
        raise ServerFailure('unexpected_ready')
      was_resuming = peer.phase == 'resuming'
      peer.output.ready()
      peer.phase = 'streaming'
      peer.session.ever_ready = True
      peer.send_event.set()
      if was_resuming:
        self.bots.handback(peer.session.slot)
        self.broadcast(wire.pack_handback_notify(peer.session.slot, self.window.frame_id))
      self._changed.set()
      return
    if kind == wire.MessageType.FrameInput:
      if peer.phase != 'streaming':
        raise ServerFailure('input_before_ready')
      self.window.accept(packet, (peer.session.slot,))
      self._changed.set()
      return
    raise ServerFailure('unsupported_message')

  def _expired(self, peer, now):
    if peer.phase == 'hello' and now - peer.created >= self.limits.handshake_timeout:
      return 'handshake_timeout'
    if peer.phase in ('ready', 'resuming') and now - peer.ready_since >= self.limits.ready_timeout:
      return 'ready_timeout'
    if peer.phase == 'streaming' and now - peer.last_complete >= self.limits.idle_timeout:
      return 'idle_timeout'
    if peer.partial_since is not None and now - peer.partial_since >= self.limits.message_timeout:
      return 'message_timeout'
    return None

  async def _read_peer(self, peer):
    peer.writer_task = asyncio.create_task(self._write_peer(peer), name='football-server-writer')
    try:
      if self.settings.handshake == 'server_first' and not self.started:
        self._hello(peer)
      work = 0
      while self.running and peer.phase != 'closed':
        now = self.loop.time()
        reason = self._expired(peer, now)
        if reason:
          raise ServerFailure(reason)
        packet = peer.decoder.pop()
        if packet is not None:
          peer.tokens = min(self.limits.message_burst,
                            peer.tokens + max(0.0, now - peer.rate_time) * self.limits.messages_per_second)
          peer.rate_time = now
          if peer.tokens < 1:
            raise ServerFailure('message_rate')
          peer.tokens -= 1
          self._dispatch(peer, packet)
          peer.last_complete = now
          peer.partial_since = now if peer.decoder.data else None
          work += 1
          if work == 64:
            work = 0
            await asyncio.sleep(0)
          continue
        if peer.decoder.available <= 0:
          raise ServerFailure('receive_capacity')
        # 2026-09-10: transport hook preserves the shared bounded protocol owner.
        # data = await self.loop.sock_recv(peer.socket, min(4096, peer.decoder.available))
        data = await self._receive_peer(peer, min(4096, peer.decoder.available))
        if not data:
          raise ServerFailure('peer_eof')
        if not peer.decoder.data:
          peer.partial_since = self.loop.time()
        peer.decoder.feed(data)
    except ServerFailure as error:
      self._drop(peer, error.reason)
    except (OSError, ValueError):
      self._drop(peer, 'peer_io_error')
    except asyncio.CancelledError:
      raise
    except Exception:
      self._drop(peer, 'peer_internal_error')
    finally:
      self._drop(peer, 'peer_closed')
      if peer.writer_task is not None:
        peer.writer_task.cancel()
        await asyncio.gather(peer.writer_task, return_exceptions=True)
      peer.output.release_active()
      # 2026-09-10: task completion closes the descriptor after overlapped IO
      # cancellation has finished, including cancellation before the task starts.
      # self.peers.pop(peer.identity, None)

  def _peer_done(self, peer, task):
    if not task.cancelled():
      error = task.exception()
      if error is not None:
        self.last_peer_failure = 'peer_cleanup_error'
    # 2026-09-10: UDP peers borrow the listener; only TCP owns a descriptor here.
    # peer.socket.close()
    self._close_peer(peer)
    self.peers.pop(peer.identity, None)

  async def _receive_peer(self, peer, maximum):
    return await self.loop.sock_recv(peer.socket, maximum)

  async def _send_peer(self, peer, packet):
    await self.loop.sock_sendall(peer.socket, packet)

  def _close_peer(self, peer):
    peer.socket.close()

  def _shutdown_peer(self, peer):
    try:
      peer.socket.shutdown(socket.SHUT_RDWR)
    except OSError:
      pass

  async def _write_peer(self, peer):
    try:
      while self.running and peer.phase != 'closed':
        packet = peer.output.take()
        if packet is None:
          peer.send_event.clear()
          await peer.send_event.wait()
          continue
        try:
          # 2026-09-10: time spent queued cannot renew the original send deadline.
          # await asyncio.wait_for(self.loop.sock_sendall(peer.socket, packet), self.limits.write_timeout)
          remaining = peer.output.active_since + self.limits.write_timeout - self.loop.time()
          if remaining <= 0:
            raise asyncio.TimeoutError()
          # 2026-09-10: UDP fragmentation uses the same original queue deadline.
          # await asyncio.wait_for(self.loop.sock_sendall(peer.socket, packet), remaining)
          await asyncio.wait_for(self._send_peer(peer, packet), remaining)
        finally:
          peer.output.release_active()
    except asyncio.TimeoutError:
      self._drop(peer, 'write_timeout')
    except OSError:
      self._drop(peer, 'write_error')
    except asyncio.CancelledError:
      raise
    except Exception:
      self._drop(peer, 'writer_internal_error')

  def _drop(self, peer, reason, *, notify=True):
    if peer.phase == 'closed':
      return
    peer.phase = 'closed'
    self.last_peer_failure = reason
    self.disconnected = min(0xffffffffffffffff, self.disconnected + 1)
    peer.decoder.clear()
    peer.output.close()
    peer.send_event.set()
    # 2026-09-10: wake/cancel transport owners without closing a shared socket.
    # try:
    #   peer.socket.shutdown(socket.SHUT_RDWR)
    # except OSError:
    #   pass
    self._shutdown_peer(peer)
    # 2026-09-10: keep the real socket handle valid until both IO owners finish.
    # Closing before cancellation caused WinError 6 from Proactor overlapped IO.
    # peer.socket.close()
    current = asyncio.current_task()
    for task in (peer.task, peer.writer_task):
      if task is not None and task is not current:
        task.cancel()
    session = peer.session
    if session is not None and session.peer is peer:
      session.peer = None
      self.window.disconnect((session.slot,))
      if not self.started:
        # 2026-09-10: legacy sessions release immediately; v4 can retain a lease.
        # self.sessions.pop(session.slot, None)
        if not self._retain_lobby_session(session):
          self.sessions.pop(session.slot, None)
      else:
        self.bots.takeover(session.slot, int(session.slot >= self.settings.left_agents))
        if notify and self.running:
          self.broadcast(wire.pack_takeover_notify(session.slot, self.window.frame_id))
    self._changed.set()

  async def _maintain(self):
    next_heartbeat = self.loop.time() + self.limits.heartbeat_interval
    interval = min(0.05, min(self.limits.handshake_timeout, self.limits.ready_timeout,
                           self.limits.idle_timeout, self.limits.message_timeout) / 4)
    try:
      while self.running:
        await asyncio.sleep(interval)
        now = self.loop.time()
        for peer in tuple(self.peers.values()):
          if peer.phase != 'closed':
            reason = self._expired(peer, now)
            if reason:
              self._drop(peer, reason)
        if now >= next_heartbeat:
          heartbeat = wire.pack_heartbeat(self.window.frame_id, int(now * 1000) & 0xffffffff)
          for peer in tuple(self.peers.values()):
            if peer.phase in ('ready', 'streaming', 'resuming'):
              self._queue(peer, heartbeat)
          next_heartbeat = now + self.limits.heartbeat_interval
    except asyncio.CancelledError:
      raise
    except Exception:
      self.failure = 'maintenance_error'
      await self.close()

  def connected_count(self):
    self._owner()
    return sum(peer.phase != 'closed' for peer in self.peers.values())

  def all_ready(self):
    self._owner()
    live = tuple(peer for peer in self.peers.values() if peer.phase != 'closed')
    return bool(live) and all(peer.phase == 'streaming' for peer in live)

  def session_tokens(self):
    self._owner()
    return {slot: session.token for slot, session in self.sessions.items()}

  async def run_frame(self, timeout_ms=None):
    self._require_running()
    timeout_ms = wire.FRAME_INPUT_TIMEOUT_MS if timeout_ms is None else timeout_ms
    if type(timeout_ms) not in (int, float) or not math.isfinite(timeout_ms) or not 0 <= timeout_ms <= 30000:
      raise ValueError('Frame input timeout must be within 0..30000 milliseconds')
    if self.collecting:
      raise RuntimeError('A server frame is already in progress')
    if self.window.frame_id == MAX_FRAME:
      raise ServerFailure('frame_limit')
    self.collecting = self.started = True
    expected = tuple(session for session in self.sessions.values()
                     if session.peer is not None and session.peer.phase == 'streaming')
    deadline = self.loop.time() + timeout_ms / 1000.0
    try:
      while self.running:
        received = self.window.received()
        if all(session.peer is None or session.peer.phase != 'streaming' or session.slot in received
               for session in expected):
          break
        remaining = deadline - self.loop.time()
        if remaining <= 0:
          break
        self._changed.clear()
        try:
          await asyncio.wait_for(self._changed.wait(), remaining)
        except asyncio.TimeoutError:
          break
      self._require_running()
      received = self.window.received()
      inputs = self.window.seal()
      for slot in self.bots.get_bot_slots():
        if slot not in received:
          inputs[slot] = self.bots.generate_input(slot)
      self.env.step_with_input(b''.join(wire.pack_slot_input(value) for value in inputs))
      frame = self.window.frame_id
      output = wire.pack_authoritative_frame(frame, inputs)
      if self.settings.state_hash_interval and frame % self.settings.state_hash_interval == 0:
        digest = self.env.get_state_digest()
        if type(digest) not in (bytes, str) or len(digest) > self.limits.snapshot_bytes:
          raise ServerFailure('digest_capacity')
        output += wire.pack_state_hash(frame, wire.compute_state_hash(digest))
      self.broadcast(output)
      self.window.advance()
      return frame, inputs
    except BaseException as error:
      self.failure = self.failure or 'frame_error'
      try:
        await self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Server frame cleanup also failed.')
      raise
    finally:
      self.collecting = False

  # 2026-09-10: centralize the default match cadence.
  # async def run_loop(self, rate_hz=10, wait_for_ready=True):
  # 2026-09-13: preserve generic server default; the match subclass owns 50 Hz.
  # async def run_loop(self, rate_hz=MATCH_HZ, wait_for_ready=True):
  async def run_loop(self, rate_hz=LEGACY_HZ, wait_for_ready=True):
    self._require_running()
    if type(rate_hz) not in (int, float) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
      raise ValueError('Server rate must be within 1..240 Hz')
    if type(wait_for_ready) is not bool:
      raise ValueError('wait_for_ready must be a bool')
    try:
      while self.running and wait_for_ready and not self.all_ready():
        self._changed.clear()
        await self._changed.wait()
      # 2026-09-10: async authority uses fixed deadlines and yields even when late.
      # while self.running:
      #   before = self.loop.time()
      #   await self.run_frame()
      #   remaining = 1 / rate_hz - (self.loop.time() - before)
      #   if remaining > 0:
      #     await asyncio.sleep(remaining)
      pacer = FramePacer(rate_hz)
      while self.running:
        await pacer.wait_next_async()
        if not self.running:
          break
        await self.run_frame()
    finally:
      await self.close()

  # 2026-09-10: a dedicated cleanup owner survives cancellation of any caller.
  # async def close(self):
  #   self._owner()
  #   if self.closed:
  #     return
  #   if self._closing:
  #     if self._closing_task is not asyncio.current_task():
  #       await self._closed_event.wait()
  #     return
  #   self._closing = True
  #   self._closing_task = asyncio.current_task()
  #   self.running = False
  #   self._changed.set()
  #   current = asyncio.current_task()
  #   owned = [task for task in (self._accept_task, self._timer_task) if task is not None and task is not current]
  #   # 2026-09-10: cancel accept while its descriptor still exists, then close
  #   # only after the accept operation has completed cancellation.
  #   # if self.listener is not None:
  #   #   self.listener.close()
  #   #   self.listener = None
  #   for task in owned:
  #     task.cancel()
  #   for peer in tuple(self.peers.values()):
  #     self._drop(peer, 'server_closed', notify=False)
  #     if peer.task is not None and peer.task is not current:
  #       owned.append(peer.task)
  #   # Peer cancellation was already requested by _drop. A second cancel while
  #   # its finally awaits the writer could interrupt that cleanup operation.
  #   # for task in owned:
  #   #   task.cancel()
  #   try:
  #     if owned:
  #       await asyncio.gather(*owned, return_exceptions=True)
  #   finally:
  #     if self.listener is not None:
  #       self.listener.close()
  #       self.listener = None
  #     env, self.env = self.env, None
  #     self.peers.clear()
  #     self.sessions.clear()
  #     self.window.clear()
  #     for slot in self.bots.get_bot_slots():
  #       self.bots.handback(slot)
  #     self.closed = True
  #     self._closing = False
  #     try:
  #       if env is not None:
  #         env.close()
  #     finally:
  #       self._closing_task = None
  #       self._closed_event.set()
  #
  async def close(self):
    self._owner()
    if self.closed:
      return
    if self._closing_task is None:
      self._closing = True
      self._closing_task = asyncio.create_task(
          self._close_owned(asyncio.current_task()), name='football-server-cleanup')
      def observed(task):
        if task.cancelled() or task.exception() is not None:
          self.failure = self.failure or 'close_error'
      self._closing_task.add_done_callback(observed)
    # Caller cancellation cannot interrupt descriptor cleanup halfway through.
    await asyncio.shield(self._closing_task)

  async def _close_owned(self, exclude):
    self.running = False
    self._changed.set()
    current = exclude
    owned = [task for task in (self._accept_task, self._timer_task) if task is not None and task is not current]
    # 2026-09-10: cancel accept while its descriptor still exists, then close
    # only after the accept operation has completed cancellation.
    # if self.listener is not None:
    #   self.listener.close()
    #   self.listener = None
    for task in owned:
      task.cancel()
    for peer in tuple(self.peers.values()):
      self._drop(peer, 'server_closed', notify=False)
      if peer.task is not None and peer.task is not current:
        owned.append(peer.task)
    # Peer cancellation was already requested by _drop. A second cancel while
    # its finally awaits the writer could interrupt that cleanup operation.
    # for task in owned:
    #   task.cancel()
    try:
      if owned:
        await asyncio.gather(*owned, return_exceptions=True)
    finally:
      if self.listener is not None:
        self.listener.close()
        self.listener = None
      env, self.env = self.env, None
      self.peers.clear()
      self.sessions.clear()
      self.window.clear()
      for slot in self.bots.get_bot_slots():
        self.bots.handback(slot)
      self.closed = True
      self._closing = False
      try:
        if env is not None:
          env.close()
      finally:
        self._closing_task = None
        self._closed_event.set()

  def stats(self):
    self._owner()
    return dict(running=self.running, closed=self.closed, failure=self.failure,
                last_peer_failure=self.last_peer_failure, port=self.port,
                connections=len(self.peers), connected=self.connected_count(), sessions=len(self.sessions),
                bots=tuple(self.bots.get_bot_slots()), input=self.window.stats(),
                send_messages=sum(peer.output.messages for peer in self.peers.values()),
                send_bytes=sum(peer.output.payload_bytes for peer in self.peers.values()),
                receive_bytes=sum(sys.getsizeof(peer.decoder.data) for peer in self.peers.values()),
                accepted=self.accepted, rejected=self.rejected, disconnected=self.disconnected)
