"""Pruebas de concurrencia y consultas multi-hilo de procesos (Subetapa 06.3)."""

from __future__ import annotations

import concurrent.futures
import os

from tools.process.process_service import ProcessService


def test_concurrent_process_queries() -> None:
    service = ProcessService()
    current_pid = os.getpid()

    def worker(worker_id: int) -> bool:
        info = service.get_process(current_pid)
        return info.pid == current_pid

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
