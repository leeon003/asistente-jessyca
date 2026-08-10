"""Pruebas de límites de texto, distancia y acciones de automatización (Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_automation_security import (
    DesktopAutomationLimitExceededError,
    DesktopAutomationSecurityManager,
)


def test_automation_limits_text_length_and_drag_distance() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.max_text_length = 20
    sec.max_drag_distance = 100
    sec.emergency_stop.deactivate()

    # 1. Texto excesivo
    with pytest.raises(DesktopAutomationLimitExceededError):
        sec.validate_request(
            DesktopActionRequest(
                action_type=DesktopActionType.TYPE_TEXT,
                target=DesktopActionTarget(x=0, y=0),
                text="A" * 25,
            )
        )

    # 2. Arrastre excesivo
    with pytest.raises(DesktopAutomationLimitExceededError):
        sec.validate_request(
            DesktopActionRequest(
                action_type=DesktopActionType.DRAG_AND_DROP,
                target=DesktopActionTarget(x=0, y=0),
                dest_x=200,
                dest_y=200,
            )
        )
