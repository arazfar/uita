"""Ordinary tests cannot perform external network or real model inference."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_external_network_or_real_inference(monkeypatch):
    original = socket.socket.connect

    def guarded_connect(connection, address):
        if connection.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            if host not in ('127.0.0.1', '::1', 'localhost'):
                raise AssertionError('External network is disabled in ordinary tests; use a mock transport')
        return original(connection, address)

    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
    try:
        import pydantic_ai.models
    except ImportError:
        return
    monkeypatch.setattr(pydantic_ai.models, 'ALLOW_MODEL_REQUESTS', False)
