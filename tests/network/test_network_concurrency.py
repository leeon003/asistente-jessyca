"""Pruebas de concurrencia multi-hilo para el servicio de inspección de red (Subetapa 09.1)."""

from __future__ import annotations

import concurrent.futures

from core.network_models import NetworkInterfaceRequest
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.network_service import NetworkInspectionService


def test_concurrent_network_inspection_requests() -> None:
    service = NetworkInspectionService(backend=FakeNetworkInspectionBackend())

    def worker(worker_id: int) -> bool:
        res = service.get_network_interfaces(
            NetworkInterfaceRequest(include_disconnected=True),
            request_id=f"net-concurrent-{worker_id}",
        )
        return res.success and res.metadata.interface_count >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
