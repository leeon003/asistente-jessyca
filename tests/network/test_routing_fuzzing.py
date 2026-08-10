"""Pruebas de fuzzing controlado para la frontera de seguridad de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import RoutingTableRequest
from core.network_routing_security import (
    NetworkRoutingLimitExceededError,
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_controlled_routing_fuzzing() -> None:
    sec = NetworkRoutingSecurityManager()

    invalid_requests = [
        RoutingTableRequest(metric=-10),
        RoutingTableRequest(address_family="INVALID_AF"),
        RoutingTableRequest(max_results=-10),
        RoutingTableRequest(max_results=0),
        RoutingTableRequest(max_results=999999),
        RoutingTableRequest(destination="256.256.256.256"),
        RoutingTableRequest(gateway="invalid_gateway_ip"),
    ]

    for req in invalid_requests:
        with pytest.raises((NetworkRoutingSecurityError, NetworkRoutingLimitExceededError)):
            sec.validate_routing_request(req)
