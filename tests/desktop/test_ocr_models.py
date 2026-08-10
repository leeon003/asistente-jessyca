"""Pruebas de los modelos inmutables del motor OCR (Subetapa 08.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.desktop_models import OCRBoundingBox, OCRMetadata, OCRRequest, OCRResult, OCRTextRegion


def test_ocr_request_immutability() -> None:
    req = OCRRequest(x=10, y=20, width=500, height=300, language="eng")

    assert req.x == 10
    assert req.width == 500
    assert req.language == "eng"

    with pytest.raises(AttributeError):
        req.language = "spa"  # type: ignore

    d = req.to_dict()
    assert d["has_image_base64"] is False


def test_ocr_bounding_box_and_region_immutability() -> None:
    box = OCRBoundingBox(x=5, y=5, width=100, height=20)
    region = OCRTextRegion(text="Hello World", bounding_box=box, confidence=0.98)

    assert region.text == "Hello World"
    assert region.bounding_box.width == 100
    assert region.confidence == 0.98

    with pytest.raises(AttributeError):
        region.confidence = 0.5  # type: ignore

    d = region.to_dict()
    assert d["bounding_box"]["x"] == 5


def test_ocr_result_and_metadata_immutability() -> None:
    meta = OCRMetadata(
        char_count=11,
        region_count=1,
        avg_confidence=0.98,
        processing_time_ms=12.5,
        backend_name="FakeOCRBackend",
        timestamp=datetime.now(UTC),
    )
    box = OCRBoundingBox(x=0, y=0, width=50, height=10)
    reg = OCRTextRegion(text="Hello World", bounding_box=box, confidence=0.98)

    res = OCRResult(recognized_text="Hello World", regions=(reg,), metadata=meta, truncated=False)

    assert res.metadata.char_count == 11
    assert res.regions[0].text == "Hello World"

    with pytest.raises(AttributeError):
        res.truncated = True  # type: ignore

    d = res.to_dict()
    assert d["metadata"]["backend_name"] == "FakeOCRBackend"
