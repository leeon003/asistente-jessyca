"""Pruebas de backends de automatización de escritorio (Subetapa 08.4)."""

from __future__ import annotations

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from tools.desktop.automation_backend import (
    FakeDesktopAutomationBackend,
    WindowsDesktopAutomationBackend,
)


def test_fake_automation_backend_records_action() -> None:
    backend = FakeDesktopAutomationBackend()
    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=50, y=50),
    )

    res = backend.execute_action(req, request_id="backend-test-1")

    assert res.success is True
    assert len(backend.executed_actions) == 1
    assert backend.executed_actions[0].action_type == DesktopActionType.CLICK_ELEMENT


def test_windows_automation_backend_graceful_fallback() -> None:
    backend = WindowsDesktopAutomationBackend()
    req = DesktopActionRequest(
        action_type=DesktopActionType.FOCUS_WINDOW,
        target=DesktopActionTarget(window_handle=99999999),
    )

    res = backend.execute_action(req, request_id="backend-test-2")

    assert res.success is True
