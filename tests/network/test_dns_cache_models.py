"""Pruebas de los modelos inmutables de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

import pytest

from core.network_routing_models import (
    DNSCacheEntry,
    DNSCacheRequest,
)


def test_dns_cache_entry_immutability_and_dict() -> None:
    entry = DNSCacheEntry(
        hostname="google.com",
        record_type="A",
        value="142.250.190.46",
        ttl=300,
        address_family="IPv4",
        status="Success",
    )

    assert entry.hostname == "google.com"
    assert entry.record_type == "A"
    assert entry.value == "142.250.190.46"

    # Inmutabilidad
    with pytest.raises(AttributeError):
        entry.ttl = 600  # type: ignore

    d = entry.to_dict()
    assert d["hostname"] == "google.com"
    assert d["record_type"] == "A"
