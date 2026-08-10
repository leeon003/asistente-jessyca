"""Pruebas del servicio NetworkConnectionInspectionService (Subetapa 09.2)."""

from __future__ import annotations

from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_network_connection_service_get_active_connections() -> None:
    backend = FakeNetworkConnectionInspectionBackend()
    service = NetworkConnectionInspectionService(backend=backend)

    req = NetworkConnectionRequest(protocol="TCP")
    res = service.get_active_connections(req, request_id="net-conn-serv-1")

    assert res.success is True
    assert len(res.connections) == 2


def test_network_connection_service_get_listening_ports() -> None:
    backend = FakeNetworkConnectionInspectionBackend()
    service = NetworkConnectionInspectionService(backend=backend)

    req = NetworkConnectionRequest()
    res = service.get_listening_ports(req, request_id="net-port-serv-1")

    assert res.success is True
    assert len(res.listening_ports) == 3
