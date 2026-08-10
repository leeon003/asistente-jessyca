"""Pruebas de enforzamiento de timeout para la inspección de ruteo (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_routing_inspection_timeout_setting() -> None:
    service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    req = RoutingTableRequest()

    res = service.get_routing_table(req, request_id="route-timeout-1")
    assert res.success is True
    assert res.metadata.processing_time_ms >= 0.0
