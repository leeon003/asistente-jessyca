"""Pruebas de concurrencia multi-hilo para el servicio de conexiones de red (Subetapa 09.2)."""

from __future__ import annotations

import concurrent.futures

from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_concurrent_connection_inspection_requests() -> None:
    service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())

    def worker(worker_id: int) -> bool:
        res = service.get_active_connections(
            NetworkConnectionRequest(protocol="TCP"),
            request_id=f"net-conn-concurrent-{worker_id}",
        )
        return res.success and res.metadata.total_found >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
