"""Pruebas de enforzamiento de límites de resultados de ruteo (Subetapa 09.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.network_routing_models import (
    NetworkRoute,
    RoutingTableMetadata,
    RoutingTableResult,
)
from core.network_routing_security import NetworkRoutingSecurityManager


def test_routing_security_truncates_excessive_routes() -> None:
    sec = NetworkRoutingSecurityManager()
    sec.max_routes = 2

    routes = tuple(
        NetworkRoute(
            destination=f"10.0.{i}.0",
            prefix_length=24,
            gateway="10.0.0.1",
            interface="Eth",
            metric=10,
            protocol="Static",
            address_family="IPv4",
            route_type="Direct",
        )
        for i in range(10)
    )

    res = RoutingTableResult(
        success=True,
        routes=routes,
        metadata=RoutingTableMetadata(10, 10, False, 1.0, "Mock", datetime.now(UTC)),
        message="OK",
    )

    sanitized = sec.validate_routing_result(res)

    assert len(sanitized.routes) == 2
