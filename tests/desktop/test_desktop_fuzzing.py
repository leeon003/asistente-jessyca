"""Pruebas de fuzzing controlado para la frontera de seguridad de escritorio (Subetapa 08.1)."""

from __future__ import annotations

import pytest

from core.desktop_models import ScreenshotRequest
from core.desktop_security import DesktopSecurityError, DesktopSecurityManager


def test_controlled_desktop_fuzzing() -> None:
    sec = DesktopSecurityManager()

    invalid_requests = [
        ScreenshotRequest(x=-999999, y=0),
        ScreenshotRequest(x=0, y=-999999),
        ScreenshotRequest(width=0, height=500),
        ScreenshotRequest(width=500, height=0),
        ScreenshotRequest(width=-500, height=500),
        ScreenshotRequest(format="INVALID_FORMAT"),
        ScreenshotRequest(quality=0),
        ScreenshotRequest(quality=101),
    ]

    for req in invalid_requests:
        with pytest.raises(DesktopSecurityError):
            sec.validate_request(req)
