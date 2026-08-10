"""Pruebas formales de verificación de las invariantes de seguridad de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import DNSCacheRequest
from core.network_routing_security import (
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_dns_cache_security_invariants_fail_safe_deny() -> None:
    sec = NetworkRoutingSecurityManager()

    with pytest.raises(NetworkRoutingSecurityError):
        sec.validate_dns_cache_request(DNSCacheRequest(hostname="evil.com\x00"))


def test_dns_cache_security_invariants_bounded_hostname_length() -> None:
    sec = NetworkRoutingSecurityManager()
    sec.max_hostname_len = 10

    sanitized = sec.sanitize_hostname("verylongdomainnameexceedinglimit.com")
    assert len(sanitized) == 10
