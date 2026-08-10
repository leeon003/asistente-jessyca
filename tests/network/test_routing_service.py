"""Pruebas del servicio RoutingTableInspectionService (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_routing_service_get_routing_table() -> None:
    backend = FakeRoutingTableInspectionBackend()
    service = RoutingTableInspectionService(backend=backend)

    req = RoutingTableRequest(address_family="IPv4")
    res = service.get_routing_table(req, request_id="route-serv-1")

    assert res.success is True
    assert len(res.routes) == 3
