"""Pruebas de filtrado seguro de la tabla de ruteo (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_routing_filters_by_destination_gateway_and_family() -> None:
    backend = FakeRoutingTableInspectionBackend()
    service = RoutingTableInspectionService(backend=backend)

    # 1. Filtro por destino 0.0.0.0
    req1 = RoutingTableRequest(destination="0.0.0.0")
    res1 = service.get_routing_table(req1)
    assert len(res1.routes) == 1
    assert res1.routes[0].destination == "0.0.0.0"

    # 2. Filtro por gateway 192.168.1.1
    req2 = RoutingTableRequest(gateway="192.168.1.1")
    res2 = service.get_routing_table(req2)
    assert len(res2.routes) == 1
    assert res2.routes[0].gateway == "192.168.1.1"

    # 3. Filtro por IPv6
    req3 = RoutingTableRequest(address_family="IPv6")
    res3 = service.get_routing_table(req3)
    assert len(res3.routes) == 1
    assert res3.routes[0].address_family == "IPv6"
