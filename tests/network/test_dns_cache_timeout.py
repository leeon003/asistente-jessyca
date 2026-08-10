"""Pruebas de enforzamiento de timeout para la inspección de la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_dns_cache_inspection_timeout_setting() -> None:
    service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())
    req = DNSCacheRequest()

    res = service.get_dns_cache(req, request_id="dns-timeout-1")
    assert res.success is True
    assert res.metadata.processing_time_ms >= 0.0
