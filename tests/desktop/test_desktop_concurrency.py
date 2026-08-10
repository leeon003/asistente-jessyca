"""Pruebas de concurrencia multi-hilo para el servicio de capturas de escritorio (Subetapa 08.1)."""

from __future__ import annotations

import concurrent.futures

from core.desktop_models import ScreenshotRequest
from tools.desktop.backend import FakeDesktopCaptureBackend
from tools.desktop.desktop_service import DesktopService


def test_concurrent_desktop_screenshot_requests() -> None:
    service = DesktopService(backend=FakeDesktopCaptureBackend())

    def worker(worker_id: int) -> bool:
        w = 100 + worker_id * 10
        h = 100 + worker_id * 10
        res = service.take_screenshot(ScreenshotRequest(width=w, height=h), request_id=f"concurrent-{worker_id}")
        return res.metadata.width == w and res.metadata.height == h

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
