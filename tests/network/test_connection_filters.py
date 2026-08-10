"""Pruebas de filtrado seguro de conexiones activas y puertos (Subetapa 09.2)."""

from __future__ import annotations

from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_connection_filters_by_protocol_address_port_and_pid() -> None:
    backend = FakeNetworkConnectionInspectionBackend()
    service = NetworkConnectionInspectionService(backend=backend)

    # 1. Filtro por puerto local 54321
    req1 = NetworkConnectionRequest(local_port=54321)
    res1 = service.get_active_connections(req1)
    assert len(res1.connections) == 1
    assert res1.connections[0].local_endpoint.port == 54321

    # 2. Filtro por process_id 1234
    req2 = NetworkConnectionRequest(process_id=1234)
    res2 = service.get_active_connections(req2)
    assert len(res2.connections) == 1
    assert res2.connections[0].process_name == "chrome.exe"

    # 3. Filtro por estado ESTABLISHED
    req3 = NetworkConnectionRequest(state="ESTABLISHED")
    res3 = service.get_active_connections(req3)
    assert len(res3.connections) == 2
