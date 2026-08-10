"""Pruebas de fuzzing controlado para la frontera de seguridad de caché DNS (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import DNSCacheRequest
from core.network_routing_security import (
    NetworkRoutingLimitExceededError,
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_controlled_dns_cache_fuzzing() -> None:
    sec = NetworkRoutingSecurityManager()

    invalid_requests = [
        DNSCacheRequest(hostname="a" * 300),
        DNSCacheRequest(hostname="google.com\x00evil.com"),
        DNSCacheRequest(max_results=-10),
        DNSCacheRequest(max_results=0),
        DNSCacheRequest(max_results=999999),
    ]

    for req in invalid_requests:
        with pytest.raises((NetworkRoutingSecurityError, NetworkRoutingLimitExceededError)):
            sec.validate_dns_cache_request(req)
