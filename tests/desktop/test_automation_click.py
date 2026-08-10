"""Pruebas dedicadas para la frontera de la acción click_element (Subetapa 08.4)."""

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


def test_click_element_boundary_validates_target_coordinates() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.emergency_stop.deactivate()

    # Coordenadas válidas
    req_valid = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=500, y=300),
    )
    sec.validate_request(req_valid)

    # Coordenadas fuera de pantalla
    req_invalid = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=99999, y=300),
    )
    with pytest.raises(DesktopAutomationSecurityError):
        sec.validate_request(req_invalid)
