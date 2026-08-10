"""Pruebas de concurrencia y lecturas multi-hilo del Registro (Subetapa 06.4)."""

from __future__ import annotations

import concurrent.futures

from tools.registry.backend import FakeRegistryBackend
from tools.registry.registry_service import RegistryService


def test_concurrent_registry_reads() -> None:
    fake = FakeRegistryBackend()
    service = RegistryService(backend=fake)

    def worker(worker_id: int) -> bool:
        res = service.get_value("HKCU", "Software\\JessycaMCP", "Version")
        return res.value_data == "0.6.4"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
