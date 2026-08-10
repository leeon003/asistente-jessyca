"""Pruebas de concurrencia multi-hilo para el servicio OCR (Subetapa 08.2)."""

from __future__ import annotations

import concurrent.futures

from core.desktop_models import OCRRequest
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_concurrent_ocr_requests() -> None:
    service = OCRService(backend=FakeOCRBackend(mock_text="Concurrent OCR Test\nLine 2"))

    def worker(worker_id: int) -> bool:
        res = service.process_ocr(OCRRequest(width=500, height=300), request_id=f"ocr-concurrent-{worker_id}")
        return res.metadata.region_count == 2 and "Concurrent" in res.recognized_text

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
