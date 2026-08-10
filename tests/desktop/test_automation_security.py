"""Pruebas de la frontera de seguridad DesktopAutomationSecurityManager (Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_automation_security import (
    DesktopAutomationLimitExceededError,
    DesktopAutomationSecurityError,
    DesktopAutomationSecurityManager,
)
from core.emergency_stop import get_emergency_stop_manager


def test_automation_security_manager_validates_correct_request() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.emergency_stop.deactivate()

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=100, y=200),
    )
    validated = sec.validate_request(req)
    assert validated.action_type == DesktopActionType.CLICK_ELEMENT


def test_automation_security_manager_rejects_out_of_bounds_coordinates() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.emergency_stop.deactivate()

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=-10, y=200),
    )
    with pytest.raises(DesktopAutomationSecurityError):
        sec.validate_request(req)


def test_automation_security_manager_rejects_excessive_text_length() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.max_text_length = 50
    sec.emergency_stop.deactivate()

    req = DesktopActionRequest(
        action_type=DesktopActionType.TYPE_TEXT,
        target=DesktopActionTarget(x=10, y=10),
        text="A" * 100,
    )
    with pytest.raises(DesktopAutomationLimitExceededError):
        sec.validate_request(req)


def test_automation_security_manager_rejects_excessive_drag_distance() -> None:
    sec = DesktopAutomationSecurityManager()
    sec.max_drag_distance = 500
    sec.emergency_stop.deactivate()

    req = DesktopActionRequest(
        action_type=DesktopActionType.DRAG_AND_DROP,
        target=DesktopActionTarget(x=0, y=0),
        dest_x=1000,
        dest_y=1000,
    )
    with pytest.raises(DesktopAutomationLimitExceededError):
        sec.validate_request(req)


def test_automation_security_manager_emergency_stop_active_denies_all() -> None:
    sec = DesktopAutomationSecurityManager()
    em = get_emergency_stop_manager()
    em.activate("Test Emergency Stop")

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=10, y=10),
    )

    try:
        with pytest.raises(DesktopAutomationSecurityError):
            sec.validate_request(req)
    finally:
        em.deactivate()
