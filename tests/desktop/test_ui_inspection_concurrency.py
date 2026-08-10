"""Pruebas de concurrencia multi-hilo para el servicio de inspección UI (Subetapa 08.3)."""

from __future__ import annotations

import concurrent.futures

from core.ui_inspection_models import UIElementRequest
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_concurrent_ui_inspection_requests() -> None:
    service = UIInspectionService(backend=FakeUIInspectionBackend())

    def worker(worker_id: int) -> bool:
        res = service.inspect_ui_elements(
            UIElementRequest(window_title=f"Worker Window {worker_id}"),
            request_id=f"ui-concurrent-{worker_id}",
        )
        return res.metadata.element_count >= 1 and f"Worker Window {worker_id}" in res.tree.root.name

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
