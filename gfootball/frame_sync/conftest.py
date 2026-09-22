"""Explicit opt-in for legacy scripts that need a separately running server."""
import pytest


def pytest_addoption(parser):
    parser.addoption('--run-network-integration', action='store_true', default=False,
                     help='Run checks against an existing UDP server on port 12346')


def pytest_configure(config):
    config.addinivalue_line('markers', 'external_server: requires the live UDP game server')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--run-network-integration'):
        skip = pytest.mark.skip(reason='requires UDP game server; use --run-network-integration')
        for item in items:
            if 'external_server' in item.keywords:
                item.add_marker(skip)
