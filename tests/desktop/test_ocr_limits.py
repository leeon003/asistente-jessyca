"""Pruebas de enforzamiento de límites de texto y regiones OCR (Subetapa 08.2)."""

from __future__ import annotations

import pytest

from core.desktop_models import OCRRequest
from core.ocr_security import OCRLimitExceededError, OCRSecurityManager
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_ocr_service_truncates_excessive_text_or_regions() -> None:
    # Texto sintético masivo
    massive_text = "\n".join([f"Line {i}: Sample OCR content for testing" for i in range(100)])
    backend = FakeOCRBackend(mock_text=massive_text)

    service = OCRService(backend=backend)
    service.max_regions = 10
    service.max_text_length = 100

    req = OCRRequest(width=800, height=600)
    res = service.process_ocr(req, request_id="ocr-limit-req")

    assert res.truncated is True
    assert len(res.regions) <= 10
    assert len(res.recognized_text) <= 150
    assert "[OCR_TEXT_TRUNCATED]" in res.recognized_text


def test_ocr_security_limits_exceeded_dimensions() -> None:
    sec = OCRSecurityManager()
    sec.max_width = 1000
    sec.max_height = 1000

    with pytest.raises(OCRLimitExceededError):
        sec.validate_request(OCRRequest(width=1001, height=100))
