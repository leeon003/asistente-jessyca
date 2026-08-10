"""Pruebas del servicio NetworkInspectionService (Subetapa 09.1)."""

from __future__ import annotations

from core.network_models import NetworkInterfaceRequest
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.network_service import NetworkInspectionService


def test_network_inspection_service_returns_result() -> None:
    backend = FakeNetworkInspectionBackend()
    service = NetworkInspectionService(backend=backend)

    req = NetworkInterfaceRequest(include_disconnected=True)
    res = service.get_network_interfaces(req, request_id="net-service-test-1")

    assert res.success is True
    assert res.metadata.interface_count >= 1
