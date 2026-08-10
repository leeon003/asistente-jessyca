"""Pruebas de backends de extracción OCR (Subetapa 08.2)."""

from __future__ import annotations

from core.desktop_models import OCRRequest
from tools.desktop.ocr_backend import FakeOCRBackend, WindowsOCRBackend


def test_fake_ocr_backend_returns_mock_result() -> None:
    backend = FakeOCRBackend(mock_text="System Status: OK\nUser: Admin")
    req = OCRRequest(x=0, y=0, width=500, height=200)

    res = backend.extract_text(req)

    assert "System Status: OK" in res.recognized_text
    assert len(res.regions) == 2
    assert res.metadata.backend_name == "FakeOCRBackend"


def test_windows_ocr_backend_graceful_fallback() -> None:
    backend = WindowsOCRBackend()
    req = OCRRequest(x=0, y=0, width=100, height=100)

    res = backend.extract_text(req)

    assert res.recognized_text is not None
    assert len(res.regions) >= 1
