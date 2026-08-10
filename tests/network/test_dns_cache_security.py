"""Pruebas de la frontera de seguridad NetworkRoutingSecurityManager para caché DNS (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import DNSCacheRequest
from core.network_routing_security import (
    NetworkRoutingSecurityError,
    NetworkRoutingSecurityManager,
)


def test_dns_cache_security_manager_validates_correct_request() -> None:
    sec = NetworkRoutingSecurityManager()
    req = DNSCacheRequest(hostname="google.com", max_results=100)

    validated = sec.validate_dns_cache_request(req)
    assert validated.hostname == "google.com"


def test_dns_cache_security_manager_rejects_hostname_with_control_chars() -> None:
    sec = NetworkRoutingSecurityManager()

    with pytest.raises(NetworkRoutingSecurityError):
        sec.validate_dns_cache_request(DNSCacheRequest(hostname="google.com\x00.evil.com"))


def test_dns_cache_security_manager_sanitizes_hostname_and_value() -> None:
    sec = NetworkRoutingSecurityManager()

    assert sec.sanitize_hostname("google.com\x01\x02") == "google.com"
    assert sec.sanitize_dns_value("142.250.190.46\x00") == "142.250.190.46"
