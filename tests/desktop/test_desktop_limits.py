"""Pruebas de límites de dimensiones y píxeles en capturas de pantalla (Subetapa 08.1)."""

from __future__ import annotations

import pytest

from core.desktop_models import ScreenshotRequest
from core.desktop_security import DesktopLimitExceededError, DesktopSecurityManager


def test_desktop_limits_exceeded_dimensions() -> None:
    sec = DesktopSecurityManager()
    sec.max_width = 1000
    sec.max_height = 1000
    sec.max_pixels = 500000

    # 1. Ancho excesivo
    with pytest.raises(DesktopLimitExceededError):
        sec.validate_request(ScreenshotRequest(width=1001, height=100))

    # 2. Alto excesivo
    with pytest.raises(DesktopLimitExceededError):
        sec.validate_request(ScreenshotRequest(width=100, height=1001))

    # 3. Área total de píxeles excesiva (800 * 800 = 640000 > 500000)
    with pytest.raises(DesktopLimitExceededError):
        sec.validate_request(ScreenshotRequest(width=800, height=800))
