"""Pruebas de fuzzing controlado para la frontera de seguridad OCR (Subetapa 08.2)."""

from __future__ import annotations

import pytest

from core.desktop_models import OCRBoundingBox, OCRRequest
from core.ocr_security import OCRSecurityError, OCRSecurityManager


def test_controlled_ocr_fuzzing() -> None:
    sec = OCRSecurityManager()

    invalid_requests = [
        OCRRequest(x=-999999, y=0),
        OCRRequest(x=0, y=-999999),
        OCRRequest(width=0, height=500),
        OCRRequest(width=500, height=0),
        OCRRequest(width=-500, height=500),
    ]

    for req in invalid_requests:
        with pytest.raises(OCRSecurityError):
            sec.validate_request(req)

    # Test NaN e Infinity en BoundingBox y Confidence
    with pytest.raises(OCRSecurityError):
        sec.validate_bounding_box(OCRBoundingBox(x=-1, y=0, width=10, height=10))

    with pytest.raises(OCRSecurityError):
        sec.validate_confidence(float("nan"))

    with pytest.raises(OCRSecurityError):
        sec.validate_confidence(float("inf"))
