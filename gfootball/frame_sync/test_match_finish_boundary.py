"""Real TCP/UDP facade ordering with explicit non-native engine oracles."""
import asyncio
import inspect
import threading
import time
import pytest
from gfootball.frame_sync import protocol as wire
from gfootball.frame_sync.multiplayer_transport import MatchServer
from gfootball.frame_sync.multiplayer_udp import MatchUDPServer
from gfootball.frame_sync.multiplayer_runtime import NetworkPlayer
from gfootball.frame_sync.test_match_archive import MatchOracle
from gfootball.frame_sync.server_state import ServerFailure

def wait(predicate, pump=lambda: None):
  deadline = time.monotonic() + 3
  while not predicate():
    pump()
    assert time.monotonic() < deadline, "bounded boundary wait expired"
    time.sleep(.001)

@pytest.fixture(params=["tcp", "udp"])
def match(request):
  engines, loop_errors = [], []
  def factory(settings):
    env = MatchOracle(settings)
    engines.append(env)
    return env
  server_type = MatchServer if request.param == "tcp" else MatchUDPServer
  server = server_type(listen_host="127.0.0.1", listen_port=0, left_agents=1,
                       right_agents=0, engine_factory=factory, state_hash_interval=0)
  player = None
  try:
    server.start()
    server._call(lambda: server._runtime.loop.set_exception_handler(
        lambda loop, context: loop_errors.append(context)))
    player = NetworkPlayer("127.0.0.1", server.listen_port, transport=request.param,
                           engine_factory=factory, input_provider=lambda _: wire.default_slot_input())
    player.start()
    wait(server.participants_ready)
    async def collect():
      frame = asyncio.create_task(server._runtime.run_frame(3000))
      await asyncio.sleep(0)
      assert server._runtime.collecting
      assert server._runtime.window.frame_id == 0
      return frame
    frame = server._call(collect)
    yield server, player, frame
  finally:
    server.stop()
    if player is not None:
      player.close()
      assert not player.client.client.stats()["worker_alive"]
    assert not server._thread.is_alive()
    assert engines and all(env.closed == 1 for env in engines)
    if request.param == "udp":
      assert server._runtime._addresses == {}
      assert server._runtime._epochs == {}
    assert not loop_errors, loop_errors

def test_public_finish_commits_inflight_frame(match):
  server, player, frame = match
  attempted, results, errors = threading.Event(), [], []
  original_call = server._call
  def observed_call(operation, *args):
    if operation.__name__ not in ("finish_match", "request_finish"):
      return original_call(operation, *args)
    async def observe():
      attempted.set()
      result = operation(*args)
      return await result if inspect.iscoroutine(result) else result
    return original_call(observe)
  server._call = observed_call
  def finish():
    try:
      results.append(server.finish_match())
    except BaseException as error:
      errors.append(error)
  worker = threading.Thread(target=finish, name="football-finish-boundary")
  worker.start()
  try:
    assert attempted.wait(3)
    assert original_call(lambda: server._runtime.collecting)
    player.tick()
    worker.join(3)
    assert not worker.is_alive()
    assert errors == [], [repr(e) for e in errors]
    assert results == [1]
    async def committed():
      return await frame
    assert original_call(committed)[0] == 0
    assert server.finish_match() == 1
    wait(lambda: player.stats()["ended"], player.tick)
    assert player.stats()["final_frame"] == 1
    assert original_call(lambda: server._runtime.env.get_state_digest()) == player.env.get_state_digest()
    player.flush_end_ack()
    wait(server.finish_acknowledged)
  finally:
    if worker.is_alive():
      server.stop()
      worker.join(3)
    assert not worker.is_alive()

def requests(server, count=2):
  async def create():
    tasks = [asyncio.create_task(server._runtime.request_finish()) for _ in range(count)]
    await asyncio.sleep(0)
    shared = server._runtime._finish_future
    assert shared is not None and not shared.done()
    assert all(not task.done() for task in tasks)
    return tasks, shared
  return server._call(create)

def test_shared_finish_survives_waiter_cancel(match):
  server, player, frame = match
  tasks, shared = requests(server)
  async def cancel():
    tasks[0].cancel()
    result = await asyncio.gather(tasks[0], return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert not shared.done()
  server._call(cancel)
  player.tick()
  async def finish():
    assert await tasks[1] == 1
    assert (await frame)[0] == 0
    assert shared.result() == 1
    with pytest.raises(ServerFailure, match="match_finished"):
      await server._runtime.run_frame(0)
  server._call(finish)
  wait(lambda: player.stats()["ended"], player.tick)
  assert player.stats()["final_frame"] == 1

def test_pending_finish_settles_on_shutdown(match):
  server, player, frame = match
  tasks, shared = requests(server)
  # Observe frame failure even if asyncio shutdown cancels its facade waiter.
  server._call(lambda: frame.add_done_callback(lambda done: None if done.cancelled() else done.exception()))
  server.stop()
  assert shared.done() and not shared.cancelled()
  assert isinstance(shared.exception(), ServerFailure)
  assert shared.exception().reason == "closed"
  assert all(task.done() for task in tasks)
  for task in tasks:
    if not task.cancelled():
      task.exception()

def test_pending_finish_settles_on_engine_failure(match):
  server, player, frame = match
  tasks, shared = requests(server)
  server._call(lambda: setattr(server._runtime.env, "fail_step", True))
  server._call(lambda: frame.add_done_callback(lambda done: None if done.cancelled() else done.exception()))
  player.tick()
  wait(lambda: not server._thread.is_alive())
  assert frame.done() and not frame.cancelled()
  assert "Injected engine step failure" in str(frame.exception())
  assert shared.done() and not shared.cancelled()
  assert isinstance(shared.exception(), ServerFailure)
  assert all(task.done() for task in tasks)
  for task in tasks:
    if not task.cancelled():
      task.exception()

def test_pending_finish_settles_on_final_digest_failure(match):
  server, player, frame = match
  tasks, shared = requests(server)
  failure = RuntimeError("Injected final digest failure")
  def poison():
    def digest():
      raise failure
    server._runtime.env.get_state_digest = digest
  server._call(poison)
  player.tick()
  async def settled():
    results = await asyncio.gather(frame, *tasks, return_exceptions=True)
    assert all(value is failure for value in results)
    assert shared.exception() is failure
  server._call(settled)
