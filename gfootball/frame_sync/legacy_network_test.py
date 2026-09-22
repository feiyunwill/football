"""Returning False from a CLI check must fail its pytest adapter."""
import pytest
from gfootball.frame_sync import test_determinism, test_e2e_udp, test_multi_client, test_reconnect

CHECKS = [test_determinism.test_two_clients, test_determinism.test_long_run,
          test_e2e_udp.test_basic_connection, test_e2e_udp.test_state_hash,
          test_e2e_udp.test_heartbeat, test_multi_client.test_two_clients,
          test_multi_client.test_four_clients, test_reconnect.test_basic_reconnect,
          test_reconnect.test_disconnect_detection, test_reconnect.test_exponential_backoff]


@pytest.mark.external_server
@pytest.mark.parametrize('check', CHECKS, ids=lambda check: check.__module__ + '.' + check.__name__)
def test_external_server_check(check):
    assert check() is True
