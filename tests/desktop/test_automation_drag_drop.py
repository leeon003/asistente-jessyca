"""Pruebas dedicadas para la frontera de la acción drag_and_drop (Subetapa 08.4)."""

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


def test_drag_and_drop_boundary_distance_validation() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.max_drag_distance = 300
    sec.emergency_stop.deactivate()

    # Arrastre válido (distancia ~141px < 300px)
    valid_req = DesktopActionRequest(
        action_type=DesktopActionType.DRAG_AND_DROP,
        target=DesktopActionTarget(x=100, y=100),
        dest_x=200,
        dest_y=200,
    )
    sec.validate_request(valid_req)

    # Arrastre excesivo (distancia 1000px > 300px)
    invalid_req = DesktopActionRequest(
        action_type=DesktopActionType.DRAG_AND_DROP,
        target=DesktopActionTarget(x=0, y=0),
        dest_x=1000,
        dest_y=0,
    )
    with pytest.raises(DesktopAutomationLimitExceededError):
        sec.validate_request(invalid_req)
