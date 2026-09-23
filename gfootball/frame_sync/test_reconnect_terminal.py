"""Controlled real TCP owner exit; reducer fixture is not GameEnv."""
import threading
import time
from unittest import mock
from gfootball.frame_sync.client_reconnect import ReconnectingFrameSyncClient, ReconnectLimits
from gfootball.frame_sync import test_reconnect_budget as fixtures
from gfootball.frame_sync.test_tcp_client_budget import until

def test_terminal_notification_waits_for_actual_worker_exit():
  fixture = fixtures.ReconnectClientTest()
  fixture.setUp()
  entered, release = threading.Event(), threading.Event()
  original = ReconnectingFrameSyncClient._work
  def held_work(client):
    try:
      original(client)
    finally:
      entered.set()
      if not release.wait(5):
        raise AssertionError('Test failed to release controlled owner exit')
  try:
    with mock.patch.object(ReconnectingFrameSyncClient, '_work', held_work):
      client, server, _ = fixture.make(reconnect_limits=ReconnectLimits(
          base_seconds=.02, max_seconds=.03, recovery_seconds=2, max_attempts=1))
      fixture.frame(client, server)
      calls = []
      client.set_on_give_up(lambda: calls.append((threading.current_thread(), client._worker.is_alive())))
      server.stop()
      assert entered.wait(2)
      assert client._worker.is_alive()
      before = client.stats()['total_attempts']
      started = time.monotonic()
      for _ in range(1000):
        client.tick()
      assert time.monotonic() - started < .15
      assert client.stats()['state'] != 'gave_up', 'Terminal state published before actual owner exit'
      assert calls == [], 'Callback published before actual owner exit'
      assert client.stats()['total_attempts'] == before
      release.set()
      until(lambda: not client._worker.is_alive())
      until(lambda: client.stats()['state'] == 'gave_up')
      client.tick()
      client.tick()
      assert calls == [(threading.current_thread(), False)]
      assert client.stats()['snapshot_bytes'] == 0
  finally:
    release.set()
    fixture.tearDown()
