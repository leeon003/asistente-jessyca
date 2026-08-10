"""Pruebas de concurrencia multi-hilo para el servicio de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

import concurrent.futures

from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_concurrent_routing_inspection_requests() -> None:
    service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())

    def worker(worker_id: int) -> bool:
        res = service.get_routing_table(
            RoutingTableRequest(address_family="IPv4"),
            request_id=f"net-route-concurrent-{worker_id}",
        )
        return res.success and res.metadata.total_found >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
