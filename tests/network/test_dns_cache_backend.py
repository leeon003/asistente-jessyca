"""Pruebas de backends de inspección de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import (
    FakeDNSCacheInspectionBackend,
    WindowsDNSCacheInspectionBackend,
)


def test_fake_dns_cache_backend_get_dns_cache() -> None:
    backend = FakeDNSCacheInspectionBackend()
    req = DNSCacheRequest(record_type="A")

    res = backend.get_dns_cache(req)

    assert res.success is True
    assert len(res.entries) == 2
    assert all(e.record_type == "A" for e in res.entries)


def test_windows_dns_cache_backend_fallback() -> None:
    backend = WindowsDNSCacheInspectionBackend()
    req = DNSCacheRequest()

    res = backend.get_dns_cache(req)

    assert res.success is True
    assert isinstance(res.entries, tuple)
