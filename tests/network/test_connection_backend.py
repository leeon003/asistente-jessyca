"""Pruebas de backends de inspección de conexiones de red y puertos (Subetapa 09.2)."""

from __future__ import annotations

from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import (
    FakeNetworkConnectionInspectionBackend,
    WindowsNetworkConnectionInspectionBackend,
)


def test_fake_connection_backend_get_active_connections() -> None:
    backend = FakeNetworkConnectionInspectionBackend()
    req = NetworkConnectionRequest(protocol="TCP")

    res = backend.get_active_connections(req)

    assert res.success is True
    assert len(res.connections) == 2
    assert all(c.protocol == "TCP" for c in res.connections)


def test_fake_connection_backend_get_listening_ports() -> None:
    backend = FakeNetworkConnectionInspectionBackend()
    req = NetworkConnectionRequest(protocol="ANY")

    res = backend.get_listening_ports(req)

    assert res.success is True
    assert len(res.listening_ports) == 3


def test_windows_connection_backend_fallback() -> None:
    backend = WindowsNetworkConnectionInspectionBackend()
    req = NetworkConnectionRequest(max_results=50)

    res = backend.get_active_connections(req)

    assert res.success is True
    assert isinstance(res.connections, tuple)
