"""Pruebas dedicadas para la frontera de la acción focus_window (Subetapa 08.4)."""

from __future__ import annotations

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService


def test_focus_window_boundary_execution() -> None:
    backend = FakeDesktopAutomationBackend()
    service = DesktopAutomationService(backend=backend)
    service.emergency_stop.deactivate()

    req = DesktopActionRequest(
        action_type=DesktopActionType.FOCUS_WINDOW,
        target=DesktopActionTarget(window_handle=123456, process_id=789),
    )
    # Validar solicitud
    service.security_manager.validate_request(req)
