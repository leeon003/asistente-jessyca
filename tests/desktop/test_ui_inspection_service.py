"""Pruebas del servicio UIInspectionService y redacción de secretos en elementos UI (Subetapa 08.3)."""

from __future__ import annotations

from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
)
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_ui_inspection_service_processes_and_sanitizes_element_names() -> None:
    # Backend que devuelve un elemento UI con un secreto expuesto en su propiedad Name
    secret_elem = UIElementInfo(
        automation_id="SecretField",
        name="User Password (password=SuperSecretToken123;)",
        control_type=UIControlType.EDIT,
        class_name="Edit",
        bounds=UIElementBounds(x=10, y=10, width=100, height=30),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=500,
        framework_id="Win32",
    )
    root = UIElementInfo(
        automation_id="WinRoot",
        name="Main Window",
        control_type=UIControlType.WINDOW,
        class_name="Window",
        bounds=UIElementBounds(x=0, y=0, width=500, height=400),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=500,
        framework_id="Win32",
        children=(secret_elem,),
    )

    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    service = UIInspectionService(backend=backend)

    req = UIElementRequest(max_depth=5)
    result = service.inspect_ui_elements(req, request_id="ui-service-test-1")

    # 1. El nombre del elemento sanitizado NUNCA debe contener la contraseña cruda
    elem_names = [e.name for e in result.elements_flat]
    for name in elem_names:
        assert "SuperSecretToken123" not in name

    assert result.metadata.element_count == 2


def test_ui_inspection_service_window_queries() -> None:
    backend = FakeUIInspectionBackend()
    service = UIInspectionService(backend=backend)

    active_win = service.get_active_window(request_id="test-active-win")
    assert active_win is not None
    assert active_win.hwnd == 1001
    assert active_win.is_active is True

    windows = service.list_windows(request_id="test-list-win")
    assert len(windows) == 2
    assert windows[0].title == "Jessyca MCP Application Window"
