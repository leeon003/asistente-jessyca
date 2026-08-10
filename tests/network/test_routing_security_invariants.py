"""Pruebas formales de verificación de las invariantes de seguridad de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import RoutingTableRequest
from core.network_routing_security import (
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_routing_security_invariants_fail_safe_deny() -> None:
    sec = NetworkRoutingSecurityManager()

    with pytest.raises(NetworkRoutingSecurityError):
        sec.validate_routing_request(RoutingTableRequest(metric=-99))


def test_routing_security_invariants_bounded_interface_length() -> None:
    sec = NetworkRoutingSecurityManager()
    sec.max_interface_len = 5

    sanitized = sec.validate_route(
        type(
            "MockRoute",
            (),
            {
                "destination": "0.0.0.0",
                "prefix_length": 0,
                "gateway": None,
                "interface": "VeryLongInterfaceName",
                "metric": 1,
                "protocol": "Static",
                "address_family": "IPv4",
                "route_type": "Default",
            },
        )()  # type: ignore
    )

    assert len(sanitized.interface) == 5
