"""Pruebas de backends de inspección de la tabla de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import (
    FakeRoutingTableInspectionBackend,
    WindowsRoutingTableInspectionBackend,
)


def test_fake_routing_backend_get_routing_table() -> None:
    backend = FakeRoutingTableInspectionBackend()
    req = RoutingTableRequest(address_family="IPv4")

    res = backend.get_routing_table(req)

    assert res.success is True
    assert len(res.routes) == 3
    assert all(r.address_family == "IPv4" for r in res.routes)


def test_windows_routing_backend_fallback() -> None:
    backend = WindowsRoutingTableInspectionBackend()
    req = RoutingTableRequest()

    res = backend.get_routing_table(req)

    assert res.success is True
    assert isinstance(res.routes, tuple)
