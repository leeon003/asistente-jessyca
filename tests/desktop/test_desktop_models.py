"""Pruebas de los modelos inmutables de escritorio (Subetapa 08.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.desktop_models import ScreenshotMetadata, ScreenshotRequest, ScreenshotResult


def test_screenshot_request_immutability() -> None:
    req = ScreenshotRequest(x=10, y=20, width=800, height=600, format="PNG", quality=90)

    assert req.x == 10
    assert req.width == 800
    assert req.format == "PNG"

    with pytest.raises(AttributeError):
        req.x = 50  # type: ignore

    d = req.to_dict()
    assert d["quality"] == 90


def test_screenshot_metadata_and_result_immutability() -> None:
    meta = ScreenshotMetadata(
        width=1920,
        height=1080,
        format="PNG",
        size_bytes=50000,
        pixel_count=2073600,
        timestamp=datetime.now(UTC),
        backend="FakeDesktopCaptureBackend",
    )
    res = ScreenshotResult(metadata=meta, image_base64="fakeb64data")

    assert res.metadata.pixel_count == 2073600
    assert res.image_base64 == "fakeb64data"

    with pytest.raises(AttributeError):
        res.image_base64 = "modified"  # type: ignore

    d = res.to_dict()
    assert d["metadata"]["width"] == 1920
