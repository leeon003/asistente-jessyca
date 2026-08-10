"""Pruebas de fuzzing controlado para la frontera de automatización de escritorio (Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_automation_security import (
    DesktopAutomationSecurityError,
    DesktopAutomationSecurityManager,
)


def test_controlled_automation_fuzzing() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.emergency_stop.deactivate()

    invalid_requests = [
        DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=DesktopActionTarget(x=-999, y=0)),
        DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=DesktopActionTarget(x=0, y=-999)),
        DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=DesktopActionTarget(x=999999, y=0)),
        DesktopActionRequest(action_type=DesktopActionType.TYPE_TEXT, target=DesktopActionTarget(x=0, y=0), text=None),
        DesktopActionRequest(action_type=DesktopActionType.DRAG_AND_DROP, target=DesktopActionTarget(x=0, y=0), dest_x=None, dest_y=None),
    ]

    for req in invalid_requests:
        with pytest.raises(DesktopAutomationSecurityError):
            sec.validate_request(req)
