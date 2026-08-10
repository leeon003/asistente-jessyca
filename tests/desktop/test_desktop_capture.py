"""Pruebas de la captura de pantalla a través de DesktopService y backends desacoplados (Subetapa 08.1)."""

from __future__ import annotations

from core.desktop_models import ScreenshotRequest
from tools.desktop.backend import FakeDesktopCaptureBackend, WindowsDesktopCaptureBackend
from tools.desktop.desktop_service import DesktopService


def test_desktop_service_take_screenshot_with_fake_backend() -> None:
    fake_backend = FakeDesktopCaptureBackend()
    service = DesktopService(backend=fake_backend)

    req = ScreenshotRequest(width=1280, height=720, format="PNG")
    result = service.take_screenshot(req, request_id="test-req-fake")

    assert result.metadata.width == 1280
    assert result.metadata.height == 720
    assert result.metadata.backend == "FakeDesktopCaptureBackend"
    assert result.image_base64 is not None


def test_desktop_service_take_screenshot_with_windows_backend() -> None:
    service = DesktopService(backend=WindowsDesktopCaptureBackend())
    req = ScreenshotRequest(width=100, height=100, format="PNG")

    result = service.take_screenshot(req, request_id="test-req-win")

    assert result.metadata.width == 100
    assert result.metadata.height == 100
    assert result.image_base64 is not None
