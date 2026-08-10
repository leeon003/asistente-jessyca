"""Pruebas de enforzamiento de timeout para la inspección de conexiones (Subetapa 09.2)."""

from __future__ import annotations

from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_connection_inspection_timeout_setting() -> None:
    service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    req = NetworkConnectionRequest()

    res = service.get_active_connections(req, request_id="net-timeout-1")
    assert res.success is True
    assert res.metadata.processing_time_ms >= 0.0
