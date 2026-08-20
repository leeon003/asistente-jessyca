"""Pruebas de la frontera de seguridad DesktopSecurityManager (Subetapa 08.1)."""

from __future__ import annotations

import pytest

from core.desktop_models import ScreenshotRequest
from core.desktop_security import (
    DesktopSecurityError,
    DesktopSecurityManager,
)


def test_desktop_security_manager_validates_correct_request() -> None:
    sec = DesktopSecurityManager()
    req = ScreenshotRequest(x=0, y=0, width=1920, height=1080, format="png", quality=90)

    validated = sec.validate_request(req)
    assert validated.format == "PNG"


def test_desktop_security_manager_rejects_negative_coordinates() -> None:
    sec = DesktopSecurityManager()

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(x=-10, y=0))

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(x=0, y=-5))


def test_desktop_security_manager_rejects_invalid_dimensions() -> None:
    sec = DesktopSecurityManager()

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(width=0, height=100))

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(width=-100, height=100))


def test_desktop_security_manager_rejects_unsupported_formats_or_invalid_quality() -> None:
    sec = DesktopSecurityManager()

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(format="EXE"))

    with pytest.raises(DesktopSecurityError):
        sec.validate_request(ScreenshotRequest(quality=150))
