"""Pruebas de la frontera de seguridad OCR (OCRSecurityManager - Subetapa 08.2)."""

from __future__ import annotations

import pytest

from core.desktop_models import OCRBoundingBox, OCRRequest
from core.ocr_security import OCRLimitExceededError, OCRSecurityError, OCRSecurityManager


def test_ocr_security_manager_validates_correct_request() -> None:
    sec = OCRSecurityManager()
    req = OCRRequest(x=0, y=0, width=1920, height=1080, language="eng")

    validated = sec.validate_request(req)
    assert validated.width == 1920


def test_ocr_security_manager_rejects_negative_coords_or_dimensions() -> None:
    sec = OCRSecurityManager()

    with pytest.raises(OCRSecurityError):
        sec.validate_request(OCRRequest(x=-1, y=0))

    with pytest.raises(OCRSecurityError):
        sec.validate_request(OCRRequest(x=0, y=-5))

    with pytest.raises(OCRSecurityError):
        sec.validate_request(OCRRequest(width=-100, height=100))


def test_ocr_security_manager_rejects_nan_and_infinity_in_confidence() -> None:
    sec = OCRSecurityManager()

    with pytest.raises(OCRSecurityError):
        sec.validate_confidence(float("nan"))

    with pytest.raises(OCRSecurityError):
        sec.validate_confidence(float("inf"))

    with pytest.raises(OCRSecurityError):
        sec.validate_confidence(-0.5)


def test_ocr_security_manager_bounding_box_validation() -> None:
    sec = OCRSecurityManager()

    valid_box = OCRBoundingBox(x=10, y=20, width=100, height=50)
    sec.validate_bounding_box(valid_box)

    invalid_box = OCRBoundingBox(x=-1, y=20, width=100, height=50)
    with pytest.raises(OCRSecurityError):
        sec.validate_bounding_box(invalid_box)
