# 2026-09-10: legacy sync/async entrypoints over one bounded server implementation.
import asyncio
import concurrent.futures
import copy
import os
import threading

from gfootball.frame_sync.server_runtime import ServerRuntime, ServerSettings
from gfootball.frame_sync.server_state import ServerFailure


def settings(host, port, scenario, left, right, seed, hash_interval, handshake):
  return ServerSettings(host, port, scenario, left, right, seed, hash_interval, handshake)


class FrameSyncServer:
  """Synchronous calls; one private event loop owns network and engine operations.

  At most eight submitted API operations and one stop request may be pending.
  get_env() is a borrowed compatibility view; only use it when stepping is idle.
  Stop cannot interrupt a native engine call; it closes immediately after that
  call returns and raises if its owner thread cannot be joined within 30 seconds.
  """
  def __init__(self, listen_host='0.0.0.0', listen_port=12345,
               scenario_name='academy_empty_goal', left_agents=1, right_agents=0,
               game_engine_random_seed=42, state_hash_interval=0, *, limits=None,
               engine_factory=None, handshake='negotiated'):
    values = settings(listen_host, listen_port, scenario_name, left_agents, right_agents,
                      game_engine_random_seed, state_hash_interval, handshake)
    self.__dict__.update(vars(values))
    self.num_slots = left_agents + right_agents
    # 2026-09-10: UDP facade reuses control admission, engine ownership and joins.
    # self._runtime = ServerRuntime(values, limits, engine_factory)
    self._runtime = self._make_runtime(values, limits, engine_factory)
    self._pid = os.getpid()
    self._thread = self._loop = None
    self._started_event = threading.Event()
    self._stop_requested = threading.Event()
    self._lifecycle = threading.Lock()
    self._admission = threading.BoundedSemaphore(8)
    self._startup_error = None
    self._shutdown_error = None
    self._started_once = self._stop_scheduled = False
    self._last_stats = None

  def _make_runtime(self, values, limits, engine_factory):
    return ServerRuntime(values, limits, engine_factory)

  def _process(self):
    if self._pid != os.getpid():
      raise RuntimeError('Server cannot be shared across fork')

  def _worker(self):
    async def serve():
      self._loop = asyncio.get_running_loop()
      try:
        await self._runtime.start()
        self.listen_port = self._runtime.port
      except BaseException as error:
        self._startup_error = error
        self._started_event.set()
        return
      self._started_event.set()
      if self._stop_requested.is_set():
        await self._runtime.close()
      await self._runtime._closed_event.wait()

    try:
      asyncio.run(serve())
    except BaseException as error:
      # 2026-09-10: report owner shutdown failures through the public stop call.
      self._shutdown_error = error
      self._runtime.failure = self._runtime.failure or 'close_error'
      if not self._started_event.is_set():
        self._startup_error = error
        self._started_event.set()
    finally:
      # stats are copied after all loop tasks have completed; no live engine view.
      runtime = self._runtime
      self._last_stats = dict(running=False, closed=runtime.closed, failure=runtime.failure,
                              last_peer_failure=runtime.last_peer_failure, port=runtime.port,
                              connections=len(runtime.peers), sessions=len(runtime.sessions),
                              input=runtime.window.stats(), send_messages=0, send_bytes=0,
                              accepted=runtime.accepted, rejected=runtime.rejected, disconnected=runtime.disconnected)

  def start(self):
    self._process()
    with self._lifecycle:
      if self._started_once or self._stop_requested.is_set():
        raise RuntimeError('Create a fresh server for a new session')
      self._started_once = True
      self._thread = threading.Thread(target=self._worker, name='football-server-owner')
      self._thread.start()
    if not self._started_event.wait(30):
      self._stop_requested.set()
      raise ServerFailure('startup_timeout')
    if self._startup_error is not None:
      error, self._startup_error = self._startup_error, None
      self._thread.join(2)
      raise error

  def _call(self, operation, *args):
    self._process()
    if threading.current_thread() is self._thread:
      raise RuntimeError('Blocking server API cannot run inside its own event loop')
    if self._thread is None or not self._thread.is_alive() or self._loop is None:
      raise ServerFailure('closed')
    if not self._admission.acquire(blocking=False):
      raise ServerFailure('control_capacity')
    result = concurrent.futures.Future()
    task_ref = []

    async def invoke():
      value = operation(*args)
      return await value if asyncio.iscoroutine(value) else value

    def done(task):
      try:
        try:
          value = task.result()
        except BaseException as error:
          if not result.done():
            result.set_exception(error)
        else:
          if not result.done():
            result.set_result(value)
      except concurrent.futures.InvalidStateError:
        pass
      finally:
        self._admission.release()

    def schedule():
      if result.cancelled():
        self._admission.release()
        return
      if not self._runtime.running or self._runtime.closed:
        self._admission.release()
        if not result.done():
          result.set_exception(ServerFailure('closed'))
        return
      try:
        task = self._loop.create_task(invoke(), name='football-server-command')
        task_ref.append(task)
        task.add_done_callback(done)
      except BaseException as error:
        self._admission.release()
        if not result.done():
          result.set_exception(error)

    try:
      self._loop.call_soon_threadsafe(schedule)
    except BaseException:
      self._admission.release()
      raise
    try:
      # 2026-09-10: an event loop that terminates during submission cannot leave
      # a caller waiting forever on a callback that will never start.
      # return result.result()
      while True:
        try:
          return result.result(timeout=.1)
        except concurrent.futures.TimeoutError:
          if not self._thread.is_alive():
            raise ServerFailure('closed')
    except BaseException:
      result.cancel()
      if task_ref:
        try:
          self._loop.call_soon_threadsafe(task_ref[0].cancel)
        except RuntimeError:
          pass
      raise

  def stop(self):
    self._process()
    with self._lifecycle:
      self._stop_requested.set()
      thread = self._thread
      if thread is None or not thread.is_alive():
        return
      if self._loop is not None and not self._stop_scheduled:
        self._stop_scheduled = True

        def request_close():
          # 2026-09-10: do not create a late task while asyncio.run is already
          # shutting down after an internally failed frame or earlier close.
          if self._runtime.closed or self._runtime._closing_task is not None:
            return
          task = self._loop.create_task(self._runtime.close(), name='football-server-stop')
          # Observe close errors even when stop was signaled from another caller.
          def observed(done):
            try:
              done.result()
            except BaseException as error:
              self._runtime.failure = self._runtime.failure or 'close_error'
              self._shutdown_error = error
          task.add_done_callback(observed)

        try:
          self._loop.call_soon_threadsafe(request_close)
        except RuntimeError:
          pass
    if threading.current_thread() is not thread:
      thread.join(30)
      if thread.is_alive():
        raise RuntimeError('Server owner did not finish shutdown within 30 seconds')
      if self._shutdown_error is not None:
        error, self._shutdown_error = self._shutdown_error, None
        raise error

  close = stop

  def get_env(self):
    return self._call(lambda: self._runtime.env)

  def get_num_slots(self):
    return self.num_slots

  def get_frame_id(self):
    return self._call(lambda: self._runtime.window.frame_id)

  def get_current_frame_inputs(self):
    return self._call(self._runtime.window.current)

  def get_received_from(self):
    return self._call(lambda: set(self._runtime.window.received()))

  def get_connected_client_count(self):
    return self._call(self._runtime.connected_count)

  def all_clients_ready(self):
    return self._call(self._runtime.all_ready)

  def send_to_all(self, data):
    return self._call(self._runtime.broadcast, data)

  def get_session_tokens(self):
    return self._call(self._runtime.session_tokens)

  def run_one_frame(self, timeout_ms=None):
    return self._call(self._runtime.run_frame, timeout_ms)

  def run_loop(self, rate_hz=10, wait_for_ready=True):
    # 2026-09-10: explicit stop is a normal loop exit, even when owner shutdown
    # cancels a sleeping loop coroutine after its resources have been closed.
    # return self._call(self._runtime.run_loop, rate_hz, wait_for_ready)
    try:
      return self._call(self._runtime.run_loop, rate_hz, wait_for_ready)
    except asyncio.CancelledError:
      if not self._stop_requested.is_set():
        raise

  def stats(self):
    self._process()
    if self._thread is not None and not self._thread.is_alive() and self._last_stats is not None:
      return copy.deepcopy(self._last_stats)
    return self._call(self._runtime.stats)


