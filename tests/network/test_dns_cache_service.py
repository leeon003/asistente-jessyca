"""Pruebas del servicio DNSCacheInspectionService (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_dns_cache_service_get_dns_cache() -> None:
    backend = FakeDNSCacheInspectionBackend()
    service = DNSCacheInspectionService(backend=backend)

    req = DNSCacheRequest(record_type="A")
    res = service.get_dns_cache(req, request_id="dns-serv-1")

    assert res.success is True
    assert len(res.entries) == 2
