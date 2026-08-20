"""Pruebas de la frontera de seguridad NetworkRoutingSecurityManager para ruteo (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import RoutingTableRequest
from core.network_routing_security import (
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_routing_security_manager_validates_correct_request() -> None:
    sec = NetworkRoutingSecurityManager()
    req = RoutingTableRequest(address_family="IPv4", metric=10, max_results=100)

    validated = sec.validate_routing_request(req)
    assert validated.address_family == "IPv4"
    assert validated.metric == 10


def test_routing_security_manager_rejects_negative_metric() -> None:
    sec = NetworkRoutingSecurityManager()

    with pytest.raises(NetworkRoutingSecurityError):
        sec.validate_routing_request(RoutingTableRequest(metric=-5))


def test_routing_security_manager_rejects_invalid_destination_ip() -> None:
    sec = NetworkRoutingSecurityManager()

    with pytest.raises(NetworkRoutingSecurityError):
        sec.validate_routing_request(RoutingTableRequest(destination="invalid_ip_format"))