class FrameSyncServerAsync:
  """Async facade; start() initializes the engine, await start_server() opens TCP.

  stop() requests shutdown on this event loop; await close_async() observes full
  socket/task/engine cleanup. An async context manager is available as well.
  """
  def __init__(self, listen_host='0.0.0.0', listen_port=12345,
               scenario_name='academy_empty_goal', left_agents=1, right_agents=0,
               game_engine_random_seed=42, state_hash_interval=0, *, limits=None,
               engine_factory=None, handshake='server_first'):
    values = settings(listen_host, listen_port, scenario_name, left_agents, right_agents,
                      game_engine_random_seed, state_hash_interval, handshake)
    self.__dict__.update(vars(values))
    self.num_slots = left_agents + right_agents
    self._runtime = ServerRuntime(values, limits, engine_factory)
    self._close_task = None

  def start(self):
    if self._close_task is not None:
      raise ServerFailure('closed')
    self._runtime.initialize()

  async def start_server(self):
    if self._close_task is not None:
      raise ServerFailure('closed')
    await self._runtime.start()
    self.listen_port = self._runtime.port

  def stop(self):
    self._runtime._owner()
    if self._close_task is None:
      # 2026-09-10: stop is effective before the scheduled cleanup gets a tick.
      # Resolve the loop before constructing a coroutine or changing state.
      # self._close_task = asyncio.create_task(self._runtime.close(), name='football-server-stop')
      loop = asyncio.get_running_loop()
      self._runtime.running = False
      self._runtime._changed.set()
      self._close_task = loop.create_task(self._runtime.close(), name='football-server-stop')
      def observe(task):
        if not task.cancelled():
          task.exception()
      self._close_task.add_done_callback(observe)

  async def close_async(self):
    self.stop()
    # 2026-09-10: cancelling a waiter must not cancel the shared cleanup owner.
    # await self._close_task
    await asyncio.shield(self._close_task)

  async def __aenter__(self):
    await self.start_server()
    return self

  async def __aexit__(self, kind, value, traceback):
    await self.close_async()

  def get_env(self):
    self._runtime._owner()
    return self._runtime.env

  def get_num_slots(self):
    return self.num_slots

  async def get_frame_id(self):
    self._runtime._owner()
    return self._runtime.window.frame_id

  async def get_current_frame_inputs(self):
    self._runtime._owner()
    return self._runtime.window.current()

  async def get_received_from(self):
    self._runtime._owner()
    return set(self._runtime.window.received())

  async def get_connected_client_count(self):
    return self._runtime.connected_count()

  async def all_clients_ready(self):
    return self._runtime.all_ready()

  async def send_to_all(self, data):
    return self._runtime.broadcast(data)

  async def get_session_tokens(self):
    return self._runtime.session_tokens()

  async def run_one_frame(self, timeout_ms=None):
    return await self._runtime.run_frame(timeout_ms)

  async def run_loop_async(self, rate_hz=10, wait_for_ready=True):
    if self._runtime.loop is None:
      await self.start_server()
    await self._runtime.run_loop(rate_hz, wait_for_ready)

  def stats(self):
    return self._runtime.stats()
