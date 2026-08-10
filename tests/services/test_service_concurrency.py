"""Pruebas de concurrencia y consultas multi-hilo de Servicios (Subetapa 06.5)."""

from __future__ import annotations

import concurrent.futures

from tools.services.backend import FakeServicesBackend
from tools.services.services_service import ServicesService


def test_concurrent_services_queries() -> None:
    fake = FakeServicesBackend()
    service = ServicesService(backend=fake)

    def worker(worker_id: int) -> bool:
        info = service.get_service("wuauserv")
        return info.service_name == "wuauserv"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
