"""Pruebas dedicadas a la protección contra elementos UI obsoletos (Stale Target Protection - Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_automation_security import (
    DesktopAutomationSecurityManager,
    StaleTargetError,
)


def test_stale_target_protection_detects_changed_process_or_handle() -> None:
    sec = DesktopAutomationSecurityManager()

    target = DesktopActionTarget(process_id=1234, window_handle=55555)
    req = DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=target)

    # 1. UI idéntica -> Pasa validación
    current_ui_matching = {"process_id": 1234, "window_handle": 55555}
    assert sec.verify_target_freshness(req, current_ui_matching) is True

    # 2. UI cambió de Process ID -> Lanza StaleTargetError
    current_ui_changed_pid = {"process_id": 9999, "window_handle": 55555}
    with pytest.raises(StaleTargetError):
        sec.verify_target_freshness(req, current_ui_changed_pid)

    # 3. UI cambió de Window Handle -> Lanza StaleTargetError
    current_ui_changed_hwnd = {"process_id": 1234, "window_handle": 88888}
    with pytest.raises(StaleTargetError):
        sec.verify_target_freshness(req, current_ui_changed_hwnd)
