"""Pruebas de concurrencia multi-hilo para el servicio de caché DNS (Subetapa 09.3)."""

from __future__ import annotations

import concurrent.futures

from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_concurrent_dns_cache_inspection_requests() -> None:
    service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())

    def worker(worker_id: int) -> bool:
        res = service.get_dns_cache(
            DNSCacheRequest(record_type="A"),
            request_id=f"net-dns-concurrent-{worker_id}",
        )
        return res.success and res.metadata.total_found >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
