"""Pruebas de enforzamiento de límites de resultados de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.network_routing_models import (
    DNSCacheEntry,
    DNSCacheMetadata,
    DNSCacheResult,
)
from core.network_routing_security import NetworkRoutingSecurityManager


def test_dns_cache_security_truncates_excessive_entries() -> None:
    sec = NetworkRoutingSecurityManager()
    sec.max_dns_entries = 2

    entries = tuple(
        DNSCacheEntry(
            hostname=f"host{i}.example.com",
            record_type="A",
            value=f"10.0.0.{i}",
            ttl=300,
            address_family="IPv4",
            status="Success",
        )
        for i in range(10)
    )

    res = DNSCacheResult(
        success=True,
        entries=entries,
        metadata=DNSCacheMetadata(10, 10, False, 1.0, "Mock", datetime.now(UTC)),
        message="OK",
    )

    sanitized = sec.validate_dns_cache_result(res)

    assert len(sanitized.entries) == 2
