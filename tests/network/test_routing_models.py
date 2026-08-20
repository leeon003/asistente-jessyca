"""Pruebas de los modelos inmutables de la tabla de ruteo (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import (
    NetworkRoute,
)


def test_network_route_immutability_and_dict() -> None:
    route = NetworkRoute(
        destination="0.0.0.0",
        prefix_length=0,
        gateway="192.168.1.1",
        interface="Wi-Fi",
        metric=25,
        protocol="DHCP",
        address_family="IPv4",
        route_type="Default",
    )

    assert route.destination == "0.0.0.0"
    assert route.prefix_length == 0
    assert route.gateway == "192.168.1.1"

    # Inmutabilidad
    with pytest.raises(AttributeError):
        route.metric = 50  # type: ignore

    d = route.to_dict()
    assert d["destination"] == "0.0.0.0"
    assert d["address_family"] == "IPv4"
