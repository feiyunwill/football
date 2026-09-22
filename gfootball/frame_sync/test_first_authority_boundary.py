"""Force first authority to arrive after lobby peek but before logic drain."""
import time
from unittest import mock
import pytest
from gfootball.frame_sync.multiplayer_transport import MatchServer
from gfootball.frame_sync.multiplayer_udp import MatchUDPServer
from gfootball.frame_sync.multiplayer_runtime import NetworkPlayer
from gfootball.frame_sync.test_match_archive import MatchOracle

def wait(predicate, pump=lambda:None):
  deadline=time.monotonic()+3
  while not predicate():
    pump()
    assert time.monotonic()<deadline, "First authority boundary timed out"
    time.sleep(.001)

@pytest.mark.parametrize("transport",["tcp","udp"])
def test_consumed_first_authority_releases_lobby_and_prediction(transport):
  engines=[]
  def factory(settings):
    env=MatchOracle(settings);engines.append(env);return env
  server_type=MatchServer if transport=="tcp" else MatchUDPServer
  server=server_type(listen_host="127.0.0.1",listen_port=0,left_agents=1,right_agents=0,engine_factory=factory)
  player=None
  try:
    server.start()
    player=NetworkPlayer("127.0.0.1",server.listen_port,transport=transport,engine_factory=factory)
    player.start()
    wait(server.participants_ready)
    assert player.stats()["waiting_for_players"] is True
    assert player.client.logic.get_last_confirmed_frame_id()==-1
    channel=player.client.client;original_peek=channel.has_authoritative_frame
    crossed=[]
    def peek():
      # Capture the empty observation, then deliver a real socket authority before
      # returning it. This forces the same legal receive-thread interleaving.
      observed=original_peek()
      if not crossed:
        assert observed is False
        crossed.append(server.run_one_frame(0)[0])
        wait(original_peek)
      return observed
    with mock.patch.object(channel,"has_authoritative_frame",peek):
      result=player.tick()
    assert crossed==[0]
    assert player.client.logic.get_last_confirmed_frame_id()==0
    assert not original_peek()
    assert result["waiting_for_players"] is False, "Confirmed authority still classified as lobby"
    wait(lambda:player.client.logic.get_current_frame_id()>1,player.tick)
    assert server.get_frame_id()==1
  finally:
    server.stop()
    if player is not None:
      player.close()
      assert not player.client.client.stats()["worker_alive"]
    assert not server._thread.is_alive()
    assert engines and all(env.closed==1 for env in engines)
    if transport=="udp":
      assert server._runtime._addresses=={} and server._runtime._epochs=={}
