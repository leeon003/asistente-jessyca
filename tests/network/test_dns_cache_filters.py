"""Pruebas de filtrado seguro de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_dns_cache_filters_by_hostname_record_type_and_value() -> None:
    backend = FakeDNSCacheInspectionBackend()
    service = DNSCacheInspectionService(backend=backend)

    # 1. Filtro por hostname google
    req1 = DNSCacheRequest(hostname="google")
    res1 = service.get_dns_cache(req1)
    assert len(res1.entries) == 1
    assert "google.com" in res1.entries[0].hostname

    # 2. Filtro por record_type AAAA
    req2 = DNSCacheRequest(record_type="AAAA")
    res2 = service.get_dns_cache(req2)
    assert len(res2.entries) == 1
    assert res2.entries[0].record_type == "AAAA"
